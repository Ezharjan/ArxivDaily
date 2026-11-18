"""Test helpers: a tiny SMTP server and canned arXiv responses (no network needed)."""

from __future__ import annotations

import base64
import os
import re
import socketserver
import sys
import threading
from contextlib import contextmanager
from email import message_from_bytes, policy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")
if ROOT not in sys.path:          # make `import main` / `from src import ...` work from anywhere
    sys.path.insert(0, ROOT)

import logging  # noqa: E402

logging.getLogger("src").setLevel(logging.ERROR)    # keep test output readable
logging.getLogger("arxivdaily").setLevel(logging.WARNING)


def fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


class _SMTPHandler(socketserver.StreamRequestHandler):
    def _send(self, line: str) -> None:
        self.wfile.write(line.encode() + b"\r\n")

    def handle(self):  # noqa: C901 - a deliberately flat state machine
        srv = self.server
        self._send("220 fake.smtp ESMTP ready")
        mail_from, rcpts, buf, in_data = None, [], [], False
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            if in_data:
                if raw in (b".\r\n", b".\n"):
                    if srv.reject_data & set(rcpts):
                        self._send("554 5.7.1 Message rejected as spam")
                    else:
                        srv.messages.append({"from": mail_from, "to": list(rcpts), "raw": b"".join(buf)})
                        self._send("250 2.0.0 queued")
                    mail_from, rcpts, buf, in_data = None, [], [], False
                else:
                    buf.append(raw[1:] if raw.startswith(b"..") else raw)
                continue
            cmd = raw.decode("utf-8", "replace").strip()
            up = cmd.upper()
            if up.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-fake.smtp\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
            elif up.startswith("AUTH PLAIN"):
                parts = cmd.split()
                token = parts[2] if len(parts) > 2 else None
                if token is None:
                    self._send("334 ")
                    token = self.rfile.readline().decode().strip()
                _, user, password = base64.b64decode(token).split(b"\0")
                ok = (user.decode(), password.decode()) == (srv.user, srv.password)
                srv.logins += 1
                self._send("235 2.7.0 Authentication successful" if ok
                           else "535 5.7.8 Username and Password not accepted")
            elif up.startswith("MAIL FROM:"):
                mail_from = cmd[10:].strip().strip("<>")
                self._send("250 2.1.0 OK")
            elif up.startswith("RCPT TO:"):
                addr = cmd[8:].strip().strip("<>")
                if addr in srv.refuse:
                    self._send("550 5.1.1 No such user")
                else:
                    rcpts.append(addr)
                    self._send("250 2.1.5 OK")
            elif up == "DATA":
                in_data = True
                self._send("354 Go ahead")
            elif up in ("RSET", "NOOP"):
                rcpts = [] if up == "RSET" else rcpts
                self._send("250 OK")
            elif up == "QUIT":
                self._send("221 Bye")
                return
            else:
                self._send("502 5.5.2 Command not recognized")


class FakeSMTPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, user="ada@example.org", password="app-password", refuse=(), reject_data=()):
        super().__init__(("127.0.0.1", 0), _SMTPHandler)
        self.user, self.password, self.refuse = user, password, set(refuse)
        self.reject_data = set(reject_data)       # accept RCPT, then refuse the message itself
        self.messages = []
        self.logins = 0

    @property
    def port(self) -> int:
        return self.server_address[1]

    def parsed(self, i: int = -1):
        return message_from_bytes(self.messages[i]["raw"], policy=policy.default)


@contextmanager
def smtp_server(**kw):
    srv = FakeSMTPServer(**kw)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


@contextmanager
def env(**values):
    """Temporarily set (or with None, remove) environment variables."""
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def smtp_env(srv: FakeSMTPServer, **extra):
    values = dict(SMTP_HOST="127.0.0.1", SMTP_PORT=str(srv.port), SMTP_SECURITY="none",
                  SMTP_USERNAME=srv.user, SMTP_PASSWORD=srv.password, SMTP_FROM=None, MAIL_TO=None)
    values.update(extra)
    return env(**values)


def combine_rss(*feeds: bytes) -> bytes:
    """Merge several arXiv RSS documents into one (like rss.arxiv.org/rss/a+b)."""
    head, items, seen = None, [], set()
    for feed in feeds:
        text = feed.decode("utf-8")
        start = text.find("<item>")
        if head is None:
            head = text[:start] if start != -1 else text[: text.index("</channel>")]
        for m in re.finditer(r"<item>.*?</item>", text, re.S):
            link = re.search(r"<link>(.*?)</link>", m.group(0)).group(1)
            if link not in seen:
                seen.add(link)
                items.append(m.group(0))
    return (head + "\n".join(items) + "\n  </channel>\n</rss>\n").encode("utf-8")


def api_feed(entries) -> bytes:
    """Build an arXiv API (Atom) response. entries: dicts with id, title, summary,
    published (datetime), cats (list, first = primary), authors (list), version."""
    from xml.sax.saxutils import escape as x
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<feed xmlns="http://www.w3.org/2005/Atom">',
             '<title type="html">ArXiv Query</title><id>http://arxiv.org/api/test</id>',
             f'<opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">{len(entries)}'
             '</opensearch:totalResults>']
    for e in entries:
        v = e.get("version", 1)
        stamp = e["published"].strftime("%Y-%m-%dT%H:%M:%SZ")
        updated = e.get("updated", e["published"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        cats = e.get("cats", ["cs.LG"])
        parts.append(
            f'<entry><id>http://arxiv.org/abs/{e["id"]}v{v}</id><updated>{updated}</updated>'
            f'<published>{stamp}</published><title>{x(e["title"])}</title>'
            f'<summary>  {x(e.get("summary", ""))}\n</summary>'
            + "".join(f"<author><name>{x(a)}</name></author>" for a in e.get("authors", ["A. Author"]))
            + f'<link href="http://arxiv.org/abs/{e["id"]}v{v}" rel="alternate" type="text/html"/>'
            f'<link title="pdf" href="http://arxiv.org/pdf/{e["id"]}v{v}" rel="related" type="application/pdf"/>'
            f'<arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="{cats[0]}" '
            'scheme="http://arxiv.org/schemas/atom"/>'
            + "".join(f'<category term="{c}" scheme="http://arxiv.org/schemas/atom"/>' for c in cats)
            + "</entry>")
    parts.append("</feed>")
    return "\n".join(parts).encode("utf-8")
