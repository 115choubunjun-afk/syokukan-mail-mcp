from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import SMTP
import secrets
import smtplib
import ssl
from threading import Lock
from time import monotonic


SENDER = "1@syokukan.co.jp"
SMTP_HOST = "prvh1039.presinet.ne.jp"


@dataclass(frozen=True)
class Draft:
    to: str
    subject: str
    body: str


class Drafts:
    def __init__(self, deliver):
        self.deliver = deliver
        self.pending = {}
        self.lock = Lock()

    def create(self, to, subject, body):
        address = Address(addr_spec=to)
        if address.addr_spec != to or not address.domain or not to.isascii() or len(to) > 254:
            raise ValueError("Enter one complete email address.")
        if not subject.strip() or len(subject) > 250 or any(ord(c) < 32 for c in subject):
            raise ValueError("Enter a subject of up to 250 characters on one line.")
        if not body.strip() or len(body) > 20000:
            raise ValueError("Enter a message of up to 20,000 characters.")
        draft = Draft(to, subject, body)
        key = secrets.token_urlsafe(32)
        now = monotonic()
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if v[0] > now}
            if len(self.pending) >= 50:
                raise ValueError("Too many pending previews.")
            self.pending[key] = (now + 900, draft)
        return key, draft

    def view(self, key):
        with self.lock:
            expiry, draft = self.pending[key]
            if expiry <= monotonic():
                raise KeyError(key)
            return draft

    def confirm(self, key):
        with self.lock:
            expiry, draft = self.pending.pop(key)
            if expiry <= monotonic():
                raise KeyError(key)
        self.deliver(draft)


def deliver_smtp(draft, username, password):
    message = EmailMessage(policy=SMTP)
    message["From"] = SENDER
    message["To"] = draft.to
    message["Subject"] = draft.subject
    message.set_content(draft.body)
    with smtplib.SMTP(SMTP_HOST, 587, timeout=20) as client:
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
        client.login(username, password)
        client.send_message(message, from_addr=SENDER, to_addrs=[draft.to])
