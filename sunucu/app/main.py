"""Emre'nin Asistanı: mail raporları web uygulaması (Railway)."""
import logging
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import ajanda as ajanda_mod, auth, db, jobs

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
templates.env.globals["totp_enabled"] = auth.totp_enabled


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
        return templates.TemplateResponse(request, "giris.html", {"hata": "Sunucu henüz kurulmadı: APP_PASSWORD_HASH ve SESSION_SECRET değişkenlerini Railway'de tanımlayın.", "kapali": True})
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
        return templates.TemplateResponse(request, "giris.html", {"hata": "Şifre ya da doğrulama kodu hatalı." if auth.totp_enabled() else "Şifre hatalı."}, status_code=401)
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
    simdi = datetime.now(TZ)
    return _page(request, "ana.html", sid, r=db.get_report(), gun=ajanda_mod.today_summary(), yaklasan=ajanda_mod.upcoming(3),
                 simdi="%d %s %d, %s" % (simdi.day, AYLAR[simdi.month - 1], simdi.year, GUNLER[simdi.weekday()]))


@app.get("/mailler", response_class=HTMLResponse)
def mailler(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    return _page(request, "rapor.html", sid, r=db.get_report(), son=db.list_reports(1), gun=ajanda_mod.today_summary())


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


# ---------- Ajanda ----------
import json as _json
import re as _re

from fastapi.responses import Response

_APP_DIR = os.path.dirname(__file__)
_ID_RE = _re.compile(r"^[A-Za-z0-9_\-.~:@+]{1,200}$")
_MAX_DOC = 256 * 1024


def _ajanda_html():
    with open(os.path.join(_APP_DIR, "ajanda.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/ajanda", response_class=HTMLResponse)
def ajanda(request: Request):
    sid, redir = _guard(request)
    if redir:
        return redir
    head = ('<!doctype html><html lang="tr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="robots" content="noindex, nofollow"><meta name="csrf" content="%s">'
            '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
            'body{margin:0;font:14px system-ui,-apple-system,sans-serif}[hidden]{display:none!important}'
            '.ea-menu{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;justify-content:space-between;max-width:1240px;margin:0 auto;'
            'padding:14px 16px 0;font:500 14px system-ui,-apple-system,sans-serif}'
            '.ea-menu a{color:#5b6678;text-decoration:none;padding:6px 10px;border-radius:8px}'
            '.ea-menu a:hover,.ea-menu a.on{background:#e9edf3;color:#17202e}'
            '.ea-marka{display:flex;align-items:center;gap:10px;font-weight:700;color:#17202e!important;padding-left:0!important;background:none!important}'
            '.ea-marka i{font-style:normal;width:30px;height:30px;border-radius:8px;background:#1f5fa8;color:#fff;display:grid;place-items:center;font-size:13px}'
            '.ea-menu span{display:flex;flex-wrap:wrap;gap:4px}'
            '@media (prefers-color-scheme:dark){.ea-menu a{color:#9aa6b8}.ea-menu a:hover,.ea-menu a.on{background:#212b38;color:#e7ebf2}.ea-marka{color:#e7ebf2!important}}'
            '</style>'
            '<script src="/ajanda/kopru.js"></script></head><body>') % auth.csrf_token(sid)
    menu = ('<nav class="ea-menu"><a class="ea-marka" href="/"><i>EA</i>Emre\'nin Asistanı</a><span>'
            '<a class="on" href="/ajanda">Emre\'nin Ajandası</a><a href="/mailler">Emre\'nin Mailleri</a>'
            '<a href="/ayarlar">Ayarlar</a></span></nav>')
    return HTMLResponse(head + menu + _ajanda_html() + '</body></html>')


@app.get("/ajanda/kopru.js")
def ajanda_kopru(request: Request):
    sid, redir = _guard(request)
    if redir:
        return PlainTextResponse("", status_code=401)
    with open(os.path.join(_APP_DIR, "ajanda_kopru.js"), encoding="utf-8") as f:
        return Response(f.read(), media_type="application/javascript")


def _api_guard(request, write=False):
    sid = auth.current_session(request)
    if not sid:
        return None, PlainTextResponse("Oturum yok", status_code=401)
    if write and not auth.csrf_ok(sid, request.headers.get("x-csrf", "")):
        return None, PlainTextResponse("Geçersiz istek", status_code=400)
    return sid, None


def _check(col, doc_id=None):
    return col in db.DOC_COLLECTIONS and (doc_id is None or _ID_RE.match(doc_id))


@app.get("/api/db/{col}")
def api_list(request: Request, col: str):
    _, err = _api_guard(request)
    if err:
        return err
    if not _check(col):
        return PlainTextResponse("Bilinmeyen koleksiyon", status_code=404)
    return db.doc_list(col)


@app.get("/api/db/{col}/{doc_id}")
def api_get(request: Request, col: str, doc_id: str):
    _, err = _api_guard(request)
    if err:
        return err
    body = db.doc_get(col, doc_id) if _check(col, doc_id) else None
    return {"data": body} if body is not None else PlainTextResponse("Yok", status_code=404)


@app.put("/api/db/{col}/{doc_id}")
async def api_set(request: Request, col: str, doc_id: str):
    _, err = _api_guard(request, write=True)
    if err:
        return err
    if not _check(col, doc_id):
        return PlainTextResponse("Geçersiz yol", status_code=400)
    raw = await request.body()
    if len(raw) > _MAX_DOC:
        return PlainTextResponse("Kayıt çok büyük", status_code=413)
    try:
        body = _json.loads(raw)
    except ValueError:
        return PlainTextResponse("Geçersiz JSON", status_code=400)
    if not isinstance(body, dict):
        return PlainTextResponse("Kayıt bir nesne olmalı", status_code=400)
    db.doc_set(col, doc_id, body)
    return Response(status_code=204)


@app.delete("/api/db/{col}/{doc_id}")
def api_delete(request: Request, col: str, doc_id: str):
    _, err = _api_guard(request, write=True)
    if err:
        return err
    if _check(col, doc_id):
        db.doc_delete(col, doc_id)
    return Response(status_code=204)


@app.post("/ayarlar/ice-aktar")
async def ice_aktar(request: Request):
    """claude.ai ajandasından alınan JSON yedeğini içe aktarır: {"items": [{"id", "data"}], ...}."""
    sid, redir = _guard(request)
    if redir:
        return redir
    form = await request.form()
    if not auth.csrf_ok(sid, form.get("csrf", "")):
        return PlainTextResponse("Geçersiz istek.", status_code=400)
    up = form.get("dosya")
    try:
        data = _json.loads((await up.read()).decode("utf-8")) if up else {}
    except (ValueError, AttributeError):
        return RedirectResponse("/ayarlar?aktar=hata", status_code=303)
    n = 0
    for col in ("items", "gorevler", "plans"):
        for row in data.get(col) or []:
            if isinstance(row, dict) and _check(col, str(row.get("id", ""))) and isinstance(row.get("data"), dict):
                db.doc_set(col, row["id"], row["data"])
                n += 1
    return RedirectResponse("/ayarlar?aktar=%d" % n, status_code=303)
