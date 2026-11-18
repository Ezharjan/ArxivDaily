"""Send the digest over SMTP.

Only two settings are required: ``SMTP_USERNAME`` (your email address) and
``SMTP_PASSWORD`` (an app password). The server, port and encryption are
detected from the address for common providers (Gmail, iCloud, Yahoo, QQ,
163, Zoho, Fastmail, ...) and can always be set explicitly:

  SMTP_HOST      server, e.g. smtp.gmail.com (auto-detected when possible)
  SMTP_PORT      465 or 587 (auto-detected; 465 implies SSL)
  SMTP_SECURITY  starttls | ssl | none (auto-detected from the port)
  SMTP_FROM      From address (defaults to SMTP_USERNAME)

Each recipient gets their own copy, so nobody sees the other addresses.
"""

from __future__ import annotations

import logging
import os
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import List, Sequence, Tuple

from . import __version__

log = logging.getLogger(__name__)

_GMX_HINT = ("your GMX password (or an app-specific password, if you use two-factor authentication), "
             "with POP3/IMAP access turned on in GMX's settings")

# domain -> (host, port, security, password hint)
PRESETS = {
    "gmail.com": ("smtp.gmail.com", 587, "starttls", "a Google App Password"),
    "googlemail.com": ("smtp.gmail.com", 587, "starttls", "a Google App Password"),
    "icloud.com": ("smtp.mail.me.com", 587, "starttls", "an Apple app-specific password"),
    "me.com": ("smtp.mail.me.com", 587, "starttls", "an Apple app-specific password"),
    "mac.com": ("smtp.mail.me.com", 587, "starttls", "an Apple app-specific password"),
    "yahoo.com": ("smtp.mail.yahoo.com", 465, "ssl", "a Yahoo app password"),
    "aol.com": ("smtp.aol.com", 465, "ssl", "an AOL app password"),
    "qq.com": ("smtp.qq.com", 465, "ssl", "the QQ Mail authorization code (授权码)"),
    "foxmail.com": ("smtp.qq.com", 465, "ssl", "the QQ Mail authorization code (授权码)"),
    "163.com": ("smtp.163.com", 465, "ssl", "the 163 Mail authorization code (授权码)"),
    "126.com": ("smtp.126.com", 465, "ssl", "the 126 Mail authorization code (授权码)"),
    "yeah.net": ("smtp.yeah.net", 465, "ssl", "the Yeah.net authorization code (授权码)"),
    "zoho.com": ("smtp.zoho.com", 465, "ssl", "a Zoho app-specific password"),
    "zoho.eu": ("smtp.zoho.eu", 465, "ssl", "a Zoho app-specific password"),
    "fastmail.com": ("smtp.fastmail.com", 465, "ssl", "a Fastmail app password"),
    "fastmail.fm": ("smtp.fastmail.com", 465, "ssl", "a Fastmail app password"),
    "gmx.com": ("mail.gmx.com", 587, "starttls", _GMX_HINT),
    "gmx.net": ("mail.gmx.net", 587, "starttls", _GMX_HINT),
    "gmx.de": ("mail.gmx.net", 587, "starttls", _GMX_HINT),
    "yandex.com": ("smtp.yandex.com", 465, "ssl", "a Yandex app password"),
    "yandex.ru": ("smtp.yandex.ru", 465, "ssl", "a Yandex app password"),
}
MICROSOFT_DOMAINS = {"outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.de", "hotmail.co.uk"}
OUTLOOK_NOTE = ("Microsoft no longer accepts passwords or app passwords for SMTP on Outlook.com/Hotmail "
                "accounts (basic authentication was switched off in September 2024), so ArxivDaily can't "
                "send from them. Use another address to send, e.g. a Gmail account, and keep receiving "
                "at your Outlook address via the MAIL_TO secret.")


class SetupError(Exception):
    """Something the user has to change in their settings (shown without a traceback)."""


@dataclass
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_address: str
    security: str           # starttls | ssl | none
    detected: bool = False  # host/port came from PRESETS
    password_hint: str = ""

    def describe(self) -> str:
        sec = {"starttls": "STARTTLS", "ssl": "SSL", "none": "no encryption"}[self.security]
        return f"{self.host}:{self.port} ({sec})" + (", detected automatically" if self.detected else "")

    @classmethod
    def from_env(cls, default_from: str = "") -> "SmtpConfig":
        user = os.environ.get("SMTP_USERNAME", "").strip()
        password = os.environ.get("SMTP_PASSWORD", "").strip()
        missing = [name for name, value in (("SMTP_USERNAME", user), ("SMTP_PASSWORD", password)) if not value]
        if missing:
            raise SetupError(
                "Email isn't set up yet: missing " + " and ".join(missing) + ". On GitHub, add them under "
                "Settings > Secrets and variables > Actions > New repository secret; on your own computer, "
                "put them in a .env file (copy .env.example). SMTP_USERNAME is your full email address and "
                "SMTP_PASSWORD an app password (see docs/setup-guide.md).")
        domain = user.rsplit("@", 1)[-1].lower() if "@" in user else ""
        preset = PRESETS.get(domain)
        host = os.environ.get("SMTP_HOST", "").strip()
        if not host and domain in MICROSOFT_DOMAINS:
            raise SetupError(OUTLOOK_NOTE)
        if not host and not preset:
            raise SetupError(
                f"Can't tell which mail server to use for {'@' + domain if domain else user!r}. "
                "Add an SMTP_HOST secret with your provider's SMTP server (for example smtp.example.com) "
                "and, if needed, SMTP_PORT.")
        detected = not host
        host = host or preset[0]
        port_raw = os.environ.get("SMTP_PORT", "").strip()
        if port_raw:
            if not port_raw.isdigit():
                raise SetupError(f"SMTP_PORT must be a number like 465 or 587 (got {port_raw!r}).")
            port = int(port_raw)
        else:
            port = preset[1] if (preset and detected) else 587
        security = os.environ.get("SMTP_SECURITY", "").strip().lower()
        if not security:
            security = "ssl" if port == 465 else "starttls"
        if security not in ("starttls", "ssl", "none"):
            raise SetupError(f"SMTP_SECURITY must be starttls, ssl or none (got {security!r}).")
        if domain in ("gmail.com", "googlemail.com"):
            password = password.replace(" ", "")     # Google shows app passwords as "abcd efgh ijkl mnop"
        from_addr = (os.environ.get("SMTP_FROM", "").strip() or default_from or user).strip()
        hint = preset[3] if preset else ""
        return cls(host, port, user, password, from_addr, security, detected, hint)


def _msgid_domain(from_address: str) -> str:
    """Pick a safe domain for the Message-ID header (fallback: arxivdaily.local)."""
    if "@" in from_address:
        domain = from_address.rsplit("@", 1)[1].strip()
        if domain:
            return domain
    return "arxivdaily.local"


def build_message(*, subject: str, html: str, text: str, from_name: str, from_address: str,
                  to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_address))
    msg["To"] = to
    msg["Date"] = formatdate(usegmt=True)
    msg["Message-ID"] = make_msgid(domain=_msgid_domain(from_address))
    msg["Auto-Submitted"] = "auto-generated"     # tells vacation responders not to reply
    msg["X-Mailer"] = f"ArxivDaily/{__version__}"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def _explain(err: Exception, smtp: SmtpConfig) -> str:
    where = f"{smtp.host}:{smtp.port}"
    if isinstance(err, smtplib.SMTPAuthenticationError):
        detail = (err.smtp_error or b"").decode("utf-8", "replace")
        if "basic authentication is disabled" in detail.lower() or "5.7.139" in detail:
            return OUTLOOK_NOTE
        if "5.7.30" in detail or "basic authentication is not supported" in detail.lower():
            return (f"{smtp.host} no longer accepts passwords for sending (Microsoft 365 is switching off "
                    "password-based SMTP for work and university accounts). Send from another address, e.g. a "
                    "Gmail account, and keep receiving at this one via the MAIL_TO secret.")
        hint = smtp.password_hint
        if not hint:
            password = ("SMTP_PASSWORD must be the password for SMTP access, which many providers issue "
                        "separately as an \"app password\"")
        elif hint.startswith("your "):            # GMX accepts the normal password
            password = f"SMTP_PASSWORD must be {hint}"
        else:
            password = f"SMTP_PASSWORD must be {hint}, not your normal login password"
        how = ("Turn on 2-Step Verification, then create an app password at "
               "https://myaccount.google.com/apppasswords" if smtp.host == "smtp.gmail.com" else
               "Step 2 of docs/setup-guide.md shows how to get it")
        return (f"{smtp.host} rejected the username or password ({err.smtp_code}). SMTP_USERNAME must be the "
                f"full email address and {password}. {how}.")
    if isinstance(err, ssl.SSLError):
        return (f"Encryption handshake with {where} failed ({err.reason or err}). Port 465 needs "
                "SMTP_SECURITY=ssl and port 587 needs starttls; remove SMTP_SECURITY to auto-detect.")
    if isinstance(err, smtplib.SMTPNotSupportedError):
        return f"{where} doesn't support STARTTLS. Try SMTP_PORT=465 (SSL)."
    if isinstance(err, smtplib.SMTPSenderRefused):
        return (f"{smtp.host} refused the From address. Most providers only let you send as your own "
                "address: remove SMTP_FROM / email.from_address or set it to your account's address.")
    if isinstance(err, socket.gaierror):
        return f"Can't find the mail server {smtp.host!r}. Check SMTP_HOST for typos."
    if isinstance(err, smtplib.SMTPResponseException) and not isinstance(err, smtplib.SMTPConnectError):
        detail = err.smtp_error.decode("utf-8", "replace") if isinstance(err.smtp_error, bytes) else str(err.smtp_error)
        return (f"{smtp.host} didn't accept the message ({err.smtp_code} {' '.join(detail.split())}). "
                "This is usually the provider's spam filter or a sending limit.")
    if isinstance(err, OSError):              # timeouts, refused connections, hang-ups (smtplib errors included)
        return (f"Couldn't connect to {where} ({err.__class__.__name__}: {err}). Check SMTP_HOST and "
                "SMTP_PORT (usually 465 or 587).")
    return f"Sending through {where} failed: {err}"


def _connect(smtp: SmtpConfig) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if smtp.security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(smtp.host, smtp.port, context=context, timeout=30)
    else:
        server = smtplib.SMTP(smtp.host, smtp.port, timeout=30)
    try:
        if smtp.security != "ssl":
            server.ehlo()
            if smtp.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
        server.login(smtp.username, smtp.password)
    except Exception:
        server.close()
        raise
    return server


def verify_login(smtp: SmtpConfig) -> None:
    """Log in and out without sending anything (used by --check)."""
    try:
        server = _connect(smtp)
        server.quit()
    except Exception as e:  # noqa: BLE001
        raise SetupError(_explain(e, smtp)) from None


def send_all(*, recipients: Sequence[str], subject: str, html: str, text: str, from_name: str,
             smtp: SmtpConfig) -> Tuple[List[str], List[str]]:
    """Send one copy per recipient over a single connection.

    Returns (delivered, failed). Raises SetupError if nothing could be sent.
    """
    log.info("connecting to %s", smtp.describe())
    try:
        server = _connect(smtp)
    except Exception as e:  # noqa: BLE001
        raise SetupError(_explain(e, smtp)) from None
    delivered: List[str] = []
    failed: List[str] = []
    first_error = None
    try:
        for to in recipients:
            msg = build_message(subject=subject, html=html, text=text, from_name=from_name,
                                from_address=smtp.from_address, to=to)
            for attempt in (1, 2):
                try:
                    server.send_message(msg, from_addr=smtp.from_address, to_addrs=[to])
                    delivered.append(to)
                except smtplib.SMTPServerDisconnected as e:
                    if attempt == 1:                  # the server hung up: reconnect once and retry
                        try:
                            server = _connect(smtp)
                            continue
                        except Exception as reconnect_error:  # noqa: BLE001
                            e = reconnect_error
                    failed.append(to)
                    first_error = first_error or e
                except smtplib.SMTPSenderRefused as e:
                    if not delivered:                 # same answer for everyone: stop right away
                        raise SetupError(_explain(e, smtp)) from None
                    failed.append(to)
                    first_error = first_error or e
                except smtplib.SMTPRecipientsRefused:
                    failed.append(to)
                except (smtplib.SMTPException, OSError) as e:
                    failed.append(to)
                    first_error = first_error or e
                break
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass
    if not delivered:
        if first_error is not None:
            raise SetupError(_explain(first_error, smtp))
        whom = "the recipient address" if len(recipients) == 1 else f"all {len(recipients)} recipient addresses"
        raise SetupError(f"{smtp.host} refused {whom}. Check the MAIL_TO secret for typos.")
    log.info("sent to %d of %d recipients", len(delivered), len(recipients))
    return delivered, failed
