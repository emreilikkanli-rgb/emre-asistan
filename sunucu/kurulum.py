"""Giriş şifresi, doğrulama kodu anahtarı ve oturum anahtarını üretir.

Kendi bilgisayarınızda çalıştırın:  python3 kurulum.py
Çıkan üç değeri Railway → Variables bölümüne yapıştırın. Hiçbir yere kaydedilmez.
"""
import getpass
import secrets
import sys

try:
    import pyotp
    from argon2 import PasswordHasher
except ImportError:
    sys.exit("Önce paketleri kurun: .venv/bin/pip install pyotp argon2-cffi")

print("\nEmre'nin Asistanı · güvenlik kurulumu\n")
while True:
    p1 = getpass.getpass("Giriş şifresi (en az 12 karakter): ")
    if len(p1) < 12:
        print("  En az 12 karakter olmalı.")
        continue
    if getpass.getpass("Şifre (tekrar): ") != p1:
        print("  İki şifre aynı değil.")
        continue
    break

totp = pyotp.random_base32()
uri = pyotp.TOTP(totp).provisioning_uri(name="Emre'nin Asistanı", issuer_name="EA")

print("\n1) Doğrulama uygulamasına (Google Authenticator, Microsoft Authenticator...) şu anahtarı ekleyin:")
print("   Hesap adı: EA   ·   Anahtar: %s   ·   Tür: zamana bağlı" % totp)
print("   (Bağlantı: %s )" % uri)
print("\n2) Railway → projeniz → Variables bölümüne şu üç değişkeni ekleyin:\n")
print("APP_PASSWORD_HASH=%s" % PasswordHasher().hash(p1))
print("TOTP_SECRET=%s" % totp)
print("SESSION_SECRET=%s" % secrets.token_urlsafe(48))
print("\nBu pencereyi kapattıktan sonra değerler hiçbir yerde kalmaz.\n")
