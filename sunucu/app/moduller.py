"""Ana ekrandaki modüller (uygulama ikonları). hazir=False olanlar "Yakında" sayfasına gider."""

GRUPLAR = [
    ("is", "İş ve planlama"),
    ("gundem", "Gündem"),
    ("kisisel", "Kişisel"),
]

MODULLER = [
    {"slug": "ajanda", "ust": "Emre'nin", "ad": "Ajandası", "grup": "is", "href": "/ajanda", "hazir": True,
     "aciklama": "Günlük, haftalık ve aylık planınız, hatırlatmalar ve özel günler."},
    {"slug": "mailler", "ust": "Emre'nin", "ad": "Mailleri", "grup": "is", "href": "/mailler", "hazir": True,
     "aciklama": "Önemli kişiler, takip, tartışmalar, şikâyetler ve ödeme mailleri."},
    {"slug": "is-planlama", "ust": "Emre'nin", "ad": "İş Planlaması", "grup": "is", "href": "/ajanda#gorevler", "hazir": True,
     "aciklama": "Ekibe verilen görevler, bitiş tarihleri, uzatmalar ve değerlendirmeler."},
    {"slug": "kibris-etkinlik", "ust": "Kıbrıs", "ad": "Etkinlikleri", "grup": "is", "href": "/etkinlikler", "hazir": True,
     "aciklama": "KKTC'de konser, tiyatro, festival, otel ve mekân etkinlikleri; tarih, saat, sanatçı ve ücret bilgisiyle."},
    {"slug": "tr-haberler", "ust": "Emre'nin", "ad": "TR Haberleri", "grup": "gundem", "href": "/gundem/tr-haberler", "hazir": True,
     "aciklama": "Türkiye ve KKTC gündeminden sizin için seçilmiş haberler.",
     "planlanan": ["Sabah ve akşam kısa gündem özeti", "Turizm, havacılık ve otelcilik haberleri öncelikli", "KKTC'den yerel gelişmeler"]},
    {"slug": "dunya-haberleri", "ust": "Emre'ye", "ad": "Dünyadan Haberler", "grup": "gundem", "href": "/gundem/dunya-haberleri", "hazir": True,
     "aciklama": "Dünya gündemi ve sektörünüzü etkileyen gelişmeler, kısa özetlerle.",
     "planlanan": ["Günün 5 önemli dünya haberi", "Avrupa pazarları ve seyahat eğilimleri", "Kaynağına bağlantılı kısa özetler"]},
    {"slug": "piyasalar", "ust": "Emre'nin", "ad": "Piyasaları", "grup": "gundem", "href": "/piyasalar", "hazir": True,
     "aciklama": "Döviz, altın ve borsa: işinizi etkileyen rakamlar tek bakışta.",
     "planlanan": ["EUR, USD, GBP / TL kurları", "Altın ve petrol", "Gün içi değişim ve kısa yorum"]},
    {"slug": "hava", "ust": "Emre'nin", "ad": "Hava Durumu", "grup": "gundem", "href": "/hava", "hazir": True,
     "aciklama": "Bulunduğunuz yer ve rotalarınız için hava durumu.",
     "planlanan": ["İstanbul, Lefkoşa, Girne", "Seyahat rotalarınıza göre tahmin", "Uçuş günü uyarıları"]},
    {"slug": "rotalar", "ust": "Emre'nin", "ad": "Rotaları", "grup": "kisisel", "hazir": False,
     "aciklama": "Seyahat planlarınız, gidilecek yerler, uçuş ve otel bilgileri.",
     "planlanan": ["Yaklaşan seyahatler ve uçuşlar", "Gidilecek yerler listesi ve harita", "Otel ve restoran notları"]},
    {"slug": "hobiler", "ust": "Emre'nin", "ad": "Hobileri", "grup": "kisisel", "hazir": False,
     "aciklama": "İlgi alanlarınız, takip ettikleriniz ve hobi notlarınız.",
     "planlanan": ["İlgi alanlarınıza göre öneriler", "Etkinlik ve maç takvimi", "Hobi notları ve listeler"]},
    {"slug": "saglik", "ust": "Emre'nin", "ad": "Sağlık ve Sporu", "grup": "kisisel", "hazir": False,
     "aciklama": "Spor, yürüyüş ve sağlık hatırlatmaları.",
     "planlanan": ["Haftalık spor planı", "Kontrol ve ilaç hatırlatmaları", "Kısa günlük hedefler"]},
    {"slug": "notlar", "ust": "Emre'nin", "ad": "Notları", "grup": "kisisel", "hazir": False,
     "aciklama": "Hızlı notlar, fikirler, okunacak ve izlenecekler.",
     "planlanan": ["Sesli ya da yazılı hızlı not", "Fikir ve okuma listeleri", "Claude ile özetleme"]},
]

BY_SLUG = {m["slug"]: m for m in MODULLER}
