"""Zamanlanmış mail kontrolleri: maili çek → sınıflandır → Haiku'ya özetlet → kaydet."""
import logging
import os
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db
from .analyze import analyze
from .classify import classify
from .ews import Ews, EwsError
from . import ajanda, bildirim

log = logging.getLogger("ea.jobs")
TZ = ZoneInfo("Europe/Istanbul")
_run_lock = threading.Lock()
scheduler = BackgroundScheduler(timezone=TZ)


def _hours_for(kind):
    if kind in ("sabah", "guncel"):
        return 24  # sayfa her zaman son 24 saatin tam tablosunu gösterir
    # Ara kontrol: bir önceki rapordan bu yana (en az 3, en fazla 12 saat)
    last = db.list_reports(1)
    if last:
        try:
            prev = datetime.fromisoformat(last[0]["created_at"]).astimezone(TZ)
            h = int((datetime.now(TZ) - prev).total_seconds() // 3600) + 1
            return max(3, min(12, h))
        except ValueError:
            pass
    return 5


def run(kind="sabah", hours=None):
    if not _run_lock.acquire(blocking=False):
        return None, "Zaten bir kontrol çalışıyor."
    try:
        cfg = db.get_settings()
        hours = hours or _hours_for(kind)
        limit = float(cfg.get("aylik_limit_usd") or 0)
        spent = db.month_cost()
        if limit and spent >= limit:
            msg = "Aylık API limiti ($%.2f) doldu; bu kontrol atlandı. Ayarlar'dan limiti artırabilirsiniz." % limit
            return db.add_report(kind, hours, "atlandi", error=msg), msg
        if not os.environ.get("ANTHROPIC_API_KEY"):
            msg = "ANTHROPIC_API_KEY ayarlanmamış."
            return db.add_report(kind, hours, "hata", error=msg), msg
        user = os.environ.get("EWS_USER", "")
        cfg["user"] = user
        ews = Ews(os.environ.get("EWS_HOST", ""), user, os.environ.get("EWS_PASSWORD", ""))
        msgs, total = ews.find_messages(hours)
        cfg["_total"] = total
        result = classify(msgs, cfg)
        ids = [m["id"] for sec in ("sikayet", "odeme", "ortak", "vip", "mine") for m in result["sections"].get(sec, [])]
        ids += [b["latest"]["id"] for b in result["busy"]]
        bodies = ews.get_bodies(ids, limit=90)
        now = datetime.now(TZ)
        label = "%s → %s" % ((now - timedelta(hours=hours)).strftime("%d.%m %H:%M"), now.strftime("%d.%m %H:%M"))
        data, cands, usage = analyze(result, bodies, cfg, label)
        data["_links"] = {str(i + 1): ews.owa_link(m["id"]) for i, m in enumerate(cands)}
        data["_ids"] = {str(i + 1): m["id"] for i, m in enumerate(cands)}
        data["_gruplar"] = result["others"].most_common(12)
        stats = {"total": total, "scanned": len(msgs), "others_total": result["others_total"],
                 "candidates": len(cands), "period": label}
        rid = db.add_report(kind, hours, "ok", stats=stats, data=data, usage=usage)
        db.prune_reports()
        log.info("Rapor %s hazır: %s mail, $%.4f", rid, total, usage["cost"])
        return rid, None
    except EwsError as e:
        return db.add_report(kind, hours or 0, "hata", error=str(e)), str(e)
    except Exception as e:  # beklenmeyen hata: kaydet, sunucuyu düşürme
        log.exception("Kontrol başarısız")
        msg = "Beklenmeyen hata: %s" % e.__class__.__name__
        return db.add_report(kind, hours or 0, "hata", error=msg), msg
    finally:
        _run_lock.release()


GUNCEL_DK = 3  # linkten yenileyince hep kontrol et; yalnızca rapor bitince sayfanın kendi yenilemesinde ikinci kez başlatma
_ajanda_son = [0.0]


def calisiyor():
    return _run_lock.locked()


def guncelle_baslat():
    """Mail sayfası açılınca/yenilenince çağrılır. Son kontrol GUNCEL_DK dakikadan eskiyse
    son 24 saati arka planda yeniden kontrol eder. Son kontrol hatalıysa 15 dk beklenir: Exchange'e
    art arda hatalı giriş denemesi yapılmaz. Dönüş: "calisiyor" | "basladi" | "guncel"."""
    if _run_lock.locked():
        return "calisiyor"
    last = db.list_reports(1)
    if last:
        try:
            prev = datetime.fromisoformat(last[0]["created_at"])
            bekle = GUNCEL_DK if last[0]["status"] == "ok" else 15  # hatadan sonra Exchange'i 15 dk zorlama (hesap kilitlenmesin)
            if (datetime.now(prev.tzinfo) - prev).total_seconds() < bekle * 60:
                return "guncel"
        except ValueError:
            pass
    threading.Thread(target=run, args=("guncel", 24), daemon=True).start()
    return "basladi"


def ajanda_guncelle():
    """Ajanda sayfası açılınca/yenilenince: "EA:" maillerini hemen işle (en sık dakikada bir)."""
    import time
    if time.time() - _ajanda_son[0] < 60:
        return
    _ajanda_son[0] = time.time()
    threading.Thread(target=ajanda_tick, daemon=True).start()


def start():
    cfg = db.get_settings()
    scheduler.remove_all_jobs()
    for part in (cfg.get("takvim") or "").split(";"):
        if "=" not in part:
            continue
        t, kind = [x.strip() for x in part.split("=", 1)]
        try:
            hh, mm = [int(x) for x in t.split(":")]
        except ValueError:
            continue
        kind = kind if kind in ("sabah", "ara", "guncel") else "guncel"
        scheduler.add_job(run, CronTrigger(hour=hh, minute=mm, timezone=TZ), args=[kind],
                          id="kontrol-%s" % t, replace_existing=True, misfire_grace_time=3600, coalesce=True)
        # Takvim doluysa ajanda ("EA:" mailleri) da aynı saatlerde güncellenir. Varsayılan takvim boş: otomatik güncelleme yok.
        scheduler.add_job(ajanda_tick, CronTrigger(hour=hh, minute=mm, timezone=TZ), id="ajanda-%s" % t,
                          replace_existing=True, misfire_grace_time=900, coalesce=True)
    scheduler.add_job(hatirlatma_tick, CronTrigger(minute="*/5", timezone=TZ), id="hatirlatma",
                      replace_existing=True, misfire_grace_time=300, coalesce=True)
    if not scheduler.running:
        scheduler.start()


def ajanda_tick():
    added = ajanda.mail_intake()
    if added:
        names = [("%s: %s" % (b["kisi"], b["baslik"])) if "kisi" in b else b.get("title", "") for b in added]
        bildirim.gonder("✅ Ajandaya eklendi: " + " · ".join(names)[:180])


def hatirlatma_tick():
    due = ajanda.due_reminders()
    if not due:
        return
    text = " · ".join(t for *_, t in due)
    if bildirim.gonder(text[:190] + (" — ajandadan ertele/tamamla" if len(text) < 150 else "")):
        ajanda.mark_notified(due)
