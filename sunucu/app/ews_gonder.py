"""Görev maili gönderme: Exchange'de TEK yazma işlemi.

Yalnızca iki yerden, Emre Bey'in kendi isteğiyle çağrılır:
1) /api/gorev-mail: oturum açıkken "Mail ile gönder" düğmesine basıp onayladığında,
2) /sifremi-unuttum: şifre yenileme linki; yalnızca sabit kurtarma adresine (auth.KURTARMA_MAIL), sıklık sınırlı.
Zamanlayıcılar, mail okuma ve Claude'un anahtarlı yazma ucu bu modülü kullanmaz. Gönderilen mail Gönderilmiş Öğeler'e kaydedilir.
"""
import re
from xml.sax.saxutils import escape

from .ews import Ews

MAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
# Sık yapılan alan adı yazım hataları (ör. .con): bu adreslere gönderilmez.
MAIL_TYPO = re.compile(r"\.(con|cmo|ocm|comm|coom|vom|xom|cpm|co\.t|com\.t)$|@(gmial|gmal|gamil|hotmial|hotmal|outlok)\.", re.I)

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
    if MAIL_TYPO.search(to):
        raise ValueError("Adreste yazım hatası var gibi görünüyor (ör. .con yerine .com)")
    ews._call(_CREATE.format(subject=escape(subject[:250]), body=escape(html), to=escape(to)))
