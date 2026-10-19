#!/bin/zsh
# Bir kez çalıştırılır: Claude'un EA ajandasına yazması için rastgele bir anahtar üretir,
# Mac'te Anahtar Zinciri'ne (ea-api-token) ve Railway'de EA_API_TOKEN değişkenine kaydeder.
# Anahtar ekrana yazdırılmaz.
set -e
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/sunucu"
TOKEN=$(openssl rand -hex 32)
security add-generic-password -U -s ea-api-token -a emre -w "$TOKEN"
railway variables --service ea-sunucu --set "EA_API_TOKEN=$TOKEN" >/dev/null
unset TOKEN
echo "Tamam: anahtar Anahtar Zinciri'ne ve Railway'e kaydedildi. Railway birkaç dakika içinde yeniden başlayacak."
