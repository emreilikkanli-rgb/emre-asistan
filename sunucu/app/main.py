"""Emre'nin Asistanı: mail raporları web uygulaması (Railway)."""
import hashlib
import hmac
import html as _html
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import ajanda as ajanda_mod, auth, db, etkinlik, ews_gonder, jobs, moduller
from .analyze import tekillestir

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ea.main")
TZ = ZoneInfo("Europe/Istanbul")
SECURE = os.environ.get("COOKIE_INSECURE") != "1"  # yerel test dışında çerez yalnızca https

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def _local(iso, fmt="%d.%m.%Y %H:%M"):
    try:
        return datetime.fromisoformat(iso).astimezone(TZ).strftime(fmt)
    except (TypeError, ValueError):
        return iso or ""


templates.env.filters["yerel"] = _local
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _uzun_tarih(iso):
    d = datetime.fromisoformat(iso).astimezone(TZ)
    return "%d %s %d, %s · %s" % (d.day, AYLAR[d.month - 1], d.year, GUNLER[d.weekday()], d.strftime("%H:%M"))


templates.env.filters["uzun_tarih"] = _uzun_tarih
templates.env.globals["totp_enabled"] = auth.totp_enabled


@app.on_event("startup")
def _startup():
    db.init()
    if os.environ.get("SCHEDULER_OFF") != "1":
        jobs.start()


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store"
    if SECURE:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


def _page(request, name, sid, **ctx):
    ctx.update(csrf=auth.csrf_token(sid) if sid else "", aylik=db.month_cost(),
               ayarlar=db.get_settings())
    return templates.TemplateResponse(request, name, ctx)


def _guard(request):
    sid = auth.current_session(request)
    return sid, (None if sid else RedirectResponse("/giris", status_code=303))


@app.get("/saglik", response_class=PlainTextResponse)
def saglik():
    return "ok"


# Uygulama simgesi (telefon ana ekranı, tarayıcı sekmesi). Yalnızca logo görseli; veri içermez.
_STATIC = os.path.join(os.path.dirname(__file__), "static")


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
def ikon_telefon():
    return FileResponse(os.path.join(_STATIC, "apple-touch-icon.png"), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.png")
@app.get("/favicon.ico")
def ikon_sekme():
    return FileResponse(os.path.join(_STATIC, "favicon.png"), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /\n"


def _giris_sayfa(request, sablon, status_code=200, **ctx):
    ctx.setdefault("kullanici_var", bool(auth.kullanici()))
    return templates.TemplateResponse(request, sablon, ctx, status_code=status_code)


@app.get("/giris", response_class=HTMLResponse)
def giris_form(request: Request):
    if not auth.configured():
        return _giris_sayfa(request, "giris.html", hata="Sunucu henüz kurulmadı: SESSION_SECRET ve şifre tanımlanmamış.", kapali=True)
    return _giris_sayfa(request, "giris.html", hata=auth.lockout_message(auth.client_ip(request)),
                        bilgi="Yeni şifreniz kaydedildi." if request.query_params.get("yenilendi") else "")


@app.post("/giris")
def giris(request: Request, kullanici: str = Form(""), sifre: str = Form(""), kod: str = Form(""), hatirla: str = Form("")):
    if not auth.configured():
        return RedirectResponse("/giris", status_code=303)
    ip = auth.client_ip(request)
    lock = auth.lockout_message(ip)
    if lock:
        return _giris_sayfa(request, "giris.html", 429, hata=lock, kullanici=kullanici)
    sid = auth.check_login(kullanici, sifre, kod, ip, hatirla=bool(hatirla))
    if not sid:
        return _giris_sayfa(request, "giris.html", 401, kullanici=kullanici,
                            hata="Kullanıcı adı ya da şifre hatalı." if auth.kullanici() else "Şifre hatalı.")
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.cookie_value(sid), max_age=auth.HATIRLA_MAX if hatirla else None,
                    httponly=True, secure=SECURE, samesite="lax" if hatirla else "strict")
    return resp


@app.get("/sifremi-unuttum", response_class=HTMLResponse)
def sifremi_unuttum_form(request: Request):
    return _giris_sayfa(request, "sifre_unuttum.html", olustur=not auth.kullanici())


@app.get("/hesap-olustur")
def hesap_olustur_form(request: Request):
    return RedirectResponse("/sifremi-unuttum", status_code=303)


@app.post("/sifremi-unuttum", response_class=HTMLResponse)
def sifremi_unuttum(request: Request, mail: str = Form(""), kullanici: str = Form("")):
    ip = auth.client_ip(request)
    olustur = not auth.kullanici()  # henüz hesap yoksa: kullanıcı adı da burada seçilir
    sayfa = lambda kod, **k: _giris_sayfa(request, "sifre_unuttum.html", kod, olustur=olustur, kullanici=kullanici, mail=mail, **k)
    lock = auth.lockout_message(ip)
    if lock:
        return sayfa(429, hata=lock)
    t, neden = auth.sifirlama_iste(mail, ip, kullanici if olustur else "")
    if neden == "kullanici":
        return sayfa(400, hata="Kullanıcı adı 3–32 karakter olmalı; harf, rakam, nokta, tire ya da alt çizgi kullanın (Türkçe karakter ve boşluk olmadan).")
    if neden == "sik":
        return sayfa(429, hata="Az önce bir link gönderildi. Gelen kutunuzu kontrol edin; 5 dakika sonra yeniden isteyebilirsiniz.")
    if neden == "gunluk":
        return sayfa(429, hata="Bugün için link sınırına ulaşıldı. Yarın yeniden deneyin.")
    if t:
        link = "%s/sifre-yenile?t=%s" % (os.environ.get("APP_URL", "https://ea-sunucu-production.up.railway.app").rstrip("/"), t)
        html = ('<div style="font:15px Calibri,Arial,sans-serif;color:#17202e;max-width:520px">'
                "<p>Merhaba Emre Bey,</p><p>Emre'nin Asistanı kullanıcı adınızı doğrulamak ve şifrenizi oluşturmak için aşağıdaki düğmeye basın. "
                "Link <b>30 dakika</b> geçerlidir ve yalnızca bir kez kullanılabilir.</p>"
                '<p><a href="%s" style="display:inline-block;padding:12px 22px;border-radius:10px;background:#5b4fe9;color:#fff;text-decoration:none;font-weight:600">'
                "Yeni şifre oluştur</a></p><p style=\"color:#6b6a66;font-size:13px\">Bu isteği siz yapmadıysanız bu maili dikkate almayın; şifreniz değişmez.</p></div>") % _html.escape(link)
        try:
            ews = Ews(os.environ.get("EWS_HOST", ""), os.environ.get("EWS_USER", ""), os.environ.get("EWS_PASSWORD", ""))
            ews_gonder.send(ews, auth.KURTARMA_MAIL, "Emre'nin Asistanı · doğrulama linki", html)
            log.info("Şifre yenileme linki gönderildi")
        except (EwsError, ValueError) as ex:
            log.warning("Şifre yenileme maili gönderilemedi: %s", ex)
            db.kimlik_del("sifirlama")
            return sayfa(502, hata="Mail gönderilemedi. Biraz sonra yeniden deneyin.")
    # Adres yanlış olsa da aynı cevap: hangi adresin kayıtlı olduğu dışarıya söylenmez
    return sayfa(200, gonderildi=True)


@app.get("/sifre-yenile", response_class=HTMLResponse)
def sifre_yenile_form(request: Request, t: str = ""):
    if not auth.sifirlama_gecerli(t):
        return _giris_sayfa(request, "sifre_yenile.html", 400, gecersiz=True)
    return _giris_sayfa(request, "sifre_yenile.html", t=t, kullanici=auth.bekleyen_kullanici() or auth.kullanici(),
                        dogrulandi=bool(auth.bekleyen_kullanici() or auth.kullanici()))


@app.post("/sifre-yenile", response_class=HTMLResponse)
def sifre_yenile(request: Request, t: str = Form(""), kullanici: str = Form(""), sifre: str = Form(""), sifre2: str = Form("")):
    if sifre != sifre2:
        return _giris_sayfa(request, "sifre_yenile.html", 400, t=t, kullanici=kullanici, hata="İki şifre aynı değil.")
    sid, hata = auth.sifirlama_tamamla(t, kullanici, sifre, auth.client_ip(request))
    if not sid:
        return _giris_sayfa(request, "sifre_yenile.html", 400, t=t, kullanici=kullanici, hata=hata,
                            gecersiz=not auth.sifirlama_gecerli(t))
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.cookie_value(sid), max_age=auth.HATIRLA_MAX, httponly=True, secure=SECURE, samesite="lax")
    return resp


@app.post("/cikis")
def cikis(request: Request, csrf: str = Form("")):
    sid = auth.current_session(request)
    if sid and auth.csrf_ok(sid, csrf):
        db.session_delete(sid)
    resp = RedirectResponse("/giris", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
def ana(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    simdi = datetime.now(TZ)
    gun = ajanda_mod.today_summary()
    p = _pano(db.get_report())
    rozet = {
        "ajanda": len([i for i in gun["bugun"] if not i.get("done")]) + len(gun["geciken"]),
        "mailler": len(p.get("sikayet", [])) + len(p.get("odeme", [])) + len([c for c in p.get("takip", []) if c.get("_aksiyon")]),
        "is-planlama": len(gun["g_bugun"]) + len(gun["g_gec"]),
        "kibris-etkinlik": len([e for e in (db.etkinlik_son() or {}).get("data", {}).get("etkinlikler", [])
                                if simdi.date().isoformat() <= e["tarih"] <= (simdi.date() + timedelta(days=7)).isoformat()]),
    }
    parcalar = []
    if rozet["ajanda"]:
        parcalar.append("ajandada %d iş" % rozet["ajanda"])
    if rozet["is-planlama"]:
        parcalar.append("%d görev bitişi" % rozet["is-planlama"])
    if rozet["mailler"]:
        parcalar.append("%d önemli mail" % rozet["mailler"])
    h = simdi.hour
    selam = "İyi geceler" if h < 5 else "Günaydın" if h < 12 else "İyi günler" if h < 18 else "İyi akşamlar" if h < 22 else "İyi geceler"
    return _page(request, "ana.html", sid, moduller=moduller.MODULLER, gruplar=moduller.GRUPLAR, rozet=rozet,
                 ozet=("Bugün: " + ", ".join(parcalar)) if parcalar else "",
                 selam=selam, saat=simdi.strftime("%H:%M"), gun_no=simdi.day, gun_ad=["PZT", "SAL", "ÇAR", "PER", "CUM", "CMT", "PAZ"][simdi.weekday()],
                 simdi="%d %s %d, %s" % (simdi.day, AYLAR[simdi.month - 1], simdi.year, GUNLER[simdi.weekday()]))


@app.get("/m/{slug}", response_class=HTMLResponse)
def modul(request: Request, slug: str):
    sid, redir = _guard(request)
    if redir:
        return redir
    m = moduller.BY_SLUG.get(slug)
    if not m:
        return RedirectResponse("/", status_code=303)
    if m["hazir"]:
        return RedirectResponse(m["href"], status_code=303)
    return _page(request, "modul.html", sid, m=m)


def _mail_kimligi(r, ref):
    """Rapordaki mail numarasından Exchange kimliğini bulur."""
    data = (r or {}).get("data") or {}
    item_id = (data.get("_ids") or {}).get(str(ref))
    if not item_id:  # eski raporlar: kimliği Outlook bağlantısından çıkar
        link = (data.get("_links") or {}).get(str(ref), "")
        item_id = (parse_qs(urlparse(link).query).get("ItemID") or [None])[0]
    return item_id


def _anahtar(item_id):
    return hashlib.sha1(item_id.encode()).hexdigest()[:24] if item_id else ""


def _pano(r):
    """Tekrarsız pano + Emre Bey'in kararları: okundu/gereksiz olanlar listeden kalkar, takiptekiler ayrı başlıkta."""
    if not (r and r.get("status") == "ok" and isinstance(r.get("data"), dict)):
        return {}
    p = tekillestir(r["data"])
    kararlar = db.karar_hepsi()
    for bolum in ("sikayet", "odeme", "vip", "ortak", "takip"):
        kalan = []
        for c in p.get(bolum, []):
            ref = (c.get("refs") or [None])[0]
            a = _anahtar(_mail_kimligi(r, ref)) if ref is not None else ""
            c["_ref"], c["_rid"] = ref, r["id"]
            if a and a in kararlar:
                continue  # okundu, gereksiz ya da Takiptekiler'de
            kalan.append(c)
        p[bolum] = kalan
    p["takipte"] = [dict(k["kart"], _ref=k["ref"], _rid=k["rid"], _takip_at=k["at"]) for k in db.karar_liste("takip", limit=200, gun=3650)]
    return p


# ---------- Kıbrıs Etkinlikleri ----------
@app.get("/etkinlikler", response_class=HTMLResponse)
def etkinlikler(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    durum = etkinlik.baslat(elle=False)  # son tarama 24 saatten eskiyse arka planda yenile
    son, enson = db.etkinlik_son(), db.etkinlik_son(sadece_ok=False)
    g = etkinlik.gruplar((son or {}).get("data", {}).get("etkinlikler", []))
    return _page(request, "etkinlikler.html", sid, son=son, g=g, araniyor=durum in ("basladi", "calisiyor"),
                 hata=(enson or {}).get("error") if enson and enson["status"] != "ok" else "")


@app.get("/api/etkinlik-durum")
def etkinlik_durum(request: Request):
    _, err = _api_guard(request)
    if err:
        return err
    son, enson = db.etkinlik_son(), db.etkinlik_son(sadece_ok=False)
    return {"calisiyor": etkinlik.calisiyor(), "id": (son or {}).get("id", 0),
            "hata": (enson or {}).get("error") or "" if enson and enson["status"] != "ok" else "", "son_id": (enson or {}).get("id", 0)}


@app.post("/api/etkinlik-ara")
def etkinlik_ara(request: Request):
    _, err = _api_guard(request, write=True)
    if err:
        return err
    return {"durum": etkinlik.baslat(elle=True)}


@app.post("/api/mail-karar")
async def mail_karar(request: Request):
    """Okudum / Takibe devam / Gerek yok / Geri al. Yalnızca oturum + CSRF ile."""
    _, err = _api_guard(request, write=True)
    if err:
        return err
    try:
        body = await request.json()
        rid, ref, durum = int(body.get("rid")), str(body.get("ref")), str(body.get("durum"))
    except (ValueError, TypeError):
        return PlainTextResponse("Geçersiz istek", status_code=400)
    if durum not in ("okundu", "takip", "gereksiz", "geri"):
        return PlainTextResponse("Geçersiz karar", status_code=400)
    r = db.get_report(rid)
    a = _anahtar(_mail_kimligi(r, ref))
    if not a:
        return PlainTextResponse("Mail bulunamadı", status_code=404)
    if durum == "geri":
        db.karar_sil(a)
        return {"ok": True}
    kart = next((c for sec in ("sikayetler", "odeme", "oncelikli", "ortak", "aksiyon", "takip")
                 for c in (r["data"].get(sec) or []) if [str(x) for x in (c.get("refs") or [])][:1] == [ref]), None)
    if kart is None:
        kart = next((dict(k["kart"]) for k in db.karar_hepsi().values() if str(k["ref"]) == ref and k["rid"] == rid), {"baslik": "Mail"})
    ozet = {k: kart.get(k) for k in ("baslik", "kim", "zaman", "ozet", "satir_etiketi", "satir", "etiketler", "kisiler", "refs")}
    db.karar_set(a, durum, rid, ref, ozet)
    return {"ok": True}


@app.get("/mailler", response_class=HTMLResponse)
def mailler(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    r = db.get_report()
    durum = jobs.guncelle_baslat() if not r else ("calisiyor" if jobs.calisiyor() else "guncel")
    return _page(request, "rapor.html", sid, r=r, p=_pano(r), son=db.list_reports(1), gun=ajanda_mod.today_summary(),
                 guncelleniyor=durum in ("basladi", "calisiyor"))


@app.get("/api/rapor-durum")
def rapor_durum(request: Request):
    _, err = _api_guard(request)
    if err:
        return err
    son = db.list_reports(1)
    ok = db.get_report()
    return {"calisiyor": jobs.calisiyor(), "rid": ok["id"] if ok else 0,
            "hata": son[0]["error"] if son and son[0]["status"] != "ok" else ""}


@app.post("/api/rapor-guncelle")
def rapor_guncelle(request: Request):
    _, err = _api_guard(request, write=True)
    if err:
        return err
    return {"durum": jobs.guncelle_baslat()}


@app.get("/rapor/{rid}", response_class=HTMLResponse)
def rapor(request: Request, rid: int):
    sid, redir = _guard(request)
    if redir:
        return redir
    r = db.get_report(rid)
    return _page(request, "rapor.html", sid, r=r, p=_pano(r), son=[])


@app.get("/raporlar", response_class=HTMLResponse)
def raporlar(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    return _page(request, "raporlar.html", sid, liste=db.list_reports())


@app.post("/calistir")
def calistir(request: Request, csrf: str = Form(""), tur: str = Form("ara")):
    sid, redir = _guard(request)
    if redir:
        return redir
    if not auth.csrf_ok(sid, csrf):
        return PlainTextResponse("Geçersiz istek.", status_code=400)
    threading.Thread(target=jobs.run, args=("sabah" if tur == "sabah" else "ara",), daemon=True).start()
    return RedirectResponse("/raporlar?basladi=1", status_code=303)


@app.get("/ayarlar", response_class=HTMLResponse)
def ayarlar(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    return _page(request, "ayarlar.html", sid, kaydedildi=request.query_params.get("ok") == "1")


@app.post("/ayarlar")
async def ayarlar_kaydet(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    form = await request.form()
    if not auth.csrf_ok(sid, form.get("csrf", "")):
        return PlainTextResponse("Geçersiz istek.", status_code=400)
    values = {k: str(form.get(k, "")).strip()[:20000] for k in db.DEFAULT_SETTINGS if k in form}
    db.save_settings(values)
    jobs.start()  # takvim değiştiyse yeniden kur
    return RedirectResponse("/ayarlar?ok=1", status_code=303)


# ---------- Ajanda ----------
import json as _json
import re as _re

from fastapi.responses import Response

_APP_DIR = os.path.dirname(__file__)
_ID_RE = _re.compile(r"^[A-Za-z0-9_\-.~:@+]{1,200}$")
_MAX_DOC = 256 * 1024


def _ajanda_html():
    with open(os.path.join(_APP_DIR, "ajanda.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/ajanda", response_class=HTMLResponse)
def ajanda(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    jobs.ajanda_guncelle()  # "EA:" maillerini hemen işle; yeni kayıtlar sayfaya 5 sn içinde düşer
    head = ('<!doctype html><html lang="tr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="robots" content="noindex, nofollow"><meta name="theme-color" content="#0b0a1a"><meta name="csrf" content="%s">'
            '<link rel="apple-touch-icon" href="/apple-touch-icon.png"><link rel="icon" type="image/png" href="/favicon.png"><meta name="apple-mobile-web-app-title" content="EA">'
            '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
            'body{margin:0;background:#0b0a1a}[hidden]{display:none!important}'
            '.ea-menu{position:relative;z-index:2;display:flex;gap:10px;align-items:center;justify-content:space-between;max-width:1240px;margin:0 auto;'
            'padding:14px 16px 0;font:600 15px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}'
            '.ea-marka{display:flex;align-items:center;gap:10px;color:#e8e5ff;text-decoration:none;white-space:nowrap}'
            '.ea-marka i{font-style:normal;width:34px;height:34px;border-radius:11px;display:grid;place-items:center;font-size:12px;font-weight:800;color:#fff;'
            'background:conic-gradient(from 210deg,#7c6cff,#c06cff,#ff8f6c,#7c6cff);box-shadow:0 6px 20px rgba(124,108,255,.4)}'
            '.ea-menu span{display:flex;gap:6px}'
            '.ea-menu span a{width:38px;height:38px;border-radius:50%%;display:grid;place-items:center;color:#cfcaf0;background:rgba(255,255,255,.06);'
            'border:1px solid rgba(255,255,255,.12);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px)}'
            '.ea-menu span a:hover{background:rgba(255,255,255,.12);color:#fff}'
            '.ea-menu span a.on{color:#fff;background:linear-gradient(135deg,#7c6cff,#c06cff);border-color:transparent}'
            '.ea-menu svg{width:18px;height:18px}'
            '@media (max-width:420px){.ea-marka{font-size:0;gap:0}}'
            '</style>'
            '<script src="/ajanda/kopru.js"></script></head><body>') % auth.csrf_token(sid)
    ikon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">%s</svg>'
    menu = ('<nav class="ea-menu"><a class="ea-marka" href="/"><i>EA</i>Emre\'nin Asistanı</a><span>'
            '<a href="/" title="Ana ekran" aria-label="Ana ekran">' + ikon % '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/>' + '</a>'
            '<a class="on" href="/ajanda" title="Emre\'nin Ajandası" aria-label="Emre\'nin Ajandası">' + ikon % '<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/>' + '</a>'
            '<a href="/mailler" title="Emre\'nin Mailleri" aria-label="Emre\'nin Mailleri">' + ikon % '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7 8 6 8-6"/>' + '</a>'
            '<a href="/ayarlar" title="Ayarlar" aria-label="Ayarlar">' + ikon % '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1"/>' + '</a>'
            '</span></nav>')
    return HTMLResponse(head + menu + _ajanda_html() + '</body></html>')


@app.get("/ajanda/kopru.js")
def ajanda_kopru(request: Request):
    sid, redir = _guard(request)
    if redir:
        return PlainTextResponse("", status_code=401)
    with open(os.path.join(_APP_DIR, "ajanda_kopru.js"), encoding="utf-8") as f:
        return Response(f.read(), media_type="application/javascript")


def _api_guard(request, write=False):
    sid = auth.current_session(request)
    if not sid:
        return None, PlainTextResponse("Oturum yok", status_code=401)
    if write and not auth.csrf_ok(sid, request.headers.get("x-csrf", "")):
        return None, PlainTextResponse("Geçersiz istek", status_code=400)
    return sid, None


def _check(col, doc_id=None):
    return col in db.DOC_COLLECTIONS and (doc_id is None or _ID_RE.match(doc_id))


@app.get("/api/db/{col}")
def api_list(request: Request, col: str):
    _, err = _api_guard(request)
    if err:
        return err
    if not _check(col):
        return PlainTextResponse("Bilinmeyen koleksiyon", status_code=404)
    return db.doc_list(col)


@app.get("/api/db/{col}/{doc_id}")
def api_get(request: Request, col: str, doc_id: str):
    _, err = _api_guard(request)
    if err:
        return err
    body = db.doc_get(col, doc_id) if _check(col, doc_id) else None
    return {"data": body} if body is not None else PlainTextResponse("Yok", status_code=404)


@app.put("/api/db/{col}/{doc_id}")
async def api_set(request: Request, col: str, doc_id: str):
    _, err = _api_guard(request, write=True)
    if err:
        return err
    if not _check(col, doc_id):
        return PlainTextResponse("Geçersiz yol", status_code=400)
    raw = await request.body()
    if len(raw) > _MAX_DOC:
        return PlainTextResponse("Kayıt çok büyük", status_code=413)
    try:
        body = _json.loads(raw)
    except ValueError:
        return PlainTextResponse("Geçersiz JSON", status_code=400)
    if not isinstance(body, dict):
        return PlainTextResponse("Kayıt bir nesne olmalı", status_code=400)
    db.doc_set(col, doc_id, body)
    return Response(status_code=204)


@app.delete("/api/db/{col}/{doc_id}")
def api_delete(request: Request, col: str, doc_id: str):
    _, err = _api_guard(request, write=True)
    if err:
        return err
    if _check(col, doc_id):
        db.doc_delete(col, doc_id)
    return Response(status_code=204)


@app.put("/api/claude/{col}/{doc_id}")
async def api_claude_set(request: Request, col: str, doc_id: str):
    """Claude'un "Ajandama ekle" kayıtları: oturum yerine EA_API_TOKEN ile, yalnızca yazma."""
    token = os.environ.get("EA_API_TOKEN", "")
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if len(token) < 32 or not hmac.compare_digest(token, given):
        return PlainTextResponse("Yetkisiz", status_code=401)
    if col not in ("items", "gorevler", "plans") or not _check(col, doc_id):
        return PlainTextResponse("Geçersiz yol", status_code=400)
    raw = await request.body()
    if len(raw) > _MAX_DOC:
        return PlainTextResponse("Kayıt çok büyük", status_code=413)
    try:
        body = _json.loads(raw)
    except ValueError:
        return PlainTextResponse("Geçersiz JSON", status_code=400)
    if not isinstance(body, dict):
        return PlainTextResponse("Kayıt bir nesne olmalı", status_code=400)
    db.doc_set(col, doc_id, body)
    return Response(status_code=204)


def _tr_tarih(s):
    return "%s.%s.%s" % (s[8:10], s[5:7], s[:4]) if s and len(s) >= 10 else "—"


def _gorev_mail_html(g, imza):
    e = lambda s: _html.escape(str(s or "")).replace("\n", "<br>")
    rows = [("İş", g.get("baslik")), ("Detay", g.get("detay")), ("Birim", g.get("birim")),
            ("Veriliş tarihi", _tr_tarih(g.get("verilisTarihi", ""))),
            ("Bitiş tarihi", _tr_tarih(g.get("bitisTarihi", "")) + ((" " + g["saat"]) if g.get("saat") else ""))]
    if g.get("oncelik") == "yuksek":
        rows.append(("Öncelik", "Yüksek"))
    ek = [x for x in (g.get("ekGorevler") or []) if not x.get("done")]
    tablo = "".join('<tr><td style="padding:4px 12px 4px 0;color:#5b6678;vertical-align:top">%s</td><td style="padding:4px 0">%s</td></tr>'
                    % (e(k), e(v)) for k, v in rows if v)
    ek_html = ("<p><b>Ek görevler</b></p><ul>%s</ul>" % "".join(
        "<li>%s. görev: %s%s</li>" % (e(x.get("no")), e(x.get("metin")), (" · bitiş " + _tr_tarih(x["bitis"])) if x.get("bitis") else "")
        for x in ek)) if ek else ""
    return ('<div style="font:14px Calibri,Arial,sans-serif;color:#17202e">'
            "<p>Merhaba %s,</p><p>Aşağıdaki işin takibini size iletiyorum.</p>"
            '<table style="border-collapse:collapse;font:inherit">%s</table>%s'
            "<p>Bitiş tarihine kadar sonucu bana bildirmenizi rica ederim.</p><p>Saygılarımla,<br>%s</p></div>"
            % (e(g.get("kisi")), tablo, ek_html, e(imza)))


@app.post("/api/gorev-mail/{doc_id}")
async def gorev_mail(request: Request, doc_id: str):
    """Görevi görevliye mail ile iletir. Yalnızca oturum + CSRF ile, sayfadaki "Gönder" düğmesinden."""
    _, err = _api_guard(request, write=True)
    if err:
        return err
    if not _check("gorevler", doc_id):
        return PlainTextResponse("Geçersiz görev", status_code=400)
    g = db.doc_get("gorevler", doc_id)
    if not g:
        return PlainTextResponse("Görev bulunamadı", status_code=404)
    try:
        to = str((await request.json()).get("to", "")).strip()
    except ValueError:
        return PlainTextResponse("Geçersiz istek", status_code=400)
    if not ews_gonder.MAIL_RE.match(to):
        return PlainTextResponse("Geçersiz mail adresi", status_code=400)
    if ews_gonder.MAIL_TYPO.search(to):
        return PlainTextResponse("%s adresinde yazım hatası var gibi görünüyor (ör. .con yerine .com)." % to, status_code=400)
    gecmis = g.get("mailGonderimleri") or []
    simdi = datetime.now(timezone.utc)
    if gecmis and (simdi - datetime.fromisoformat(gecmis[-1]["at"].replace("Z", "+00:00"))).total_seconds() < 60:
        return PlainTextResponse("Bu görev az önce gönderildi; 1 dakika sonra tekrar deneyin.", status_code=429)
    imza = db.get_settings().get("name") or "Emre ILIKKANLI"
    konu = "Görev: %s · bitiş %s" % (g.get("baslik", ""), _tr_tarih(g.get("bitisTarihi", "")))
    try:
        ews = Ews(os.environ.get("EWS_HOST", ""), os.environ.get("EWS_USER", ""), os.environ.get("EWS_PASSWORD", ""))
        ews_gonder.send(ews, to, konu, _gorev_mail_html(g, imza))
    except (EwsError, ValueError) as ex:
        log.warning("Görev maili gönderilemedi: %s", ex)
        return PlainTextResponse("Mail gönderilemedi: %s" % ex, status_code=502)
    at = simdi.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    g["kisiMail"] = to
    g["mailGonderimleri"] = gecmis + [{"at": at, "to": to}]
    g["updatedAt"] = at
    db.doc_set("gorevler", doc_id, g)
    log.info("Görev maili gönderildi: %s", doc_id)
    return {"ok": True, "at": at, "to": to}


@app.post("/ayarlar/ice-aktar")
async def ice_aktar(request: Request):
    """claude.ai ajandasından alınan JSON yedeğini içe aktarır: {"items": [{"id", "data"}], ...}."""
    sid, redir = _guard(request)
    if redir:
        return redir
    form = await request.form()
    if not auth.csrf_ok(sid, form.get("csrf", "")):
        return PlainTextResponse("Geçersiz istek.", status_code=400)
    up = form.get("dosya")
    try:
        data = _json.loads((await up.read()).decode("utf-8")) if up else {}
    except (ValueError, AttributeError):
        return RedirectResponse("/ayarlar?aktar=hata", status_code=303)
    n = 0
    for col in ("items", "gorevler", "plans"):
        for row in data.get(col) or []:
            if isinstance(row, dict) and _check(col, str(row.get("id", ""))) and isinstance(row.get("data"), dict):
                db.doc_set(col, row["id"], row["data"])
                n += 1
    return RedirectResponse("/ayarlar?aktar=%d" % n, status_code=303)


# ---------- Maili asistanın içinde okuma ----------
from urllib.parse import parse_qs, urlparse

from .ews import Ews, EwsError, get_message


@app.get("/mail/{rid}/{ref}", response_class=HTMLResponse)
def mail_oku(request: Request, rid: int, ref: str):
    sid, redir = _guard(request)
    if redir:
        return redir
    r = db.get_report(rid)
    item_id = _mail_kimligi(r, ref) if r else None
    karar = db.karar_hepsi().get(_anahtar(item_id)) if item_id else None
    m, hata = None, None
    if not item_id:
        hata = "Bu mail bulunamadı."
    else:
        try:
            ews = Ews(os.environ.get("EWS_HOST", ""), os.environ.get("EWS_USER", ""), os.environ.get("EWS_PASSWORD", ""))
            m = get_message(ews, item_id)
            if not m:
                hata = "Mail artık gelen kutusunda değil (taşınmış ya da silinmiş olabilir)."
            else:
                m["owa"] = ews.owa_link(item_id)
        except EwsError as e:
            hata = str(e)
    return _page(request, "mail.html", sid, m=m, hata=hata, rid=rid, ref=ref, karar=(karar or {}).get("durum", ""))
