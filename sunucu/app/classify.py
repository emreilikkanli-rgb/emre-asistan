"""Mailleri bölümlere ayırır: şikâyet, ödeme/giriş riski, öncelikli kişiler,
size doğrudan ilgili, ortak maillerde tartışma ve uzayan yazışmalar."""
import re
from collections import Counter, defaultdict

_TR = str.maketrans("ıİçğöşüâîÇĞÖŞÜÂÎ", "iicgosuaicgosuai")


def norm(s):
    """Türkçe büyük/küçük harf ve noktalı/noktasız i farkını yok sayarak karşılaştırma için."""
    s = (s or "").lower().translate(_TR).replace("̇", "")
    return re.sub(r"[^a-z0-9@.]+", " ", s)


def words(text):
    return [w for w in (norm(x).strip() for x in re.split(r"[;\n]", text or "")) if w]


def _hits(text, ws):
    return [w for w in ws if re.search(r"\b" + re.escape(w), text)]


def parse_vips(text):
    vips = []
    for raw in [x.strip() for x in re.split(r"[;\n]", text or "") if x.strip()]:
        toks = norm(raw).split()
        names = [t for t in toks if not t.startswith("@")]
        domain = next((t[1:] for t in toks if t.startswith("@")), None)
        vips.append({"label": raw, "names": names, "domain": domain})
    return vips


def _vip_hits(vips, people):
    hit = set()
    for v in vips:
        for p in (norm(x) for x in people):
            if any(not re.search(r"\b" + re.escape(n) + r"\b", p) for n in v["names"]):
                continue
            if v["domain"] and not re.search(r"@[a-z0-9.]*" + re.escape(v["domain"]), p):
                continue
            hit.add(v["label"])
    return sorted(hit)


_PREFIX = re.compile(r"^\s*(re|fw|fwd|ynt|yanit|yanıt|ilt|ilet|iletildi|aw|wg|tr)\s*:\s*", re.I)


def thread_key(subject):
    s = subject or ""
    while _PREFIX.match(s):
        s = _PREFIX.sub("", s, count=1)
    return norm(s).strip()


SECTIONS = [
    ("sikayet", "ŞİKÂYET ŞÜPHESİ"),
    ("odeme", "ÖDEME TALEBİ / GİRİŞ RİSKİ"),
    ("vip", "ÖNCELİKLİ KİŞİLER"),
    ("mine", "SİZE DOĞRUDAN İLGİLİ"),
    ("ortak", "ORTAK MAİLLERDE TARTIŞMA İŞARETİ"),
]


def classify(msgs, cfg):
    """cfg: user, name, oncelikli, sikayet_kelimeleri, odeme_kelimeleri,
    tartisma_kelimeleri, rehber_kelimeleri, rehber_olumsuz (metin)."""
    me = norm(cfg.get("name", "")).strip()
    parts = me.split()
    first, last = (parts + ["", ""])[:2]
    email = norm(cfg.get("user", "")).strip()
    own_domain = email.split("@")[-1] if "@" in email else ""
    vips = parse_vips(cfg.get("oncelikli", ""))
    w_comp = words(cfg.get("sikayet_kelimeleri", ""))
    w_pay = words(cfg.get("odeme_kelimeleri", ""))
    w_disp = words(cfg.get("tartisma_kelimeleri", ""))
    w_guide = words(cfg.get("rehber_kelimeleri", ""))
    w_guide_neg = words(cfg.get("rehber_olumsuz", ""))

    sections = defaultdict(list)
    seen = {}
    others = Counter()
    threads = defaultdict(list)

    for m in msgs:
        if norm(m["from_addr"]).strip() == email:
            continue  # kendi gönderdikleriniz
        to, cc, subj, prev = m["to"], m["cc"], m["subject"], m["preview"]
        rcpt = norm(to + " " + cc)
        other_same_first = bool(first) and re.search(
            r"\b" + re.escape(first) + r" (?!" + re.escape(last) + r"\b)[a-z]", rcpt) is not None
        why = []
        if me and me in norm(to):
            why.append("Kime: size")
        if me and me in norm(cc):
            why.append("CC: size")
        if first and not other_same_first and re.search(r"\b" + re.escape(first) + r" (bey|b\b|beyin|beye)", norm(prev)):
            why.append("içerikte '%s bey' geçiyor" % first.capitalize())
        quoted = re.findall(r"([^:;<>'\"]{2,60}?\s*<[^<>\s]+@[^<>\s]+>)", prev)
        vip = _vip_hits(vips, ["%s <%s>" % (m["from_name"], m["from_addr"])] + (to + ";" + cc).split(";") + quoted)
        ntext = norm(subj + " " + prev)
        comp = _hits(ntext, w_comp)
        if _hits(ntext, w_guide) and _hits(ntext, w_guide_neg):
            comp.append("rehber şikâyeti")
        pay = _hits(ntext, w_pay)
        disp = _hits(ntext, w_disp)

        sec = "sikayet" if comp else "odeme" if pay else "vip" if vip else "mine" if why else "ortak" if disp else None
        if sec is None:
            others[to or "(boş)"] += 1
            k = thread_key(subj)
            if k:
                threads[k].append(m)
            continue
        if vip:
            why.append("öncelikli kişi: " + ", ".join(vip))
        if comp:
            why.append("şikâyet: " + ", ".join(comp))
        if pay:
            why.append("ödeme / giriş riski: " + ", ".join(pay))
        if disp:
            why.append("tartışma işareti: " + ", ".join(disp))
        key = norm("%s|%s|%s" % (m["from_addr"], subj, prev[:120]))
        if key in seen:
            seen[key]["dupes"] += 1
            continue
        entry = dict(m, section=sec, why=why, vips=vip, dupes=0)
        seen[key] = entry
        sections[sec].append(entry)

    busy = []
    for k, ms in threads.items():
        senders = {norm(x["from_addr"]).strip() for x in ms}
        if len(ms) >= 5 and len(senders) >= 3:
            external = any(not s.endswith(own_domain) for s in senders) if own_domain else True
            busy.append({"subject": ms[0]["subject"], "count": len(ms), "latest": ms[0], "first": ms[-1],
                         "people": list(dict.fromkeys(x["from_name"] for x in ms))[:8], "external": external})
    busy.sort(key=lambda b: -b["count"])
    return {"sections": sections, "busy": busy[:8], "others": others,
            "others_total": sum(others.values()), "vip_labels": [v["label"] for v in vips]}
