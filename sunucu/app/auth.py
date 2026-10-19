"""Tek kullanıcılı giriş: kullanıcı adı + şifre (Argon2 özeti); TOTP_SECRET tanımlıysa ayrıca doğrulama kodu.

Kullanıcı adı ve şifre özeti veritabanındaki "kimlik" tablosundadır ("Şifremi unuttum" ile kurulur/değişir).
Orada şifre yoksa eski APP_PASSWORD_HASH ortam değişkeni geçerlidir (kullanıcı adı sorulmaz).
SESSION_SECRET ve isteğe bağlı TOTP_SECRET yalnızca ortam değişkenlerinden okunur.
"""
import hashlib
import hmac
import os
import re
import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from itsdangerous import BadSignature, URLSafeSerializer

from . import db

COOKIE = "ea_oturum"
SESSION_MAX = 12 * 3600       # oturum en fazla 12 saat
IDLE_MAX = 30 * 60            # 30 dk işlem yoksa çıkış
HATIRLA_MAX = 30 * 86400      # "Beni hatırla": 30 gün
SIFRE_MIN = 6
KURTARMA_MAIL = "emre.ilikkanli@cyprusroyal.com"   # şifre sıfırlama linki yalnızca bu adrese gider
RESET_SURE = 30 * 60          # sıfırlama linki 30 dk geçerli
RESET_ARALIK, RESET_GUNLUK = 5 * 60, 5   # en sık 5 dk'da bir, günde en fazla 5 link
KULLANICI_RE = re.compile(r"^[a-z0-9._\-]{3,32}$")
IP_LIMIT, IP_WINDOW = 5, 15 * 60          # aynı IP'den 15 dk'da 5 hatalı deneme
GLOBAL_LIMIT, GLOBAL_WINDOW = 20, 3600    # tüm IP'lerden 1 saatte 20 hatalı deneme → giriş kilitlenir

_ph = PasswordHasher()


def _sifre_ozeti():
    return db.kimlik_get("sifre") or os.environ.get("APP_PASSWORD_HASH", "")


def kullanici():
    return db.kimlik_get("kullanici")


def configured():
    return bool(os.environ.get("SESSION_SECRET")) and bool(_sifre_ozeti())


def totp_enabled():
    return bool(os.environ.get("TOTP_SECRET"))


def _serializer():
    return URLSafeSerializer(os.environ["SESSION_SECRET"], salt="ea-oturum")


def client_ip(request):
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?"))[:64]


def lockout_message(ip):
    now = time.time()
    if db.fail_count(now - GLOBAL_WINDOW) >= GLOBAL_LIMIT:
        return "Çok fazla hatalı giriş denemesi yapıldı; giriş 1 saatliğine kilitlendi."
    if db.fail_count(now - IP_WINDOW, ip) >= IP_LIMIT:
        return "Bu cihazdan çok fazla hatalı deneme yapıldı; 15 dakika sonra tekrar deneyin."
    return None


def check_login(username, password, code, ip, hatirla=False):
    """Doğruysa yeni oturum kimliği döner, değilse None."""
    ok = False
    try:
        ok = _ph.verify(_sifre_ozeti(), password or "")
    except (VerificationError, InvalidHashError):
        ok = False
    beklenen = kullanici()
    if beklenen and not hmac.compare_digest(beklenen, (username or "").strip().lower()):
        ok = False
    code_ok = (not totp_enabled()) or pyotp.TOTP(os.environ["TOTP_SECRET"]).verify((code or "").replace(" ", ""), valid_window=1)
    if not (ok and code_ok):
        db.fail_add(ip, time.time())
        return None
    db.fail_clear(ip)
    return _oturum_ac(ip, hatirla)


def _oturum_ac(ip, hatirla=False):
    sid = secrets.token_urlsafe(32)
    db.session_create(sid, ip, time.time(), hatirla)
    return sid


def cookie_value(sid):
    return _serializer().dumps(sid)


def current_session(request):
    raw = request.cookies.get(COOKIE)
    if not raw or not configured():
        return None
    try:
        sid = _serializer().loads(raw)
    except BadSignature:
        return None
    s = db.session_get(sid)
    now = time.time()
    uzun = s and s.get("kalici")
    if not s or now - s["created_at"] > (HATIRLA_MAX if uzun else SESSION_MAX) or now - s["last_seen"] > (HATIRLA_MAX if uzun else IDLE_MAX):
        if s:
            db.session_delete(sid)
        return None
    db.session_touch(sid, now)
    return sid


def csrf_token(sid):
    return hmac.new(os.environ["SESSION_SECRET"].encode(), ("csrf:" + sid).encode(), hashlib.sha256).hexdigest()


def csrf_ok(sid, token):
    return bool(token) and hmac.compare_digest(csrf_token(sid), token)


# ---------- Şifremi unuttum ----------
def _jeton_ozeti(t):
    return hashlib.sha256(("ea-sifirla:" + (t or "")).encode()).hexdigest()


def sifirlama_iste(mail, ip, yeni_kullanici=""):
    """Yazılan adres kurtarma adresiyse (jeton, None) döner; değilse (None, neden).
    Link yalnızca KURTARMA_MAIL adresine gönderilir; yazılan adrese asla gönderilmez.
    yeni_kullanici: hesap oluştururken seçilen kullanıcı adı; mail doğrulanınca kaydedilir."""
    yeni_kullanici = (yeni_kullanici or "").strip().lower()
    if yeni_kullanici and not KULLANICI_RE.match(yeni_kullanici):
        return None, "kullanici"
    if not hmac.compare_digest((mail or "").strip().lower(), KURTARMA_MAIL):
        db.fail_add(ip, time.time())
        return None, "adres"
    now = time.time()
    gecmis = [float(x) for x in db.kimlik_get("sifirlama_gecmis").split(",") if x]
    gecmis = [x for x in gecmis if now - x < 86400]
    if gecmis and now - gecmis[-1] < RESET_ARALIK:
        return None, "sik"
    if len(gecmis) >= RESET_GUNLUK:
        return None, "gunluk"
    t = secrets.token_urlsafe(32)
    db.kimlik_set("sifirlama", "%s|%d" % (_jeton_ozeti(t), int(now + RESET_SURE)))
    db.kimlik_set("sifirlama_gecmis", ",".join("%.0f" % x for x in gecmis + [now]))
    if yeni_kullanici:
        db.kimlik_set("bekleyen_kullanici", yeni_kullanici)
    return t, None


def bekleyen_kullanici():
    return db.kimlik_get("bekleyen_kullanici")


def sifirlama_gecerli(t):
    kayit = db.kimlik_get("sifirlama")
    if not (t and "|" in kayit):
        return False
    ozet, son = kayit.split("|", 1)
    return hmac.compare_digest(ozet, _jeton_ozeti(t)) and time.time() < int(son)


def sifirlama_tamamla(t, username, password, ip):
    """Kullanıcı adı ve şifreyi kaydeder, tüm eski oturumları kapatır, yeni oturum açar. (sid, hata)"""
    if not sifirlama_gecerli(t):
        return None, "Bu link geçersiz ya da süresi dolmuş. Yeni bir link isteyin."
    username = (username or "").strip().lower()
    if not KULLANICI_RE.match(username):
        return None, "Kullanıcı adı 3–32 karakter olmalı; harf, rakam, nokta, tire ya da alt çizgi kullanın (Türkçe karakter olmadan)."
    if len(password or "") < SIFRE_MIN:
        return None, "Şifre en az %d karakter olmalı." % SIFRE_MIN
    db.kimlik_set("kullanici", username)
    db.kimlik_set("sifre", _ph.hash(password))
    db.kimlik_del("sifirlama")  # link tek kullanımlık
    db.kimlik_del("bekleyen_kullanici")
    db.session_delete()          # eski şifreyle açılmış tüm oturumlar kapanır
    db.fail_clear(ip)
    return _oturum_ac(ip, hatirla=True), None  # kayıttan sonra bu cihaz 30 gün hatırlanır
