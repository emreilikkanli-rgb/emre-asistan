"""Emre'nin Asistanı: mail raporları web uygulaması (Railway)."""
import logging
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, db, jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
TZ = ZoneInfo("Europe/Istanbul")
SECURE = os.environ.get("COOKIE_INSECURE") != "1"  # yerel test dışında çerez yalnızca https

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def _local(iso, fmt="%d.%m.%Y %H:%M"):
    try:
        return datetime.fromisoformat(iso).astimezone(TZ).strftime(fmt)
    except (TypeError, ValueError):
        return iso or ""


templates.env.filters["yerel"] = _local
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _uzun_tarih(iso):
    d = datetime.fromisoformat(iso).astimezone(TZ)
    return "%d %s %d, %s · %s" % (d.day, AYLAR[d.month - 1], d.year, GUNLER[d.weekday()], d.strftime("%H:%M"))


templates.env.filters["uzun_tarih"] = _uzun_tarih


@app.on_event("startup")
def _startup():
    db.init()
    if os.environ.get("SCHEDULER_OFF") != "1":
        jobs.start()


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store"
    if SECURE:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


def _page(request, name, sid, **ctx):
    ctx.update(csrf=auth.csrf_token(sid) if sid else "", aylik=db.month_cost(),
               ayarlar=db.get_settings())
    return templates.TemplateResponse(request, name, ctx)


def _guard(request):
    sid = auth.current_session(request)
    return sid, (None if sid else RedirectResponse("/giris", status_code=303))


@app.get("/saglik", response_class=PlainTextResponse)
def saglik():
    return "ok"


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /\n"


@app.get("/giris", response_class=HTMLResponse)
def giris_form(request: Request):
    if not auth.configured():
        return templates.TemplateResponse(request, "giris.html", {"hata": "Sunucu henüz kurulmadı: APP_PASSWORD_HASH, TOTP_SECRET ve SESSION_SECRET değişkenlerini Railway'de tanımlayın.", "kapali": True})
    return templates.TemplateResponse(request, "giris.html", {"hata": auth.lockout_message(auth.client_ip(request))})


@app.post("/giris")
def giris(request: Request, sifre: str = Form(""), kod: str = Form("")):
    if not auth.configured():
        return RedirectResponse("/giris", status_code=303)
    ip = auth.client_ip(request)
    lock = auth.lockout_message(ip)
    if lock:
        return templates.TemplateResponse(request, "giris.html", {"hata": lock}, status_code=429)
    sid = auth.check_login(sifre, kod, ip)
    if not sid:
        return templates.TemplateResponse(request, "giris.html", {"hata": "Şifre ya da doğrulama kodu hatalı."}, status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.cookie_value(sid), max_age=auth.SESSION_MAX, httponly=True, secure=SECURE, samesite="strict")
    return resp


@app.post("/cikis")
def cikis(request: Request, csrf: str = Form("")):
    sid = auth.current_session(request)
    if sid and auth.csrf_ok(sid, csrf):
        db.session_delete(sid)
    resp = RedirectResponse("/giris", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
def ana(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    return _page(request, "rapor.html", sid, r=db.get_report(), son=db.list_reports(1))


@app.get("/rapor/{rid}", response_class=HTMLResponse)
def rapor(request: Request, rid: int):
    sid, redir = _guard(request)
    if redir:
        return redir
    return _page(request, "rapor.html", sid, r=db.get_report(rid), son=[])


@app.get("/raporlar", response_class=HTMLResponse)
def raporlar(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    return _page(request, "raporlar.html", sid, liste=db.list_reports())


@app.post("/calistir")
def calistir(request: Request, csrf: str = Form(""), tur: str = Form("ara")):
    sid, redir = _guard(request)
    if redir:
        return redir
    if not auth.csrf_ok(sid, csrf):
        return PlainTextResponse("Geçersiz istek.", status_code=400)
    threading.Thread(target=jobs.run, args=("sabah" if tur == "sabah" else "ara",), daemon=True).start()
    return RedirectResponse("/raporlar?basladi=1", status_code=303)


@app.get("/ayarlar", response_class=HTMLResponse)
def ayarlar(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    return _page(request, "ayarlar.html", sid, kaydedildi=request.query_params.get("ok") == "1")


@app.post("/ayarlar")
async def ayarlar_kaydet(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    form = await request.form()
    if not auth.csrf_ok(sid, form.get("csrf", "")):
        return PlainTextResponse("Geçersiz istek.", status_code=400)
    values = {k: str(form.get(k, "")).strip()[:20000] for k in db.DEFAULT_SETTINGS if k in form}
    db.save_settings(values)
    jobs.start()  # takvim değiştiyse yeniden kur
    return RedirectResponse("/ayarlar?ok=1", status_code=303)
