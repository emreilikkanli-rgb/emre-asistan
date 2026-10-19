"""Exchange Web Services (EWS) üzerinden gelen kutusunu SADECE OKUR.

Yalnızca FindItem ve GetItem çağrıları yapılır: hiçbir mail okundu işaretlenmez,
taşınmaz ya da silinmez.
"""
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from xml.sax.saxutils import escape

import requests
from requests_ntlm import HttpNtlmAuth

NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "t": "http://schemas.microsoft.com/exchange/services/2006/types",
    "m": "http://schemas.microsoft.com/exchange/services/2006/messages",
}

_ENVELOPE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">
 <soap:Header><t:RequestServerVersion Version="Exchange2016"/></soap:Header>
 <soap:Body>{body}</soap:Body>
</soap:Envelope>"""

_FIND = """<m:FindItem Traversal="Shallow">
   <m:ItemShape>
    <t:BaseShape>IdOnly</t:BaseShape>
    <t:AdditionalProperties>
     <t:FieldURI FieldURI="item:Subject"/>
     <t:FieldURI FieldURI="message:From"/>
     <t:FieldURI FieldURI="item:DisplayTo"/>
     <t:FieldURI FieldURI="item:DisplayCc"/>
     <t:FieldURI FieldURI="item:DateTimeReceived"/>
     <t:FieldURI FieldURI="message:IsRead"/>
     <t:FieldURI FieldURI="item:Importance"/>
     <t:FieldURI FieldURI="item:HasAttachments"/>
     <t:FieldURI FieldURI="item:Preview"/>
    </t:AdditionalProperties>
   </m:ItemShape>
   <m:IndexedPageItemView MaxEntriesReturned="{page}" Offset="{offset}" BasePoint="Beginning"/>
   <m:Restriction>
    <t:IsGreaterThanOrEqualTo>
     <t:FieldURI FieldURI="item:DateTimeReceived"/>
     <t:FieldURIOrConstant><t:Constant Value="{since}"/></t:FieldURIOrConstant>
    </t:IsGreaterThanOrEqualTo>
   </m:Restriction>
   <m:SortOrder>
    <t:FieldOrder Order="Descending"><t:FieldURI FieldURI="item:DateTimeReceived"/></t:FieldOrder>
   </m:SortOrder>
   <m:ParentFolderIds><t:DistinguishedFolderId Id="inbox"/></m:ParentFolderIds>
  </m:FindItem>"""

_GET = """<m:GetItem>
   <m:ItemShape><t:BaseShape>IdOnly</t:BaseShape><t:BodyType>Text</t:BodyType>
    <t:AdditionalProperties><t:FieldURI FieldURI="item:Body"/></t:AdditionalProperties>
   </m:ItemShape>
   <m:ItemIds>{ids}</m:ItemIds>
  </m:GetItem>"""


class EwsError(Exception):
    pass


class Ews:
    def __init__(self, host, user, password):
        if not (host and user and password):
            raise EwsError("EWS_HOST, EWS_USER ve EWS_PASSWORD ayarlanmamış.")
        self.host = host
        self.user = user
        self.url = "https://%s/EWS/Exchange.asmx" % host
        self.session = requests.Session()
        self.session.auth = HttpNtlmAuth(user, password)
        self.session.headers["Content-Type"] = "text/xml; charset=utf-8"

    def _call(self, body):
        data = _ENVELOPE.format(body=body).encode("utf-8")
        last = None
        for attempt in range(3):  # geçici ağ/SSL hatalarında 3 kez dener
            try:
                r = self.session.post(self.url, data=data, timeout=120)
            except requests.RequestException as e:
                last = EwsError("Exchange'e bağlanılamadı: %s" % e.__class__.__name__)
            else:
                if r.status_code == 401:
                    raise EwsError("Giriş başarısız (HTTP 401): şifre ya da kullanıcı adı hatalı.")
                if r.status_code != 200:
                    last = EwsError("Exchange hatası (HTTP %d)" % r.status_code)
                else:
                    root = ET.fromstring(r.content)
                    for msg in root.iter("{%s}ResponseMessages" % NS["m"]):
                        for rm in msg:
                            if rm.get("ResponseClass") == "Error":
                                txt = rm.findtext("m:MessageText", default="", namespaces=NS)
                                raise EwsError("Exchange hatası: %s" % txt)
                    return root
            time.sleep(5 * (attempt + 1))
        raise last

    def find_messages(self, hours, max_items=4000):
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out, total, offset = [], 0, 0
        while offset < max_items:
            root = self._call(_FIND.format(page=500, offset=offset, since=since))
            view = root.find(".//m:RootFolder", NS)
            if view is not None:
                total = int(view.get("TotalItemsInView") or 0)
            for msg in root.iter("{%s}Message" % NS["t"]):
                out.append(_parse_message(msg))
            if view is None or view.get("IncludesLastItemInRange") == "true":
                break
            offset += 500
        return out, (total or len(out))

    def get_bodies(self, ids, limit=80):
        bodies = {}
        ids = [i for i in ids if i][:limit]
        for k in range(0, len(ids), 40):
            chunk = "".join('<t:ItemId Id="%s"/>' % escape(i, {'"': "&quot;"}) for i in ids[k:k + 40])
            root = self._call(_GET.format(ids=chunk))
            for msg in root.iter("{%s}Message" % NS["t"]):
                iid = msg.find("t:ItemId", NS)
                body = msg.findtext("t:Body", default="", namespaces=NS)
                if iid is not None:
                    bodies[iid.get("Id")] = body
        return bodies

    def owa_link(self, item_id):
        return "https://%s/owa/?ItemID=%s&exvsurl=1&viewmodel=ReadMessageItem" % (self.host, quote(item_id, safe=""))


def _parse_message(msg):
    t = lambda name: msg.findtext("t:%s" % name, default="", namespaces=NS)
    frm = msg.find("t:From/t:Mailbox", NS)
    iid = msg.find("t:ItemId", NS)
    return {
        "id": iid.get("Id") if iid is not None else "",
        "subject": t("Subject"),
        "from_name": frm.findtext("t:Name", default="", namespaces=NS) if frm is not None else "",
        "from_addr": frm.findtext("t:EmailAddress", default="", namespaces=NS) if frm is not None else "",
        "to": t("DisplayTo"),
        "cc": t("DisplayCc"),
        "received": t("DateTimeReceived"),
        "is_read": t("IsRead") == "true",
        "importance": t("Importance"),
        "has_attachments": t("HasAttachments") == "true",
        "preview": " ".join(t("Preview").split()),
    }
