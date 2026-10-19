"""Tek kullanıcılı giriş: şifre (Argon2 özeti) + doğrulama uygulaması kodu (TOTP).

Gizli değerler yalnızca ortam değişkenlerinden okunur:
APP_PASSWORD_HASH, TOTP_SECRET, SESSION_SECRET.
"""
import hashlib
import hmac
import os
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
IP_LIMIT, IP_WINDOW = 5, 15 * 60          # aynı IP'den 15 dk'da 5 hatalı deneme
GLOBAL_LIMIT, GLOBAL_WINDOW = 20, 3600    # tüm IP'lerden 1 saatte 20 hatalı deneme → giriş kilitlenir

_ph = PasswordHasher()


def configured():
    return all(os.environ.get(k) for k in ("APP_PASSWORD_HASH", "TOTP_SECRET", "SESSION_SECRET"))


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


def check_login(password, code, ip):
    """Doğruysa yeni oturum kimliği döner, değilse None."""
    ok = False
    try:
        ok = _ph.verify(os.environ["APP_PASSWORD_HASH"], password or "")
    except (VerificationError, InvalidHashError):
        ok = False
    code_ok = pyotp.TOTP(os.environ["TOTP_SECRET"]).verify((code or "").replace(" ", ""), valid_window=1)
    if not (ok and code_ok):
        db.fail_add(ip, time.time())
        return None
    db.fail_clear(ip)
    sid = secrets.token_urlsafe(32)
    db.session_create(sid, ip, time.time())
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
    if not s or now - s["created_at"] > SESSION_MAX or now - s["last_seen"] > IDLE_MAX:
        if s:
            db.session_delete(sid)
        return None
    db.session_touch(sid, now)
    return sid


def csrf_token(sid):
    return hmac.new(os.environ["SESSION_SECRET"].encode(), ("csrf:" + sid).encode(), hashlib.sha256).hexdigest()


def csrf_ok(sid, token):
    return bool(token) and hmac.compare_digest(csrf_token(sid), token)
