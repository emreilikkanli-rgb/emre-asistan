"""SQLite veritabanı (Railway'de kalıcı diskte: DATA_DIR)."""
import json
import re
import os
import sqlite3
import threading
from datetime import datetime, timezone

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)
_PATH = os.path.join(DATA_DIR, "app.db")
_lock = threading.Lock()

# Kişisel veri içermeyen varsayılanlar; gerçek değerler Ayarlar sayfasından girilir.
DEFAULT_SETTINGS = {
    "name": "",
    "oncelikli": "",
    "sikayet_kelimeleri": "şikayet; şikâyet; complaint; memnuniyetsiz; memnun değil; memnun kalmadı; mağdur; rezalet; kabul edilemez; skandal; tazminat; kötü hizmet; berbat; iade talep; refund; sorun yaşa; problem yaşa; olumsuz deneyim; dissatisf; disappointed",
    "odeme_kelimeleri": "ödeme talebi; ödeme talep; ödeme hatırlatma; ödemenin yapılması; ödemenin gerçekleştirilmesi; ödeme yapılmadığı; ödeme yapılmaması; ödenmediği takdirde; ödeme alınmadan; ödeme gelmediği; ödemesi yapılmayan; ödeme bekl; giriş alınmayacak; girişi alınmayacak; girişleri alınmayacak; giriş yapılamayacak; giriş yapılmayacak; check in yapılmayacak; check-in yapılmayacak; konaklama yapılamayacak; kabul edilmeyecek; misafir kabul; ön ödeme; prepayment; payment reminder; payment request; outstanding; overdue; vadesi geçmiş; son ödeme tarihi; açık bakiye; ödenmemiş",
    "tartisma_kelimeleri": "kabul edilemez; kabul etmiyoruz; kabul etmemiz mümkün değil; itiraz; tekrar hatırlat; ikinci kez; defalarca; hala dönüş; hâlâ dönüş; halen dönüş; dönüş alamadık; dönüş sağlanmadı; yanıt alamadık; cevap alamadık; ısrarla; mağduriyet; mağdur; sorumluluk; no show; noshow; tazminat; hata yapılmış; yanlış bilgi; yanlış fiyat; yanlış rezervasyon; bilginiz dışında; sitem; üzülerek; anlaşılamadı",
    "rehber_kelimeleri": "rehber; rehberi; rehberimiz; guide; tur lideri",
    "rehber_olumsuz": "şikayet; şikâyet; memnun; ilgisiz; ilgilenmedi; kaba; saygısız; geç kaldı; gelmedi; ulaşılamadı; davranış; tavır; sorun; problem; hata; mağdur; complaint",
    "kampanya_kelimeleri": "kampanya; campaign; özel fiyat; özel teklif; special offer; indirim; discount; erken rezervasyon; early booking; erken ödeme; promosyon; promotion; fırsat; son dakika; last minute; stop sale; stopsale; release; allotment; kontenjan açıldı; yeni fiyat; fiyat güncelleme; rate update; new rates; kontrat; contract; özel aksiyon; aksiyon; paket fiyat; black friday; yılbaşı programı; gala; free night; ücretsiz gece; upgrade; komisyon; incentive",
    "sitem_kelimeleri": "maalesef; hayal kırıklığı; üzücü; kabul etmiyoruz; kabul edemiyoruz; kabul edilemez; hala; hâlâ; halen; defalarca; tekrar tekrar; ikinci kez; üçüncü kez; rica etmemize rağmen; rica ettiğimiz halde; bilgimiz dışında; dönüş alamadık; yanıt alamadık; cevap alamadık; bekletiliyoruz; mağdur; ihmal; sorumluluk sizde; ciddiyetsiz; yanlış bilgi; hatalı; şikayetçiyiz; şikâyetçiyiz; sitem; memnun değiliz; iş birliğimizi; çalışmayı sonlandır; son kez; ivedilikle; acilen; urgent; asap; disappointed; unacceptable; not acceptable; still waiting; complaint; unhappy; poor service; escalate",
    "ajanda_gonderenler": "",
    "aylik_limit_usd": "5",
    "takvim": "",  # boş: otomatik kontrol yok, yalnızca sayfa açılınca/yenilenince
}


def _conn():
    c = sqlite3.connect(_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, created_at TEXT NOT NULL,
            hours INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, stats TEXT, data TEXT,
            cost REAL DEFAULT 0, tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at REAL NOT NULL, last_seen REAL NOT NULL, ip TEXT);
        CREATE TABLE IF NOT EXISTS login_fails (ip TEXT NOT NULL, at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS docs (collection TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY (collection, id));
        CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS kimlik (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS etkinlik_rapor (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            status TEXT NOT NULL, error TEXT, data TEXT, cost REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS gundem_cache (modul TEXT PRIMARY KEY, at TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS etkinlik_gorulen (anahtar TEXT PRIMARY KEY, ilk TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mail_karar (anahtar TEXT PRIMARY KEY, durum TEXT NOT NULL, at TEXT NOT NULL,
            rid INTEGER, ref TEXT, kart TEXT NOT NULL);
        """)
        cols = [r[1] for r in c.execute("PRAGMA table_info(sessions)")]
        if "kalici" not in cols:  # "Beni hatırla" oturumları
            c.execute("ALTER TABLE sessions ADD COLUMN kalici INTEGER NOT NULL DEFAULT 0")
        # 21 Ekim 2026: Emre Bey'in eklediği önemli kişiler (yoksa eklenir; Ayarlar'dan düzenlenebilir)
        mevcut = c.execute("SELECT value FROM settings WHERE key='oncelikli'").fetchone()
        mevcut = mevcut[0] if mevcut else ""
        eklenecek = ["Mehmet Mülayim", "Hakan Ural", "Hatice @concorde", "Ulaş @concorde", "Hakan @dome", "Serdar @cratos",
                     "Hulusi @cratos", "Süleyman @salamis", "Şeref", "Mehtap @merit"]
        satirlar = [x.strip() for x in re.split(r"[;\n]", mevcut) if x.strip()]
        yeni = [e for e in eklenecek if e.lower() not in {x.lower() for x in satirlar}]
        if yeni:
            c.execute("INSERT INTO settings(key, value) VALUES('oncelikli', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      ("\n".join(satirlar + yeni),))
        # 20 Ekim 2026 (Emre Bey'in isteği, bütçe): otomatik kontrol yok; eski varsayılan takvim boşaltılır.
        c.execute("UPDATE settings SET value='' WHERE key='takvim' AND value='08:30=sabah;13:00=ara;17:00=ara'")


def get_settings():
    out = dict(DEFAULT_SETTINGS)
    with _conn() as c:
        for r in c.execute("SELECT key, value FROM settings"):
            out[r["key"]] = r["value"]
    return out


def save_settings(values):
    with _lock, _conn() as c:
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                c.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))


def add_report(kind, hours, status, error=None, stats=None, data=None, usage=None):
    usage = usage or {}
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO reports(kind, created_at, hours, status, error, stats, data, cost, tokens_in, tokens_out) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (kind, datetime.now(timezone.utc).isoformat(), hours, status, error, json.dumps(stats or {}, ensure_ascii=False),
             json.dumps(data or {}, ensure_ascii=False), usage.get("cost", 0), usage.get("input", 0), usage.get("output", 0)))
        return cur.lastrowid


def get_report(rid=None):
    with _conn() as c:
        if rid is None:
            r = c.execute("SELECT * FROM reports WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
        else:
            r = c.execute("SELECT * FROM reports WHERE id=?", (rid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["stats"] = json.loads(d["stats"] or "{}")
    d["data"] = json.loads(d["data"] or "{}")
    return d


def list_reports(limit=60):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, kind, created_at, status, error, cost, stats FROM reports ORDER BY id DESC LIMIT ?", (limit,))]


def month_cost():
    """Bu ayki toplam Claude API harcaması: mail raporları + etkinlik aramaları."""
    start = datetime.now(timezone.utc).strftime("%Y-%m-01")
    with _conn() as c:
        return c.execute("SELECT (SELECT COALESCE(SUM(cost), 0) FROM reports WHERE created_at >= ?) + "
                         "(SELECT COALESCE(SUM(cost), 0) FROM etkinlik_rapor WHERE created_at >= ?)", (start, start)).fetchone()[0]


def prune_reports(keep_days=90):
    with _lock, _conn() as c:
        c.execute("DELETE FROM reports WHERE created_at < datetime('now', ?)", ("-%d days" % keep_days,))


# Oturumlar ve giriş denemeleri
def session_create(sid, ip, now, kalici=False):
    with _lock, _conn() as c:
        c.execute("INSERT INTO sessions(id, created_at, last_seen, ip, kalici) VALUES(?,?,?,?,?)", (sid, now, now, ip, 1 if kalici else 0))


def session_get(sid):
    with _conn() as c:
        r = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    return dict(r) if r else None


def session_touch(sid, now):
    with _lock, _conn() as c:
        c.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now, sid))


def session_delete(sid=None):
    with _lock, _conn() as c:
        if sid:
            c.execute("DELETE FROM sessions WHERE id=?", (sid,))
        else:
            c.execute("DELETE FROM sessions")


def fail_add(ip, now):
    with _lock, _conn() as c:
        c.execute("INSERT INTO login_fails(ip, at) VALUES(?, ?)", (ip, now))
        c.execute("DELETE FROM login_fails WHERE at < ?", (now - 86400,))


def fail_count(since, ip=None):
    with _conn() as c:
        if ip:
            return c.execute("SELECT COUNT(*) FROM login_fails WHERE ip=? AND at>=?", (ip, since)).fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM login_fails WHERE at>=?", (since,)).fetchone()[0]


def fail_clear(ip):
    with _lock, _conn() as c:
        c.execute("DELETE FROM login_fails WHERE ip=?", (ip,))


# Ajanda belgeleri (items, gorevler, plans): claude.ai ajandasıyla aynı yapı
DOC_COLLECTIONS = ("items", "gorevler", "plans", "ayarlar")


def doc_list(collection):
    with _conn() as c:
        return [{"id": r["id"], "data": json.loads(r["body"])}
                for r in c.execute("SELECT id, body FROM docs WHERE collection=? ORDER BY id", (collection,))]


def doc_get(collection, doc_id):
    with _conn() as c:
        r = c.execute("SELECT body FROM docs WHERE collection=? AND id=?", (collection, doc_id)).fetchone()
    return json.loads(r["body"]) if r else None


def doc_set(collection, doc_id, body):
    with _lock, _conn() as c:
        c.execute("INSERT INTO docs(collection, id, body, updated_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(collection, id) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at",
                  (collection, doc_id, json.dumps(body, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))


def doc_delete(collection, doc_id):
    with _lock, _conn() as c:
        c.execute("DELETE FROM docs WHERE collection=? AND id=?", (collection, doc_id))


def push_list():
    with _conn() as c:
        return [json.loads(r["body"]) for r in c.execute("SELECT body FROM push_subs")]


def push_add(sub):
    with _lock, _conn() as c:
        c.execute("INSERT INTO push_subs(endpoint, body, created_at) VALUES(?,?,?) ON CONFLICT(endpoint) DO UPDATE SET body=excluded.body",
                  (sub["endpoint"], json.dumps(sub), datetime.now(timezone.utc).isoformat()))


def push_remove(endpoint):
    with _lock, _conn() as c:
        c.execute("DELETE FROM push_subs WHERE endpoint=?", (endpoint,))


# Giriş bilgileri (kullanıcı adı, şifre özeti, kurtarma maili, şifre sıfırlama jetonu). Ayarlar sayfasından ayrı tutulur.
def kimlik_get(key, default=""):
    with _conn() as c:
        r = c.execute("SELECT value FROM kimlik WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def kimlik_set(key, value):
    with _lock, _conn() as c:
        c.execute("INSERT INTO kimlik(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def kimlik_del(key):
    with _lock, _conn() as c:
        c.execute("DELETE FROM kimlik WHERE key=?", (key,))


# Emre Bey'in mail kararları: okundu (listeden kalkar), takip (Takiptekiler'de kalır), gereksiz (kalkar + öğrenme örneği)
def karar_set(anahtar, durum, rid, ref, kart):
    with _lock, _conn() as c:
        c.execute("INSERT INTO mail_karar(anahtar, durum, at, rid, ref, kart) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(anahtar) DO UPDATE SET durum=excluded.durum, at=excluded.at, rid=excluded.rid, ref=excluded.ref, kart=excluded.kart",
                  (anahtar, durum, datetime.now(timezone.utc).isoformat(), rid, str(ref), json.dumps(kart, ensure_ascii=False)))


def karar_sil(anahtar):
    with _lock, _conn() as c:
        c.execute("DELETE FROM mail_karar WHERE anahtar=?", (anahtar,))


def karar_hepsi():
    with _conn() as c:
        return {r["anahtar"]: dict(r, kart=json.loads(r["kart"])) for r in c.execute("SELECT * FROM mail_karar")}


def karar_liste(durum, limit=50, gun=90):
    with _conn() as c:
        rows = c.execute("SELECT * FROM mail_karar WHERE durum=? AND at >= datetime('now', ?) ORDER BY at DESC LIMIT ?",
                         (durum, "-%d days" % gun, limit)).fetchall()
    return [dict(r, kart=json.loads(r["kart"])) for r in rows]


# Kıbrıs etkinlik taramaları
def etkinlik_ekle(status, data=None, hata=None, maliyet=0):
    with _lock, _conn() as c:
        c.execute("INSERT INTO etkinlik_rapor(created_at, status, error, data, cost) VALUES(?,?,?,?,?)",
                  (datetime.now(timezone.utc).isoformat(), status, hata, json.dumps(data or {}, ensure_ascii=False), maliyet))
        c.execute("DELETE FROM etkinlik_rapor WHERE created_at < datetime('now', '-120 days')")


def etkinlik_son(sadece_ok=True):
    with _conn() as c:
        r = c.execute("SELECT * FROM etkinlik_rapor %s ORDER BY id DESC LIMIT 1" % ("WHERE status='ok'" if sadece_ok else "")).fetchone()
    if not r:
        return None
    d = dict(r)
    d["data"] = json.loads(d["data"] or "{}")
    return d


def etkinlik_gorulen_isle(anahtarlar, bugun):
    """Etkinliklerin ilk görüldüğü günü kaydeder. Dönüş: ({anahtar: ilk gün}, önceki günlerden kayıt var mı)."""
    with _lock, _conn() as c:
        onceki = c.execute("SELECT COUNT(*) FROM etkinlik_gorulen WHERE ilk < ?", (bugun,)).fetchone()[0] > 0
        for a in anahtarlar:
            c.execute("INSERT OR IGNORE INTO etkinlik_gorulen(anahtar, ilk) VALUES(?, ?)", (a, bugun))
        c.execute("DELETE FROM etkinlik_gorulen WHERE ilk < date('now', '-200 days')")
        q = ",".join("?" * len(anahtarlar))
        ilk = dict(c.execute("SELECT anahtar, ilk FROM etkinlik_gorulen WHERE anahtar IN (%s)" % q, list(anahtarlar)).fetchall()) if anahtarlar else {}
    return ilk, onceki


# Gündem modülleri (haberler, piyasalar, hava) önbelleği
def gundem_kaydet(modul, veri):
    with _lock, _conn() as c:
        c.execute("INSERT INTO gundem_cache(modul, at, data) VALUES(?,?,?) ON CONFLICT(modul) DO UPDATE SET at=excluded.at, data=excluded.data",
                  (modul, datetime.now(timezone.utc).isoformat(), json.dumps(veri, ensure_ascii=False)))


def gundem_oku(modul):
    with _conn() as c:
        r = c.execute("SELECT at, data FROM gundem_cache WHERE modul=?", (modul,)).fetchone()
    return {"at": r["at"], "data": json.loads(r["data"])} if r else None
