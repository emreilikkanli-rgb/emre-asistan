"""Gişe Kıbrıs (gisekibris.com) etkinliklerini doğrudan sitenin sayfa verisinden okur; yapay zekâ kullanılmaz.

Kaynaklar (yalnızca herkese açık sayfalar, günde bir kez, istekler arasında kısa bekleme):
- Ana sayfa: öne çıkan bölümlerdeki etkinlikler (ad, oturum tarihleri/saatleri, süre, şehir, kategori)
- Mekân sayfaları (/mekanlar/<id>): mekân adı, adresi ve o mekânın diğer etkinlikleri
- Etkinlik sayfaları (/etkinlikler/<id>): bilet fiyatları
Mekân sayfalarında başka kullanıcılara ait bilgiler de bulunur; buradan YALNIZCA mekân adı, adres ve şehir alınır.
"""
import html
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("ea.gise")
SITE = "https://www.gisekibris.com"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; EmreninAsistani/1.0; kisisel etkinlik takvimi)"}
BEKLE = 0.4  # istekler arası saniye
TZ = ZoneInfo("Europe/Istanbul")
SEHIR = {"kyrenia": "Girne", "nicosia": "Lefkoşa", "famagusta": "Gazimağusa", "iskele": "İskele", "trikomo": "İskele",
         "morphou": "Güzelyurt", "guzelyurt": "Güzelyurt", "lefke": "Lefke", "karpaz": "Karpaz"}
BOLUM_TUR = {"hotel konseri": "konser", "konser": "konser", "canlı müzik": "konser", "sahne": "tiyatro",
             "club & lounge & bar": "parti", "elektronik müzik": "parti", "cadılar bayramı etkinlikleri": "parti",
             "interaktif etkinlik": "diger", "i̇nteraktif etkinlik": "diger"}
KATEGORI_TUR = {"concert": "konser", "music": "konser", "hotelconcert": "konser", "electronicmusic": "parti",
                "party": "parti", "art": "tiyatro", "tiyatro": "tiyatro", "kids": "cocuk", "sport": "spor", "festival": "festival"}


def _sayfa(yol):
    """Sayfanın __NEXT_DATA__ pageProps verisi; hata olursa {}."""
    try:
        r = requests.get(SITE + yol, headers=_UA, timeout=25)
        if r.status_code != 200:
            return {}
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', r.text, re.S)
        return (json.loads(m.group(1)).get("props") or {}).get("pageProps") or {} if m else {}
    except (requests.RequestException, ValueError):
        return {}
    finally:
        time.sleep(BEKLE)


def _duz(h, n=220):
    """HTML açıklamayı kısa düz metne çevirir."""
    t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h or "")).split())
    if len(t) <= n:
        return t
    kes = t[:n]
    nokta = max(kes.rfind(". "), kes.rfind("! "), kes.rfind("? "))
    return (kes[:nokta + 1] if nokta > 60 else kes.rsplit(" ", 1)[0] + "…")


def _fiyat(ev):
    fiyatlar = []
    t = ev.get("tickets") or {}
    gruplar = t.values() if isinstance(t, dict) else [t]  # bilet verisi sözlük (tür → liste) ya da düz liste olabilir
    for liste in gruplar:
        for b in liste if isinstance(liste, list) else []:
            if not isinstance(b, dict):
                continue
            try:
                p = float(b.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if p > 0:
                fiyatlar.append(p)
    rozet = (((ev.get("badge") or {}).get("label") or {}).get("tr") or "").upper()
    if fiyatlar:
        en, ust = min(fiyatlar), max(fiyatlar)
        f = lambda x: "{:,.0f}".format(x).replace(",", ".")
        return "ucretli", ("%s TL" % f(en)) if en == ust else ("%s – %s TL" % (f(en), f(ust)))
    if "ÜCRETSİZ" in rozet or "UCRETSIZ" in rozet:
        return "ucretsiz", "Giriş ücretsiz"
    if ev.get("tickets") and not fiyatlar:
        return "ucretsiz", ""
    return "bilinmiyor", ""


def _bitis(saat, sure):
    try:
        h, m = map(int, saat.split(":"))
        dk = h * 60 + m + int(sure or 0)
        return "%02d:%02d" % ((dk // 60) % 24, dk % 60) if sure else ""
    except (ValueError, AttributeError):
        return ""


def _kayitlar(ev, mekanlar, tur, bugun, son):
    """Bir Gişe Kıbrıs etkinliğinden (her oturum günü için) bizim biçimde kayıtlar."""
    if not ev.get("isActive", True) or ev.get("isCancelled"):
        return []
    mekan = mekanlar.get(ev.get("venue")) or {}
    ad = " ".join((ev.get("name") or "").split())
    sanatci = re.split(r"\s+[xX]\s+", ad)[0] if re.search(r"\s+[xX]\s+", ad) else ""
    ucret, detay = _fiyat(ev)
    ortak = {
        "ad": ad, "sanatci": sanatci, "tur": tur, "mekan": mekan.get("ad", ""), "adres": mekan.get("adres", ""),
        "sehir": SEHIR.get((ev.get("city") or mekan.get("sehir") or "").lower(), (ev.get("city") or "").title()),
        "ucret": ucret, "ucret_detay": detay, "aciklama": _duz((ev.get("description") or {}).get("tr")),
        "kaynak_url": "%s/etkinlikler/%s" % (SITE, ev.get("id")), "kaynak_adi": "Gişe Kıbrıs", "kaynak": "gise",
    }
    # Tek seferlik etkinlikte başlangıç/bitiş zaman damgası esastır (oturum saati bazen hatalı kaydedilmiş)
    if ev.get("dateType") == "oneoff" and isinstance(ev.get("startdate"), (int, float)):
        bas = datetime.fromtimestamp(ev["startdate"] / 1000, timezone.utc).astimezone(TZ)
        bit = datetime.fromtimestamp(ev["enddate"] / 1000, timezone.utc).astimezone(TZ) if isinstance(ev.get("enddate"), (int, float)) else None
        gun = bas.date().isoformat()
        if not (bugun <= ((bit.date().isoformat() if bit else gun)) and gun <= son):
            return []
        return [dict(ortak, tarih=gun, bitis_tarihi=bit.date().isoformat() if bit and (bit - bas) > timedelta(hours=24) else "",
                     baslangic_saati=bas.strftime("%H:%M"), bitis_saati=bit.strftime("%H:%M") if bit else "")]
    out = []
    for s in ev.get("sessions") or []:
        gun = (s.get("startdate") or "")[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", gun) or not (bugun <= gun <= son):
            continue
        saatler = [t.get("time") for t in (s.get("times") or []) if t.get("isActive", True) and re.match(r"^\d{2}:\d{2}$", t.get("time") or "")]
        bas = saatler[0] if saatler and saatler[0] != "00:00" else ""
        out.append(dict(ortak, tarih=gun, bitis_tarihi="", baslangic_saati=bas,
                        bitis_saati=_bitis(bas, ev.get("duration")) if bas else ""))
    return out


def topla(bugun, gun=90):
    """Gişe Kıbrıs'taki önümüzdeki `gun` günlük etkinlikler. Dönüş: (liste, istek sayısı)."""
    b, son = bugun.isoformat(), (bugun + timedelta(days=gun)).isoformat()
    istek = 1
    ana = _sayfa("/")
    if not ana:
        raise RuntimeError("Gişe Kıbrıs ana sayfası okunamadı.")
    olaylar, turler = {}, {}
    for bolum in (ana.get("homeSections") or {}).values():
        btur = BOLUM_TUR.get(((bolum.get("title") or {}).get("tr") or "").strip().lower())
        for ev in bolum.get("formattedEvents") or []:
            if ev.get("id"):
                olaylar.setdefault(ev["id"], ev)
                turler.setdefault(ev["id"], btur)
    # Mekân sayfaları: ad/adres + o mekândaki diğer etkinlikler
    mekanlar = {}
    for vid in sorted({e.get("venue") for e in olaylar.values() if e.get("venue")}):
        pp = _sayfa("/mekanlar/" + vid)
        istek += 1
        v = pp.get("venue") or {}
        mekanlar[vid] = {"ad": " ".join((v.get("name") or "").split()), "adres": " ".join((v.get("address") or "").split()),
                         "sehir": v.get("city") or ""}
        for ev in pp.get("venueEvents") or []:
            if ev.get("id") and ev["id"] not in olaylar:
                olaylar[ev["id"]] = ev
    # Fiyat: yaklaşan ve bileti bilinmeyen etkinliklerin kendi sayfası
    for eid, ev in list(olaylar.items()):
        gunler = [(s.get("startdate") or "")[:10] for s in ev.get("sessions") or []]
        if ev.get("tickets") or not any(b <= g <= son for g in gunler) or not ev.get("isActive", True) or ev.get("isCancelled"):
            continue
        detay = (_sayfa("/etkinlikler/" + eid).get("event") or {})
        istek += 1
        if detay.get("tickets"):
            ev["tickets"] = detay["tickets"]
        for k in ("badge", "description", "duration", "city", "venue"):
            ev.setdefault(k, detay.get(k))
    liste = []
    for eid, ev in olaylar.items():
        tur = turler.get(eid) or KATEGORI_TUR.get(ev.get("category") or "") or next(
            (KATEGORI_TUR[s] for s in ev.get("subcategories") or [] if s in KATEGORI_TUR), "diger")
        liste.extend(_kayitlar(ev, mekanlar, tur, b, son))
    liste.sort(key=lambda e: (e["tarih"], e["baslangic_saati"] or "99"))
    log.info("Gişe Kıbrıs: %d etkinlik kaydı, %d istek", len(liste), istek)
    return liste, istek
