"""SQLite veritabanı (Railway'de kalıcı diskte: DATA_DIR)."""
import json
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
    "aylik_limit_usd": "5",
    "takvim": "08:30=sabah;13:00=ara;17:00=ara",
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
        """)


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
    start = datetime.now(timezone.utc).strftime("%Y-%m-01")
    with _conn() as c:
        return c.execute("SELECT COALESCE(SUM(cost), 0) FROM reports WHERE created_at >= ?", (start,)).fetchone()[0]


def prune_reports(keep_days=90):
    with _lock, _conn() as c:
        c.execute("DELETE FROM reports WHERE created_at < datetime('now', ?)", ("-%d days" % keep_days,))


# Oturumlar ve giriş denemeleri
def session_create(sid, ip, now):
    with _lock, _conn() as c:
        c.execute("INSERT INTO sessions(id, created_at, last_seen, ip) VALUES(?,?,?,?)", (sid, now, now, ip))


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
