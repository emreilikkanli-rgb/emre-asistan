# Emre'nin Asistanı · sunucu

Exchange gelen kutusunu **salt okunur** tarar, Claude Haiku 4.5 ile önemli mailleri
(şikâyet, ödeme/giriş riski, öncelikli kişiler, ortak mail tartışmaları, aksiyonlar)
özetler ve şifre + doğrulama koduyla korunan bir web sayfasında gösterir.

## Railway değişkenleri (Variables)

| Değişken | Açıklama |
|---|---|
| `EWS_HOST` | Exchange sunucusu (ör. `mail.ornek.com`) |
| `EWS_USER` | Mail adresiniz |
| `EWS_PASSWORD` | Mail şifreniz |
| `ANTHROPIC_API_KEY` | Claude API anahtarı |
| `APP_PASSWORD_HASH`, `TOTP_SECRET`, `SESSION_SECRET` | `python3 kurulum.py` çıktısı |

Kalıcı disk (Volume) `/data` yoluna bağlanmalıdır; raporlar ve ayarlar orada tutulur.
Gizli değerler hiçbir zaman depoya yazılmaz.
