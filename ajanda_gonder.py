#!/usr/bin/env python3
"""Claude'un ajanda kaydını EA sitesine (Railway) anında yazar.
Kullanım: ajanda_gonder.py <items|gorevler|plans> <kayit.json>
Anahtar Anahtar Zinciri'nde (servis: ea-api-token); ekrana yazdırılmaz."""
import json
import subprocess
import sys
import urllib.error
import urllib.request

SITE = "https://ea-sunucu-production.up.railway.app"


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("items", "gorevler", "plans"):
        sys.exit("Kullanım: ajanda_gonder.py <items|gorevler|plans> <kayit.json>")
    col, path = sys.argv[1], sys.argv[2]
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    doc = doc.get("data", doc) if isinstance(doc.get("data"), dict) else doc
    doc_id = doc.get("id") or ""
    token = subprocess.run(["security", "find-generic-password", "-s", "ea-api-token", "-w"],
                           capture_output=True, text=True).stdout.strip()
    if not token:
        sys.exit("HATA: Anahtar Zinciri'nde ea-api-token yok (kurulum: ea_token_kur.sh).")
    req = urllib.request.Request("%s/api/claude/%s/%s" % (SITE, col, doc_id), method="PUT",
                                 data=json.dumps(doc, ensure_ascii=False).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print("EA ajandasına yazıldı:", col, doc_id, "(HTTP %d)" % r.status)
    except urllib.error.HTTPError as e:
        sys.exit("HATA: EA sitesi HTTP %d döndü: %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))
    except urllib.error.URLError as e:
        sys.exit("HATA: EA sitesine ulaşılamadı: %s" % e.reason)


if __name__ == "__main__":
    main()
