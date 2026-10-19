"""Telefona/tarayıcıya bildirim (Web Push). VAPID anahtarları yoksa sessizce atlanır."""
import json
import logging
import os

from . import db

log = logging.getLogger("ea.bildirim")

try:
    from pywebpush import WebPushException, webpush
except ImportError:  # paket kurulu değilse bildirim kapalı
    webpush = None


def etkin():
    return bool(webpush and os.environ.get("VAPID_PRIVATE_KEY") and os.environ.get("VAPID_PUBLIC_KEY"))


def gonder(metin, url="/ajanda"):
    """En az bir aboneliğe ulaştıysa True döner."""
    if not etkin():
        return False
    ok = False
    for sub in db.push_list():
        try:
            webpush(subscription_info=sub, data=json.dumps({"title": "Emre'nin Asistanı", "body": metin, "url": url}),
                    vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
                    vapid_claims={"sub": "mailto:" + (os.environ.get("VAPID_CONTACT") or "bildirim@example.com")}, ttl=3600)
            ok = True
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                db.push_remove(sub.get("endpoint", ""))
            log.warning("Bildirim gönderilemedi: %s", code)
    return ok
