"""Görev maili gönderme: Exchange'de TEK yazma işlemi.

Yalnızca /api/gorev-mail ucundan, Emre Bey EA sitesinde oturum açıkken "Mail ile gönder"
düğmesine basıp onayladığında çağrılır. Zamanlayıcılar, mail okuma ve Claude'un anahtarlı
yazma ucu bu modülü kullanmaz. Gönderilen mail Gönderilmiş Öğeler'e kaydedilir.
"""
import re
from xml.sax.saxutils import escape

from .ews import Ews

MAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_CREATE = """<m:CreateItem MessageDisposition="SendAndSaveCopy">
   <m:SavedItemFolderId><t:DistinguishedFolderId Id="sentitems"/></m:SavedItemFolderId>
   <m:Items>
    <t:Message>
     <t:Subject>{subject}</t:Subject>
     <t:Body BodyType="HTML">{body}</t:Body>
     <t:ToRecipients><t:Mailbox><t:EmailAddress>{to}</t:EmailAddress></t:Mailbox></t:ToRecipients>
    </t:Message>
   </m:Items>
  </m:CreateItem>"""


def send(ews: Ews, to, subject, html):
    to = (to or "").strip()
    if not MAIL_RE.match(to):
        raise ValueError("Geçersiz mail adresi")
    ews._call(_CREATE.format(subject=escape(subject[:250]), body=escape(html), to=escape(to)))
