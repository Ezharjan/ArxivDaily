"""HTML and plain-text bodies for the digest and the test email.

Email clients are a hostile place for CSS: Gmail drops <style> blocks in some
apps and Outlook ignores most modern layout. So everything here is a single
column built from tables with inline styles, which renders the same in Gmail,
Outlook, Apple Mail and phone apps. Matched keywords are shown with a
highlighter colour per topic, so it's clear at a glance why a paper is here.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from html import escape
from typing import Dict, List, Optional, Sequence

from .arxiv_fetcher import Paper
from .relevance import compile_keywords, highlight_spans

INK = "#1C2230"
BODY = "#2C3443"
GRAPHITE = "#5B6474"
FAINT = "#6F7786"
RULE = "#E7E9EE"
LINK = "#1F4FB0"
PAGE = "#F4F5F7"
HIGHLIGHTERS = ["#FFEC8A", "#BDF0C8", "#FFD1E6", "#CBE6FF", "#FFDAB3", "#E2D6FF"]

SERIF = "Charter,'Bitstream Charter','Sitka Text',Cambria,Georgia,'Times New Roman',serif"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


@dataclass
class DigestContext:
    papers: Sequence[Paper]                 # what to show (already ranked and capped)
    keywords: Sequence[str]
    day: _dt.date                           # announcement date (or run date)
    total_matches: int                      # new matches before capping
    keyword_counts: Dict[str, int]          # over all new matches
    categories: Sequence[str] = ()
    source: str = "rss"                     # "rss" or "api"
    lookback_days: int = 5
    abstract_chars: int = 320
    max_authors: int = 5
    repo: str = ""                          # "owner/name" when running on GitHub
    repo_url: str = ""
    edit_config_url: str = ""
    workflow_url: str = ""
    site_url: str = ""
    notes: List[str] = field(default_factory=list)


@dataclass
class TestContext:
    sender: str
    smtp_summary: str                       # "smtp.gmail.com:587 (STARTTLS), detected automatically"
    recipient_count: int
    recipient_source: str
    schedule: str                           # "daily at 06:23 and 14:23 UTC"
    digest: DigestContext
    fetch_problem: str = ""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def plural(n: int, word: str, many: Optional[str] = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def long_date(day: _dt.date) -> str:
    return f"{day.strftime('%A')}, {day.day} {day.strftime('%B %Y')}"


def truncate(text: str, max_chars: int) -> str:
    text = " ".join((text or "").split())
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:.-–—(")
    return cut + "…"


def excerpt(p: Paper, max_chars: int, patterns) -> str:
    """The abstract, shortened so that the reason it matched stays visible.

    Normally that's just the first ``max_chars`` characters. But when the
    keyword is in neither the title nor that opening, the excerpt starts at the
    sentence that contains the first match instead ("…we fine-tune diffusion
    models to…"), so every paper shows why it's in the digest.
    """
    text = " ".join((p.summary or "").split())
    if max_chars <= 0 or len(text) <= max_chars or highlight_spans(p.title, patterns):
        return truncate(text, max_chars)
    spans = highlight_spans(text, patterns)
    if not spans or spans[0][1] <= max_chars - 10:
        return truncate(text, max_chars)
    s = spans[0][0]
    start = text.rfind(". ", 0, s)
    if start != -1 and s - start < 200:
        start += 2
    else:
        start = text.find(" ", max(0, s - 90)) + 1
    return "…" + truncate(text[start:], max_chars - 1)


def format_authors(authors: Sequence[str], max_show: int) -> str:
    if not authors:
        return ""
    if max_show <= 0 or len(authors) <= max_show:
        return ", ".join(authors)
    return ", ".join(authors[:max_show]) + f" and {len(authors) - max_show} more"


def human_list(items: Sequence[str], limit: int = 4) -> str:
    items = list(items)
    if len(items) > limit:
        items = items[:limit] + [f"{len(items) - limit} more"]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def recipients_phrase(count: int, source: str) -> str:
    if source == "your sending address":
        return "Your own address (add a MAIL_TO secret to send elsewhere)"
    return f"{plural(count, 'address', 'addresses')} from {'the ' if source.endswith('secret') else ''}{source}"


def highlighter(index: int) -> str:
    return HIGHLIGHTERS[index % len(HIGHLIGHTERS)]


def _marked(text: str, patterns) -> str:
    """Escape ``text`` and wrap keyword matches in highlighter spans."""
    out, pos = [], 0
    for start, end, idx in highlight_spans(text, patterns):
        out.append(escape(text[pos:start]))
        out.append(f'<span style="background-color:{highlighter(idx)};border-radius:2px;'
                   f'padding:0 2px;margin:0 -2px;">{escape(text[start:end])}</span>')
        pos = end
    out.append(escape(text[pos:]))
    return "".join(out)


def _source_sentence(ctx: DigestContext) -> str:
    cats = human_list(ctx.categories) if ctx.categories else "all of arXiv"
    if ctx.source == "rss":
        return f"from arXiv's announcement of {long_date(ctx.day)} in {cats}"
    return f"from the last {plural(ctx.lookback_days, 'day')} of arXiv submissions in {cats}"


def _legend_html(ctx: DigestContext) -> str:
    chips, quiet = [], []
    for i, kw in enumerate(ctx.keywords):
        n = ctx.keyword_counts.get(kw, 0)
        if n:
            chips.append(
                f'<span style="display:inline-block;margin:0 14px 8px 0;font-family:{SANS};font-size:13px;'
                f'line-height:20px;color:{GRAPHITE};white-space:nowrap;">'
                f'<span style="background-color:{highlighter(i)};color:{INK};border-radius:3px;padding:2px 6px;">'
                f'{escape(kw)}</span>&nbsp;{n}</span>')
        else:
            quiet.append(kw)
    html = "".join(chips)
    if quiet:
        html += (f'<div style="font-family:{SANS};font-size:12.5px;line-height:18px;color:{FAINT};margin-top:2px;">'
                 f'Nothing new for {escape(human_list(quiet, 6))}.</div>')
    return html


def _paper_html(rank: int, p: Paper, ctx: DigestContext, patterns, last: bool) -> str:
    border = "" if last else f"border-bottom:1px solid {RULE};"
    authors = format_authors(p.authors, ctx.max_authors)
    cats = ", ".join(p.categories[:3] or [p.primary_category])
    return (
        '<tr><td class="px" style="padding:0 32px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td width="30" valign="top" style="width:30px;padding:24px 0 0;font-family:{SERIF};font-size:15px;'
        f'line-height:24px;font-weight:700;color:{FAINT};">{rank}</td>'
        f'<td valign="top" style="padding:24px 0 22px;{border}">'
        f'<a href="{escape(p.abs_url)}" style="font-family:{SERIF};font-size:18px;line-height:24px;font-weight:700;'
        f'color:{INK};text-decoration:none;">{_marked(p.title, patterns)}</a>'
        + (f'<div style="font-family:{SANS};font-size:13px;line-height:19px;color:{GRAPHITE};margin-top:6px;">'
           f'{escape(authors)}</div>' if authors else "")
        + f'<div style="font-family:{SERIF};font-size:15px;line-height:24px;color:{BODY};margin-top:10px;">'
        f'{_marked(excerpt(p, ctx.abstract_chars, patterns), patterns)}</div>'
        f'<div style="font-family:{SANS};font-size:13px;line-height:19px;color:{GRAPHITE};margin-top:12px;">'
        f'<a href="{escape(p.pdf_url)}" style="color:{LINK};font-weight:600;text-decoration:none;">PDF</a>&emsp;'
        f'<a href="{escape(p.abs_url)}" style="color:{LINK};text-decoration:none;">arXiv:{escape(p.short_id)}</a>&emsp;'
        f'<span>{escape(cats)}</span></div>'
        '</td></tr></table></td></tr>'
    )


def _page(subject: str, preheader: str, rows: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        '<style>@media only screen and (max-width:520px){.outer{padding:0!important}'
        '.px{padding-left:20px!important;padding-right:20px!important}'
        '.pxn{padding-left:50px!important;padding-right:20px!important}}</style>'
        f'<title>{escape(subject)}</title></head>'
        f'<body style="margin:0;padding:0;background-color:{PAGE};-webkit-text-size-adjust:100%;">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{escape(preheader)}'
        + "&nbsp;&zwnj;" * 40 + "</div>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background-color:{PAGE};"><tr><td class="outer" align="center" style="padding:24px 10px 36px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:640px;background-color:#FFFFFF;">'
        f'{rows}'
        '</table></td></tr></table></body></html>'
    )


def _masthead(day: _dt.date) -> str:
    return (
        '<tr><td class="px" style="padding:26px 32px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="font-family:{SERIF};font-size:19px;line-height:24px;font-weight:700;color:{INK};">ArxivDaily</td>'
        f'<td align="right" style="font-family:{SANS};font-size:13px;line-height:24px;color:{GRAPHITE};">'
        f'{escape(long_date(day))}</td>'
        '</tr></table></td></tr>'
    )


def _heading(title: str, sub: str) -> str:
    return (
        '<tr><td class="px" style="padding:26px 32px 6px;">'
        f'<div style="font-family:{SERIF};font-size:27px;line-height:34px;font-weight:700;color:{INK};">'
        f'{escape(title)}</div>'
        f'<div style="font-family:{SANS};font-size:14px;line-height:21px;color:{GRAPHITE};margin-top:8px;">{sub}</div>'
        '</td></tr>'
    )


def _link(url: str, text: str) -> str:
    return f'<a href="{escape(url)}" style="color:{LINK};text-decoration:none;">{escape(text)}</a>'


def _footer(ctx: DigestContext) -> str:
    links = []
    if ctx.edit_config_url:
        links.append(_link(ctx.edit_config_url, "Change topics"))
    if ctx.site_url:
        links.append(_link(ctx.site_url, "Browse the web archive"))
    if ctx.workflow_url:
        links.append(_link(ctx.workflow_url, "Pause these emails"))
    where = (f'ArxivDaily sends this from your GitHub repository {_link(ctx.repo_url, ctx.repo)}.'
             if ctx.repo else "ArxivDaily sent this from your computer.")
    return (
        f'<tr><td class="px" style="padding:26px 32px 30px;border-top:1px solid {RULE};font-family:{SANS};font-size:12.5px;'
        f'line-height:19px;color:{GRAPHITE};">'
        f'<div>{where}</div>'
        + (f'<div style="margin-top:8px;">{"&emsp;".join(links)}</div>' if links else "")
        + f'<div style="margin-top:14px;color:{FAINT};">Thank you to arXiv for use of its open access '
        'interoperability. ArxivDaily is not affiliated with arXiv.</div>'
        '</td></tr>'
    )


def _papers_rows(ctx: DigestContext) -> str:
    patterns = compile_keywords(ctx.keywords)
    rows = [_paper_html(i, p, ctx, patterns, last=(i == len(ctx.papers)))
            for i, p in enumerate(ctx.papers, start=1)]
    return "".join(rows)


# --------------------------------------------------------------------------- #
# digest
# --------------------------------------------------------------------------- #

def digest_preheader(ctx: DigestContext) -> str:
    if not ctx.papers:
        return "No new papers matched your topics."
    top = ctx.papers[0].title
    more = len(ctx.papers) - 1
    text = f"Top match: {top}" + (f" — plus {plural(more, 'more paper')}" if more else "")
    return text if len(text) <= 150 else text[:147] + "…"


def render_digest_html(ctx: DigestContext, subject: str) -> str:
    n = len(ctx.papers)
    title = f"{plural(n, 'new paper')} on your topics"
    src = escape(_source_sentence(ctx))
    if ctx.total_matches > n:
        sub = f"The {n} most relevant of {ctx.total_matches} matches {src}."
    elif n > 1:
        sub = f"All {n} matches {src}."
    else:
        sub = f"The only match {src}."
    for note in ctx.notes:
        sub += f'<br><span style="color:{FAINT};">{escape(note)}</span>'
    rows = [_masthead(ctx.day), _heading(title, sub)]
    rows.append(f'<tr><td class="px" style="padding:14px 32px 10px;">{_legend_html(ctx)}</td></tr>')
    rows.append(f'<tr><td class="px" style="padding:0 32px;"><div style="border-top:2px solid {INK};font-size:0;'
                'line-height:0;">&nbsp;</div></td></tr>')
    rows.append(_papers_rows(ctx))
    extra = ctx.total_matches - n
    if extra > 0:
        more = (f"{plural(extra, 'more paper')} matched your topics. "
                + (f"Browse them in the {_link(ctx.site_url, 'web archive')}, or raise "
                   if ctx.site_url else "To get more per email, raise ")
                + '<span style="white-space:nowrap;">ranking.max_papers_per_email</span> in config.json.')
        rows.append(f'<tr><td class="pxn" style="padding:4px 32px 26px 62px;font-family:{SANS};font-size:13px;line-height:20px;'
                    f'color:{GRAPHITE};">{more}</td></tr>')
    rows.append(_footer(ctx))
    return _page(subject, digest_preheader(ctx), "".join(rows))


def _paper_text(i: int, p: Paper, ctx: DigestContext, patterns) -> List[str]:
    lines = [f"{i}. {p.title}"]
    authors = format_authors(p.authors, ctx.max_authors)
    if authors:
        lines.append(f"   {authors}")
    lines.append(f"   arXiv:{p.short_id} [{', '.join(p.categories[:3] or [p.primary_category])}]"
                 f"  matched: {', '.join(p.matched_keywords) or '-'}")
    lines.append(f"   {excerpt(p, ctx.abstract_chars, patterns)}")
    lines.append(f"   {p.abs_url}  (PDF: {p.pdf_url})")
    lines.append("")
    return lines


def _footer_text(ctx: DigestContext) -> List[str]:
    lines = ["--"]
    lines.append(f"ArxivDaily sends this from your GitHub repository {ctx.repo} ({ctx.repo_url})."
                 if ctx.repo else "ArxivDaily sent this from your computer.")
    if ctx.edit_config_url:
        lines.append(f"Change topics: {ctx.edit_config_url}")
    if ctx.site_url:
        lines.append(f"Web archive: {ctx.site_url}")
    if ctx.workflow_url:
        lines.append(f"Pause these emails: {ctx.workflow_url}")
    lines.append("Thank you to arXiv for use of its open access interoperability.")
    return lines


def render_digest_text(ctx: DigestContext) -> str:
    n = len(ctx.papers)
    head = f"ArxivDaily — {long_date(ctx.day)}"
    lines = [head, "=" * len(head), ""]
    lines.append(f"{plural(n, 'new paper')} on your topics"
                 + (f" (the {n} most relevant of {ctx.total_matches} matches)" if ctx.total_matches > n else "")
                 + f", {_source_sentence(ctx)}.")
    lines.extend(ctx.notes)
    counts = [f"{kw} ({ctx.keyword_counts.get(kw, 0)})" for kw in ctx.keywords if ctx.keyword_counts.get(kw)]
    if counts:
        lines.append("Topics: " + ", ".join(counts))
    lines.append("")
    patterns = compile_keywords(ctx.keywords)
    for i, p in enumerate(ctx.papers, start=1):
        lines.extend(_paper_text(i, p, ctx, patterns))
    if ctx.total_matches > n:
        lines.append(f"{plural(ctx.total_matches - n, 'more paper')} matched your topics. "
                     + (f"Browse them in the web archive ({ctx.site_url}), or raise "
                        if ctx.site_url else "To get more per email, raise ")
                     + "ranking.max_papers_per_email in config.json.")
        lines.append("")
    lines.extend(_footer_text(ctx))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# test email
# --------------------------------------------------------------------------- #

def _settings_row(label: str, value_html: str) -> str:
    return (f'<tr><td valign="top" style="padding:7px 16px 7px 0;width:132px;font-family:{SANS};font-size:13px;'
            f'line-height:20px;color:{GRAPHITE};white-space:nowrap;">{escape(label)}</td>'
            f'<td valign="top" style="padding:7px 0;font-family:{SANS};font-size:14px;line-height:20px;color:{INK};">'
            f'{value_html}</td></tr>')


def render_test_html(t: TestContext, subject: str) -> str:
    d = t.digest
    topics = "".join(
        f'<span style="display:inline-block;margin:0 6px 6px 0;background-color:{highlighter(i)};'
        f'border-radius:3px;padding:1px 6px;">{escape(kw)}</span>' for i, kw in enumerate(d.keywords))
    settings = "".join([
        _settings_row("Sending from", f"{escape(t.sender)}<br><span style=\"color:{GRAPHITE};font-size:13px;\">"
                                      f"{escape(t.smtp_summary)}</span>"),
        _settings_row("Delivering to", escape(recipients_phrase(t.recipient_count, t.recipient_source))),
        _settings_row("Topics", topics),
        _settings_row("Categories", escape(", ".join(d.categories) or "All of arXiv")),
        _settings_row("Schedule", escape(f"Checks for new papers {t.schedule}")),
    ])
    where = f"from {escape(d.repo)} on GitHub" if d.repo else "from your computer"
    rows = [_masthead(d.day),
            _heading("Your email setup works",
                     f"ArxivDaily sent this test {where}. New papers that match your topics will arrive "
                     "in this same format after each arXiv announcement."),
            f'<tr><td class="px" style="padding:16px 32px 8px;"><table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">{settings}</table></td></tr>']
    if d.papers:
        rows.append(
            f'<tr><td class="px" style="padding:22px 32px 0;"><div style="border-top:2px solid {INK};padding-top:16px;'
            f'font-family:{SERIF};font-size:20px;line-height:26px;font-weight:700;color:{INK};">'
            f'A sample of recent matches</div><div style="font-family:{SANS};font-size:13px;line-height:20px;'
            f'color:{GRAPHITE};margin-top:4px;">{plural(len(d.papers), "paper")} {escape(_source_sentence(d))}.</div>'
            '</td></tr>')
        rows.append(_papers_rows(d))
    else:
        reason = t.fetch_problem or "There are no matching papers to show yet."
        rows.append(f'<tr><td class="px" style="padding:22px 32px 26px;font-family:{SANS};font-size:14px;line-height:21px;'
                    f'color:{GRAPHITE};"><div style="border-top:2px solid {INK};padding-top:16px;">{escape(reason)}'
                    '</div></td></tr>')
    rows.append(_footer(d))
    return _page(subject, "Your ArxivDaily email settings work. Here's what your digest will look like.",
                 "".join(rows))


def render_test_text(t: TestContext) -> str:
    d = t.digest
    lines = ["ArxivDaily — your email setup works", "=" * 35, "",
             f"Sending from:  {t.sender} ({t.smtp_summary})",
             f"Delivering to: {recipients_phrase(t.recipient_count, t.recipient_source)}",
             f"Topics:        {', '.join(d.keywords)}",
             f"Categories:    {', '.join(d.categories) or 'All of arXiv'}",
             f"Schedule:      Checks for new papers {t.schedule}", ""]
    if d.papers:
        lines.append(f"A sample of recent matches ({_source_sentence(d)}):")
        lines.append("")
        patterns = compile_keywords(d.keywords)
        for i, p in enumerate(d.papers, start=1):
            lines.extend(_paper_text(i, p, d, patterns))
    else:
        lines.append(t.fetch_problem or "There are no matching papers to show yet.")
        lines.append("")
    lines.extend(_footer_text(d))
    return "\n".join(lines) + "\n"
