"""Gizli değişkenleri Railway'e, hiçbirini ekrana ya da dosyaya yazmadan gönderir.

Kendi Terminalinizde, sunucu klasöründe çalıştırın:  .venv/bin/python railway_gizli.py
- Giriş şifresi: sizden sorulur, Railway'e yalnızca Argon2 özeti gider.
- Mail şifresi: macOS Anahtar Zinciri'nden okunur (servis: sirket-mail-imap).
- Claude API anahtarı: gizli olarak sorulur.
"""
import getpass
import os
import secrets
import shutil
import subprocess
import sys

from argon2 import PasswordHasher

SERVICE = "ea-sunucu"
MAIL_USER = os.environ.get("EWS_USER", "emre.ilikkanli@cyprusroyal.com")
RAILWAY = shutil.which("railway") or os.path.expanduser("~/.local/bin/railway")


def push(key, value, deploy=False):
    args = [RAILWAY, "variable", "set", key, "--stdin", "--service", SERVICE]
    if not deploy:
        args.append("--skip-deploys")
    r = subprocess.run(args, input=value.encode(), capture_output=True)
    if r.returncode != 0:
        sys.exit("  %s gönderilemedi (railway hata kodu %d). Railway girişini ve proje bağlantısını kontrol edin." % (key, r.returncode))
    print("  ✓ %s Railway'e kaydedildi" % key)


print("\nEmre'nin Asistanı · Railway gizli değişken kurulumu\n")

while True:
    p1 = getpass.getpass("1/2  Asistan giriş şifresi belirleyin (en az 12 karakter, ekranda görünmez): ")
    if len(p1) < 12:
        print("     En az 12 karakter olmalı.")
        continue
    if getpass.getpass("     Şifre (tekrar): ") != p1:
        print("     İki şifre aynı değil.")
        continue
    break

key = getpass.getpass("2/2  Claude API anahtarını yapıştırın (console.anthropic.com, ekranda görünmez): ").strip()
if not key.startswith("sk-ant-"):
    sys.exit("     Anahtar 'sk-ant-' ile başlamalı. İşlem durduruldu.")

mail = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "sirket-mail-imap", "-a", MAIL_USER, "-w"],
                      capture_output=True, text=True).stdout.rstrip("\n")
if not mail:
    sys.exit("     Mail şifresi Anahtar Zinciri'nde bulunamadı. İşlem durduruldu.")

print("\nRailway'e gönderiliyor…")
push("APP_PASSWORD_HASH", PasswordHasher().hash(p1))
push("SESSION_SECRET", secrets.token_urlsafe(48))
push("EWS_PASSWORD", mail)
push("ANTHROPIC_API_KEY", key, deploy=True)
del p1, key, mail

print("
Tamam. Sunucu bir-iki dakika içinde yeni ayarlarla açılır.
")
