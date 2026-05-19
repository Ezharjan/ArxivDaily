"""Compose and send the daily arXiv email.

Renders both an HTML body (one card per paper) and a plain-text fallback.
Transport is generic SMTP (host/port/user/password from env), so the same
code works with Gmail, Outlook, Fastmail, SES, Mailgun SMTP, etc.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from typing import List, Sequence

from .arxiv_fetcher import Paper

log = logging.getLogger(__name__)


_CSS = (
    " body { margin:0; padding:0; background:#f6f7f9;"
    " font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    " color:#1f2328; line-height:1.5; }"
    " .wrap { max-width:720px; margin:0 auto; padding:24px 16px; }"
    " .header { padding:8px 4px 20px; border-bottom:1px solid #e3e6ea; }"
    " .header h1 { margin:0; font-size:22px; font-weight:700; letter-spacing:-0.01em; }"
    " .header .meta { margin-top:4px; font-size:13px; color:#57606a; }"
    " .paper { background:#fff; border:1px solid #e3e6ea; border-radius:10px;"
    " padding:16px 18px; margin:14px 0; }"
    " .paper .title { font-size:16px; font-weight:600; line-height:1.35; margin:0 0 6px; }"
    " .paper .title a { color:#0969da; text-decoration:none; }"
    " .paper .authors { font-size:13px; color:#57606a; margin:0 0 8px; }"
    " .paper .badges { font-size:12px; color:#57606a; margin:0 0 10px; }"
    " .badge { display:inline-block; padding:2px 8px; margin-right:6px;"
    " background:#eef2f6; border-radius:999px; color:#324155; font-weight:500; }"
    " .badge.kw { background:#ddf4ff; color:#0550ae; }"
    " .badge.cat { background:#f1f5e9; color:#4a5d23; }"
    " .badge.score { background:#fff3cd; color:#6b4d00; }"
    " .paper .abstract { font-size:14px; color:#1f2328; margin:6px 0 10px; }"
    " .paper .links a { font-size:13px; color:#0969da; text-decoration:none; margin-right:14px; }"
    " .footer { text-align:center; font-size:12px; color:#8b949e; padding:18px 4px 8px; }"
    " .footer a { color:#8b949e; text-decoration:underline; }"
)


def _plural(n: int, singular: str, plural=None) -> str:
    return singular if n == 1 else (plural or singular + "s")


def _truncate(text: str, max_chars: int) -> str:
    text = " ".join((text or "").split())
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[: max_chars].rsplit(" ", 1)[0].rstrip(",;:.-")
    return f"{cut}…"


def _format_authors(authors: Sequence[str], max_show: int) -> str:
    if not authors:
        return ""
    if max_show <= 0 or len(authors) <= max_show:
        return ", ".join(authors)
    return ", ".join(authors[:max_show]) + f", et al. (+{len(authors) - max_show})"


def render_html(papers: Sequence[Paper], date_label: str, abstract_chars: int, max_authors: int) -> str:
    cards = []
    for i, p in enumerate(papers, start=1):
        authors_html = escape(_format_authors(p.authors, max_authors))
        abstract_html = escape(_truncate(p.summary, abstract_chars))
        kw_badges = "".join(
            f'<span class="badge kw">{escape(k)}</span>' for k in p.matched_keywords
        )
        cat_badge = f'<span class="badge cat">{escape(p.primary_category)}</span>'
        score_badge = f'<span class="badge score">score {p.score:g}</span>'
        updated = p.updated.strftime("%Y-%m-%d")
        cards.append(
            '<div class="paper">'
            f'<p class="title"><a href="{escape(p.abs_url)}">{i}. {escape(p.title)}</a></p>'
            f'<p class="authors">{authors_html}</p>'
            f'<p class="badges">{cat_badge}{kw_badges}{score_badge}'
            f'<span style="margin-left:6px;">{escape(updated)}</span></p>'
            f'<p class="abstract">{abstract_html}</p>'
            f'<p class="links">'
            f'<a href="{escape(p.abs_url)}">abs</a>'
            f'<a href="{escape(p.pdf_url)}">pdf</a>'
            f'<a href="https://arxiv.org/list/{escape(p.primary_category)}/recent">category</a>'
            f'</p></div>'
        )
    body = "\n".join(cards) if cards else "<p>No new matching papers.</p>"
    n = len(papers)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<style>{_CSS}</style></head><body>'
        f'<div class="wrap">'
        f'<div class="header"><h1>ArxivDaily &middot; {n} new {_plural(n, "paper")}</h1>'
        f'<div class="meta">Listing date: {escape(date_label)}</div></div>'
        f'{body}'
        f'<div class="footer">Curated automatically from the arXiv API. '
        f'<a href="https://arxiv.org/">arxiv.org</a></div>'
        f'</div></body></html>'
    )


def render_text(papers: Sequence[Paper], date_label: str, abstract_chars: int, max_authors: int) -> str:
    n = len(papers)
    lines = [f"ArxivDaily - {n} new {_plural(n, 'paper')} ({date_label})", "=" * 60, ""]
    for i, p in enumerate(papers, start=1):
        lines.append(f"{i}. {p.title}")
        authors = _format_authors(p.authors, max_authors)
        if authors:
            lines.append(f"   {authors}")
        kw = ", ".join(p.matched_keywords) if p.matched_keywords else "-"
        lines.append(
            f"   [{p.primary_category}] keywords: {kw}  score: {p.score:g}  "
            f"updated: {p.updated.strftime('%Y-%m-%d')}"
        )
        lines.append(f"   {_truncate(p.summary, abstract_chars)}")
        lines.append(f"   abs: {p.abs_url}")
        lines.append(f"   pdf: {p.pdf_url}")
        lines.append("")
    lines.append("--")
    lines.append("Curated automatically from the arXiv API (arxiv.org).")
    return "\n".join(lines)


class SmtpConfig:
    """Resolved SMTP settings, sourced from environment variables.

    Recognised env vars:
      SMTP_HOST      required
      SMTP_PORT      default 587
      SMTP_USERNAME  required
      SMTP_PASSWORD  required
      SMTP_FROM      optional; defaults to SMTP_USERNAME
      SMTP_SECURITY  one of: starttls (default), ssl, none
    """

    def __init__(self, host, port, username, password, from_address, security):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address
        self.security = security.lower()

    @classmethod
    def from_env(cls, default_from: str = "") -> "SmtpConfig":
        host = os.environ.get("SMTP_HOST", "").strip()
        port = int(os.environ.get("SMTP_PORT", "587").strip() or "587")
        user = os.environ.get("SMTP_USERNAME", "").strip()
        pw = os.environ.get("SMTP_PASSWORD", "")
        from_addr = (os.environ.get("SMTP_FROM") or default_from or user).strip()
        security = (os.environ.get("SMTP_SECURITY") or "starttls").strip().lower()
        missing = [
            k for k, v in {
                "SMTP_HOST": host,
                "SMTP_USERNAME": user,
                "SMTP_PASSWORD": pw,
            }.items() if not v
        ]
        if missing:
            raise RuntimeError(
                "Missing required SMTP environment variables: " + ", ".join(missing)
            )
        if security not in {"starttls", "ssl", "none"}:
            raise RuntimeError(f"SMTP_SECURITY must be starttls|ssl|none, got {security!r}")
        return cls(host, port, user, pw, from_addr, security)


def _msgid_domain(from_address: str) -> str:
    """Pick a safe domain for the Message-ID header.

    Falls back to ``arxivdaily.local`` if the address is missing or doesn't
    contain an ``@`` (otherwise the Message-ID would be malformed).
    """
    if "@" in from_address:
        domain = from_address.rsplit("@", 1)[1].strip()
        if domain:
            return domain
    return "arxivdaily.local"


def build_message(*, subject, html, text, from_name, from_address, recipients) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_address))
    msg["To"] = ", ".join(recipients)
    msg["Message-ID"] = make_msgid(domain=_msgid_domain(from_address))
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send(message: EmailMessage, recipients: Sequence[str], smtp: SmtpConfig) -> None:
    log.info("connecting to %s:%d (%s)", smtp.host, smtp.port, smtp.security)
    context = ssl.create_default_context()
    if smtp.security == "ssl":
        with smtplib.SMTP_SSL(smtp.host, smtp.port, context=context, timeout=30) as s:
            s.login(smtp.username, smtp.password)
            s.send_message(message, from_addr=smtp.from_address, to_addrs=list(recipients))
    else:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as s:
            s.ehlo()
            if smtp.security == "starttls":
                s.starttls(context=context)
                s.ehlo()
            s.login(smtp.username, smtp.password)
            s.send_message(message, from_addr=smtp.from_address, to_addrs=list(recipients))
    log.info("sent to %d recipient(s)", len(recipients))


def send_digest(
    papers: List[Paper],
    *,
    recipients: Sequence[str],
    subject: str,
    from_name: str,
    from_address: str,
    abstract_chars: int,
    max_authors: int,
    date_label=None,
    smtp: "SmtpConfig | None" = None,
    dry_run: bool = False,
    output_dir=None,
) -> str:
    """Build + (optionally) send the digest. Returns the rendered HTML."""
    if date_label is None:
        date_label = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    html = render_html(papers, date_label, abstract_chars, max_authors)
    text = render_text(papers, date_label, abstract_chars, max_authors)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "preview.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(output_dir, "preview.txt"), "w", encoding="utf-8") as f:
            f.write(text)

    if dry_run:
        log.info("DRY RUN - not sending. Recipients would have been: %s", list(recipients))
        return html

    smtp = smtp or SmtpConfig.from_env(default_from=from_address or "")
    effective_from = from_address or smtp.from_address
    message = build_message(
        subject=subject,
        html=html,
        text=text,
        from_name=from_name,
        from_address=effective_from,
        recipients=recipients,
    )
    send(message, recipients, smtp)
    return html
