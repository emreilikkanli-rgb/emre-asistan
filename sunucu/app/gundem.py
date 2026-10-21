"""Gündem modülleri: TR Haberleri, Dünyadan Haberler, Piyasalar, Hava Durumu.

Yapay zekâ kullanılmaz; veriler sitelerin herkese açık akışlarından gelir:
- Haberler: sitelerin kendi RSS akışları (başlık, kısa özet, bağlantı)
- Piyasalar: TCMB günlük kurları (resmî) + Yahoo Finance anlık fiyatlar
- Hava: Open-Meteo (anahtarsız, ücretsiz)
Sonuçlar veritabanında önbelleklenir; süresi dolunca arka planda yenilenir, sayfa beklemez.
"""
import html
import json
import logging
import re
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

from . import db

log = logging.getLogger("ea.gundem")
TZ = ZoneInfo("Europe/Istanbul")
_UA = {"User-Agent": "Mozilla/5.0 (compatible; EmreninAsistani/1.0; kisisel haber okuyucu)"}

HABER = {
    "tr-haberler": [
        ("turkiye", "Türkiye", [("Hürriyet", "https://www.hurriyet.com.tr/rss/gundem"), ("Sözcü", "https://www.sozcu.com.tr/feeds-rss-category-gundem"),
                                ("CNN Türk", "https://www.cnnturk.com/feed/rss/turkiye/news"), ("Anadolu Ajansı", "https://www.aa.com.tr/tr/rss/default?cat=guncel"),
                                ("TRT Haber", "https://www.trthaber.com/manset_articles.rss"), ("Habertürk", "https://www.haberturk.com/rss/manset.xml"),
                                ("Milliyet", "https://www.milliyet.com.tr/rss/rssnew/gundemrss.xml"), ("Sabah", "https://www.sabah.com.tr/rss/gundem.xml"),
                                ("BBC Türkçe", "https://feeds.bbci.co.uk/turkce/rss.xml")]),
        ("kktc", "KKTC", [("Yenidüzen", "https://www.yeniduzen.com/rss"), ("Havadis", "https://www.havadiskibris.com/rss"),
                          ("Kıbrıs Genç TV", "https://www.kibrisgenctv.com/rss"), ("BRT", "https://www.brtk.net/feed/"),
                          ("Gündem Kıbrıs", "https://www.gundemkibris.com/rss"), ("Kıbrıs Gazetesi", "https://www.kibrisgazetesi.com/rss"),
                          ("Diyalog", "https://www.diyaloggazetesi.com/rss")]),
        ("turizm", "Turizm", [("Turizm Güncel", "https://www.turizmguncel.com/rss.xml"), ("TurizmAjansı", "https://www.turizmajansi.com/rss"),
                              ("Turizm Gazetesi", "https://www.turizmgazetesi.com/rss.xml")]),
    ],
    "dunya-haberleri": [
        ("turkce", "Türkçe", [("DW Türkçe", "https://rss.dw.com/rdf/rss-tur-all"), ("Euronews Türkçe", "https://tr.euronews.com/rss")]),
        ("dunya", "Dünya", [("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"), ("The Guardian", "https://www.theguardian.com/world/rss"),
                            ("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"), ("CNN", "http://rss.cnn.com/rss/edition_world.rss"),
                            ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"), ("France 24", "https://www.france24.com/en/rss")]),
        ("turizm", "Turizm", [("Skift", "https://skift.com/feed/"), ("TravelDailyNews", "https://www.traveldailynews.com/feed/")]),
    ],
}
SURE_DK = {"tr-haberler": 20, "dunya-haberleri": 30, "piyasalar": 10, "hava": 30}
SEHIRLER = [("Girne", 35.336, 33.319), ("Lefkoşa", 35.185, 33.382), ("Gazimağusa", 35.125, 33.941), ("İskele", 35.287, 33.892),
            ("İstanbul", 41.013, 28.979)]
_kilitler = {k: threading.Lock() for k in SURE_DK}


# ---------- RSS ----------
def _metin(el, *adlar):
    for ad in adlar:
        x = el.find(ad)
        if x is not None and (x.text or "").strip():
            return x.text.strip()
    return ""


def _temiz(s, n=230):
    t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def _tarih(s):
    if not s:
        return ""
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(timezone.utc).isoformat()


def _rss(kaynak, url):
    """Bir akıştaki haberler: [{baslik, ozet, url, tarih, gorsel, kaynak}]."""
    try:
        r = requests.get(url, headers=_UA, timeout=10)
        if r.status_code != 200:
            return []
        govde = re.sub(rb"<\?xml-stylesheet[^>]*\?>", b"", r.content)
        kok = ET.fromstring(govde)
    except (requests.RequestException, ET.ParseError):
        return []
    # Ad alanlarını kaldır (Atom, media, dc, rdf): etiketleri sade adla ara
    for el in kok.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    out = []
    for it in list(kok.iter("item")) + list(kok.iter("entry")):
        baslik = _temiz(_metin(it, "title"), 220)
        link = _metin(it, "link") or ((it.find("link").get("href") or "") if it.find("link") is not None else "")
        if not baslik or not link.startswith("http"):
            continue
        aciklama = _metin(it, "description", "summary", "content", "encoded")
        gorsel = ""
        for ad in ("thumbnail", "content", "enclosure"):
            for x in it.iter(ad):
                u = x.get("url") or ""
                if u.startswith("http") and (ad != "enclosure" or (x.get("type") or "image").startswith("image")):
                    gorsel = u
                    break
            if gorsel:
                break
        if not gorsel:
            m = re.search(r'<img[^>]+src="(https?://[^"]+)"', aciklama or "")
            gorsel = m.group(1) if m else ""
        out.append({"baslik": baslik, "ozet": _temiz(aciklama), "url": link.strip(), "tarih": _tarih(_metin(it, "pubDate", "published", "updated", "date")),
                    "gorsel": gorsel, "kaynak": kaynak})
        if len(out) >= 25:
            break
    return out


def _haberler(modul):
    bolumler = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        isler = {(bid, ad): ex.submit(_rss, ad, url) for bid, _, kaynaklar in HABER[modul] for ad, url in kaynaklar}
    sinir = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    calisan = 0
    for bid, bad, kaynaklar in HABER[modul]:
        liste, gorulen = [], set()
        for ad, _ in kaynaklar:
            haberler = isler[(bid, ad)].result()
            calisan += 1 if haberler else 0
            for h in haberler:
                anahtar = re.sub(r"\W+", "", h["baslik"].lower())[:60]
                if anahtar in gorulen or (h["tarih"] and h["tarih"] < sinir):
                    continue
                gorulen.add(anahtar)
                liste.append(h)
        liste.sort(key=lambda h: h["tarih"] or "", reverse=True)
        bolumler.append({"id": bid, "ad": bad, "haberler": liste[:80], "kaynaklar": [k for k, _ in kaynaklar]})
    return {"bolumler": bolumler, "calisan_kaynak": calisan, "toplam_kaynak": sum(len(k) for _, _, k in HABER[modul])}


# ---------- Piyasalar ----------
def _yahoo(sembol):
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1d" % sembol, headers=_UA, timeout=10)
        m = r.json()["chart"]["result"][0]["meta"]
        fiyat = float(m["regularMarketPrice"])
        onceki = float(m.get("previousClose") or m.get("chartPreviousClose") or 0)  # bir önceki kapanış: günlük değişim
        return {"fiyat": fiyat, "degisim": round((fiyat - onceki) / onceki * 100, 2) if onceki else None,
                "saat": datetime.fromtimestamp(m.get("regularMarketTime") or 0, timezone.utc).isoformat() if m.get("regularMarketTime") else ""}
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None


def _tcmb():
    try:
        r = requests.get("https://www.tcmb.gov.tr/kurlar/today.xml", headers=_UA, timeout=10)
        kok = ET.fromstring(r.content)
        out = {"tarih": kok.get("Tarih", "")}
        for c in kok.findall("Currency"):
            if c.get("Kod") in ("USD", "EUR", "GBP"):
                out[c.get("Kod")] = {"alis": float(c.findtext("ForexBuying") or 0), "satis": float(c.findtext("ForexSelling") or 0)}
        return out
    except (requests.RequestException, ET.ParseError, ValueError):
        return None


def _piyasalar():
    semboller = {"USD": "USDTRY=X", "EUR": "EURTRY=X", "GBP": "GBPTRY=X", "ONS": "GC=F", "BRENT": "BZ=F", "BIST": "XU100.IS"}
    with ThreadPoolExecutor(max_workers=7) as ex:
        isler = {k: ex.submit(_yahoo, s) for k, s in semboller.items()}
        tcmb_is = ex.submit(_tcmb)
    canli = {k: f.result() for k, f in isler.items()}
    if canli.get("ONS") and canli.get("USD"):  # gram altın (TL) = ons (USD) × USD/TRY ÷ 31,1035
        gram = canli["ONS"]["fiyat"] * canli["USD"]["fiyat"] / 31.1035
        d1, d2 = canli["ONS"].get("degisim"), canli["USD"].get("degisim")
        canli["GRAM"] = {"fiyat": gram, "degisim": round(((1 + d1 / 100) * (1 + d2 / 100) - 1) * 100, 2) if d1 is not None and d2 is not None else None}
    return {"canli": canli, "tcmb": tcmb_is.result()}


# ---------- Hava ----------
HAVA_KOD = {0: ("Açık", "☀️"), 1: ("Az bulutlu", "🌤"), 2: ("Parçalı bulutlu", "⛅"), 3: ("Bulutlu", "☁️"), 45: ("Sisli", "🌫"), 48: ("Sisli", "🌫"),
            51: ("Çisenti", "🌦"), 53: ("Çisenti", "🌦"), 55: ("Çisenti", "🌦"), 61: ("Hafif yağmur", "🌧"), 63: ("Yağmurlu", "🌧"), 65: ("Kuvvetli yağmur", "🌧"),
            71: ("Kar", "🌨"), 73: ("Kar", "🌨"), 75: ("Yoğun kar", "❄️"), 80: ("Sağanak", "🌦"), 81: ("Sağanak", "🌧"), 82: ("Kuvvetli sağanak", "⛈"),
            95: ("Gök gürültülü", "⛈"), 96: ("Dolu ve fırtına", "⛈"), 99: ("Dolu ve fırtına", "⛈")}


def _hava():
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", headers=_UA, timeout=12, params={
            "latitude": ",".join(str(s[1]) for s in SEHIRLER), "longitude": ",".join(str(s[2]) for s in SEHIRLER),
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
            "timezone": "Europe/Istanbul", "forecast_days": 5})
        veri = r.json()
    except (requests.RequestException, ValueError):
        return None
    veri = veri if isinstance(veri, list) else [veri]
    out = []
    for (ad, _, _), v in zip(SEHIRLER, veri):
        c, d = v.get("current") or {}, v.get("daily") or {}
        gunler = [{"tarih": t, "max": d["temperature_2m_max"][i], "min": d["temperature_2m_min"][i],
                   "kod": d["weather_code"][i], "yagis": (d.get("precipitation_probability_max") or [None] * 9)[i]} for i, t in enumerate(d.get("time") or [])]
        out.append({"ad": ad, "sicaklik": c.get("temperature_2m"), "hissedilen": c.get("apparent_temperature"), "nem": c.get("relative_humidity_2m"),
                    "ruzgar": c.get("wind_speed_10m"), "kod": c.get("weather_code"), "gunler": gunler})
    return {"sehirler": out}


# ---------- Önbellek ----------
_TOPLAYICI = {"tr-haberler": lambda: _haberler("tr-haberler"), "dunya-haberleri": lambda: _haberler("dunya-haberleri"),
              "piyasalar": _piyasalar, "hava": _hava}


def _yenile(modul):
    if not _kilitler[modul].acquire(blocking=False):
        return
    try:
        veri = _TOPLAYICI[modul]()
        if veri:
            db.gundem_kaydet(modul, veri)
            log.info("Gündem yenilendi: %s", modul)
    except Exception:
        log.exception("Gündem yenilenemedi: %s", modul)
    finally:
        _kilitler[modul].release()


def eski_mi(modul):
    k = db.gundem_oku(modul)
    if not k:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(k["at"])).total_seconds() > SURE_DK[modul] * 60


def getir(modul, bekle=False):
    """Önbellekteki veri; eskiyse arka planda yenilenir. Hiç veri yoksa (ilk açılış) bekle=True ile hemen toplanır."""
    k = db.gundem_oku(modul)
    if k is None and bekle:
        _yenile(modul)
        k = db.gundem_oku(modul)
    elif eski_mi(modul):
        threading.Thread(target=_yenile, args=(modul,), daemon=True).start()
    return k


def calisiyor(modul):
    return _kilitler[modul].locked()


def hepsini_tazele():
    """Uygulama açılınca: süresi dolan gündem modüllerini arka planda yeniler (yapay zekâ yok, ücretsiz)."""
    for m in SURE_DK:
        if eski_mi(m) and not calisiyor(m):
            threading.Thread(target=_yenile, args=(m,), daemon=True).start()
