"""Kişisel modüller: Notlar, Rotalar, Hobiler, Sağlık ve Spor.

Veriler Emre Bey'in kendi girdiği kayıtlardır; sunucu veritabanındaki belge tablosunda (docs) modül adıyla
ayrı koleksiyonlarda durur ve sayfa /api/db uçlarıyla (oturum + CSRF) okur/yazar. Yapay zekâ kullanılmaz.
Her modül: bölümler (ikonlar), her bölümün kayıt alanları ve ikonların altında özet.
"""
from datetime import date, timedelta

from . import db

# alan: (anahtar, etiket, tür, seçenekler/ipucu); tür: metin | uzun | tarih | saat | sayi | secim | onay | baglanti
MODULLER = {
    "notlar": {
        "ust": "Emre'nin", "ad": "Notları", "kayit": "not",
        "bolumler": [
            {"id": "is", "ad": "İş", "ikon": "notlar", "renk": "amber"},
            {"id": "fikir", "ad": "Fikirler", "ikon": "hobiler", "renk": "violet"},
            {"id": "okunacak", "ad": "Okunacak / İzlenecek", "ikon": "turkce", "renk": "teal"},
            {"id": "genel", "ad": "Genel", "ikon": "takipte", "renk": "blue"},
        ],
        "alanlar": [("baslik", "Başlık", "metin", ""), ("metin", "Not", "uzun", ""), ("sabit", "Sabitle (en üstte göster)", "onay", "")],
        "sirala": "-guncelleme",
    },
    "rotalar": {
        "ust": "Emre'nin", "ad": "Rotaları", "kayit": "kayıt",
        "bolumler": [
            {"id": "seyahat", "ad": "Seyahatler", "ikon": "rotalar", "renk": "teal",
             "alanlar": [("baslik", "Seyahat", "metin", "ör. ATF fuarı, Antalya"), ("yer", "Şehir / ülke", "metin", ""),
                         ("baslangic", "Gidiş", "tarih", ""), ("bitis", "Dönüş", "tarih", ""), ("ulasim", "Uçuş / ulaşım", "metin", "ör. PC1929 07:40 ECN → AYT"),
                         ("konaklama", "Konaklama", "metin", "ör. Rixos Downtown, 3 gece"), ("not", "Not", "uzun", "")]},
            {"id": "gidilecek", "ad": "Gidilecek yerler", "ikon": "dunya-haberleri", "renk": "violet",
             "alanlar": [("baslik", "Yer", "metin", "ör. Kyoto"), ("yer", "Ülke", "metin", ""), ("oncelik", "Öncelik", "secim", "Yüksek|Normal|Bir gün"),
                         ("not", "Neden / not", "uzun", ""), ("baglanti", "Bağlantı", "baglanti", "")]},
        ],
        "sirala": "baslangic",
    },
    "hobiler": {
        "ust": "Emre'nin", "ad": "Hobileri", "kayit": "kayıt",
        "bolumler": [
            {"id": "kitap", "ad": "Kitaplar", "ikon": "notlar", "renk": "amber"},
            {"id": "film", "ad": "Film ve dizi", "ikon": "ozel-donem", "renk": "violet"},
            {"id": "spor", "ad": "Spor ve maçlar", "ikon": "saglik", "renk": "red"},
            {"id": "diger", "ad": "Diğer hobiler", "ikon": "hobiler", "renk": "teal"},
        ],
        "alanlar": [("baslik", "Ad", "metin", ""), ("kim", "Yazar / yönetmen / takım", "metin", ""), ("tarih", "Tarih (varsa)", "tarih", ""),
                    ("durum", "Durum", "secim", "Yapılacak|Devam ediyor|Bitti"), ("puan", "Puanım (1–5)", "sayi", ""),
                    ("not", "Not", "uzun", ""), ("baglanti", "Bağlantı", "baglanti", "")],
        "sirala": "durum",
    },
    "saglik": {
        "ust": "Emre'nin", "ad": "Sağlık ve Sporu", "kayit": "kayıt",
        "bolumler": [
            {"id": "aktivite", "ad": "Aktiviteler", "ikon": "saglik", "renk": "red",
             "alanlar": [("tarih", "Tarih", "tarih", "bugun"), ("tur", "Tür", "secim", "Yürüyüş|Koşu|Spor salonu|Yüzme|Bisiklet|Yoga / esneme|Tenis|Diğer"),
                         ("sure", "Süre (dakika)", "sayi", ""), ("mesafe", "Mesafe (km, varsa)", "sayi", ""), ("not", "Not", "metin", "")]},
            {"id": "kontrol", "ad": "Kontrol ve randevular", "ikon": "ajanda", "renk": "teal",
             "alanlar": [("baslik", "Kontrol / randevu", "metin", "ör. Diş kontrolü"), ("tarih", "Tarih", "tarih", ""), ("saat", "Saat", "saat", ""),
                         ("yer", "Doktor / yer", "metin", ""), ("not", "Not", "uzun", ""), ("tamam", "Yapıldı", "onay", "")]},
        ],
        "sirala": "-tarih",
        "hedef_dk": 150,  # haftalık hareket hedefi (DSÖ önerisi); sayfadan değiştirilebilir
    },
}
KOLEKSIYONLAR = tuple(MODULLER)


def alanlar(modul, bolum):
    m = MODULLER[modul]
    b = next((b for b in m["bolumler"] if b["id"] == bolum), None)
    return (b or {}).get("alanlar") or m.get("alanlar") or []


def kayitlar(modul):
    return [dict(r["data"], id=r["id"]) for r in db.doc_list(modul)]


def _pzt(d):
    return d - timedelta(days=d.weekday())


def ozet(modul, liste, bugun=None):
    """İkonların altındaki özet: modüle göre kısa sayılar ve öne çıkanlar."""
    bugun = bugun or date.today()
    b = bugun.isoformat()
    if modul == "notlar":
        sabit = [k for k in liste if k.get("sabit")]
        son = sorted(liste, key=lambda k: k.get("guncelleme") or "", reverse=True)[:5]
        return {"sayilar": [("Not", len(liste)), ("Sabit", len(sabit))], "liste_baslik": "📌 Sabit ve son notlar",
                "liste": (sabit + [k for k in son if not k.get("sabit")])[:6]}
    if modul == "rotalar":
        sey = [k for k in liste if k.get("bolum") == "seyahat"]
        yaklasan = sorted([k for k in sey if (k.get("bitis") or k.get("baslangic") or "") >= b], key=lambda k: k.get("baslangic") or "9")
        gezilen = [k for k in sey if (k.get("bitis") or k.get("baslangic") or "9") < b]
        sonraki = yaklasan[0] if yaklasan else None
        kalan = (date.fromisoformat(sonraki["baslangic"]) - bugun).days if sonraki and sonraki.get("baslangic") else None
        return {"sayilar": [("Yaklaşan seyahat", len(yaklasan)), ("Gidilecek yer", len([k for k in liste if k.get("bolum") == "gidilecek"])),
                            ("Gezilen", len(gezilen))],
                "vurgu": ("✈ Sıradaki: %s%s" % (sonraki.get("baslik"), (" · %d gün kaldı" % kalan) if kalan is not None and kalan >= 0 else " · şu an seyahattesiniz")) if sonraki else "",
                "liste_baslik": "✈ Yaklaşan seyahatler", "liste": yaklasan[:5]}
    if modul == "hobiler":
        devam = [k for k in liste if k.get("durum") == "Devam ediyor"]
        yapilacak = [k for k in liste if k.get("durum") in ("", None, "Yapılacak")]
        bitti = [k for k in liste if k.get("durum") == "Bitti"]
        yakin = sorted([k for k in liste if k.get("tarih") and k["tarih"] >= b], key=lambda k: k["tarih"])[:3]
        return {"sayilar": [("Devam eden", len(devam)), ("Sırada", len(yapilacak)), ("Biten", len(bitti))],
                "liste_baslik": "▶ Devam edenler ve yaklaşan tarihler", "liste": (yakin + devam)[:6]}
    if modul == "saglik":
        akt = [k for k in liste if k.get("bolum") == "aktivite"]
        hedef = int(MODULLER["saglik"]["hedef_dk"])
        ayar = db.doc_get("plans", "saglik-hedef")
        if ayar and str(ayar.get("dk", "")).isdigit():
            hedef = int(ayar["dk"])
        haftalar = []
        for i in range(3, -1, -1):  # son 4 hafta
            bas = _pzt(bugun) - timedelta(weeks=i)
            son = bas + timedelta(days=6)
            dk = sum(int(float(k.get("sure") or 0)) for k in akt if bas.isoformat() <= (k.get("tarih") or "") <= son.isoformat())
            haftalar.append({"ad": "Bu hafta" if i == 0 else "%d hafta önce" % i, "dk": dk, "yuzde": min(100, round(dk * 100 / hedef)) if hedef else 0})
        kontrol = sorted([k for k in liste if k.get("bolum") == "kontrol" and not k.get("tamam") and (k.get("tarih") or "9") >= b],
                         key=lambda k: k.get("tarih") or "9")
        return {"sayilar": [("Bu hafta (dk)", haftalar[-1]["dk"]), ("Hedef (dk)", hedef), ("Yaklaşan kontrol", len(kontrol))],
                "haftalar": haftalar, "hedef": hedef, "liste_baslik": "🩺 Yaklaşan kontroller", "liste": kontrol[:4]}
    return {}
