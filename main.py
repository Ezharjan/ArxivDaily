"""ArxivDaily — entry point.

Pipeline:
  1. Load config.json (and, for local runs, a .env file with your SMTP settings)
  2. Fetch arXiv's latest announcement for your categories (RSS), falling back
     to the arXiv search API when the feed is unavailable
  3. Score + rank by keyword relevance
  4. Diff against state.json (`seen_ids`) — keep only papers we haven't sent
  5. If anything is new, render + send the digest email
  6. Persist new IDs back to state.json (and the web archive, when it's on)

Designed to run inside GitHub Actions, but works locally too:
  python main.py --dry-run --open   # build preview/email.html and open it; sends nothing
  python main.py --test-email       # send a test email to check your settings
  python main.py --check            # validate config.json and log in to your mail server
  python main.py --serve            # preview the web archive at http://127.0.0.1:8000
  python main.py                    # full run: fetch, rank, email, save (needs SMTP_* settings)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import functools
import http.server
import logging
import os
import socketserver
import sys
import webbrowser
from typing import List, Optional, Sequence

from src import __version__, archive, arxiv_fetcher, relevance, state, taxonomy
from src import github_actions as gha
from src.arxiv_fetcher import FetchError, FetchResult, Paper
from src.config import Config, ConfigError, env_flag, load_config, load_dotenv, mask_email, resolve_recipients
from src.email_render import (DigestContext, TestContext, plural, recipients_phrase, render_digest_html,
                              render_digest_text, render_test_html, render_test_text)
from src.email_sender import SetupError, SmtpConfig, send_all, verify_login

LOG = logging.getLogger("arxivdaily")

# Resolve everything relative to this file so the script works regardless of cwd.
ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "state.json")
PREVIEW_DIR = os.path.join(ROOT, "preview")
WEB_DIR = os.path.join(ROOT, "web")
ARCHIVE_DIR = os.path.join(WEB_DIR, "data")
WORKFLOW_PATH = os.path.join(ROOT, ".github", "workflows", "arxiv_daily.yml")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


# --------------------------------------------------------------------------- #
# shared steps
# --------------------------------------------------------------------------- #

def _rank(cfg: Config, papers: Sequence[Paper]) -> List[Paper]:
    candidates = arxiv_fetcher.filter_announce_types(
        papers, include_cross_lists=cfg.fetch.include_cross_lists, include_revisions=cfg.fetch.include_revisions)
    return relevance.score_and_rank(
        candidates, cfg.keywords,
        title_weight=cfg.ranking.title_weight,
        abstract_weight=cfg.ranking.abstract_weight,
        multi_keyword_bonus=cfg.ranking.multi_keyword_bonus,
        min_score=cfg.ranking.min_score,
    )


def _candidates_count(cfg: Config, papers: Sequence[Paper]) -> int:
    return len(arxiv_fetcher.filter_announce_types(
        papers, include_cross_lists=cfg.fetch.include_cross_lists, include_revisions=cfg.fetch.include_revisions))


def _today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


def _site_url() -> str:
    return os.environ.get("ARXIVDAILY_SITE_URL", "").strip()


def _archive_enabled() -> bool:
    flag = env_flag("ARXIVDAILY_ARCHIVE")          # set by the workflow: is GitHub Pages on?
    if flag is not None:
        return flag
    return os.path.isfile(os.path.join(ARCHIVE_DIR, "index.json"))


def _update_archive(cfg: Config, day: _dt.date, papers: Sequence[Paper]) -> None:
    """Update the web archive. Failures here are reported but never fail the run:
    the email has already gone out, and state.json must still be saved."""
    try:
        archive.update(ARCHIVE_DIR, day=day, papers=papers, keywords=cfg.keywords, categories=cfg.categories,
                       repository=gha.repository(), keep_days=cfg.archive.keep_days,
                       max_per_day=cfg.archive.max_papers_per_day)
    except Exception as e:  # noqa: BLE001
        LOG.warning("Couldn't update the web archive: %s", e)
        gha.annotate("warning", f"Couldn't update the web archive: {e}", title="Web archive")


def _context(cfg: Config, result: FetchResult, papers: Sequence[Paper], new: Sequence[Paper]) -> DigestContext:
    return DigestContext(
        papers=papers,
        keywords=cfg.keywords,
        day=result.announced or _today(),
        total_matches=len(new),
        keyword_counts=relevance.keyword_counts(new, cfg.keywords),
        categories=cfg.categories,
        source=result.source,
        lookback_days=cfg.fetch.lookback_days,
        abstract_chars=cfg.email.abstract_chars,
        max_authors=cfg.email.include_authors_max,
        repo=gha.repository(),
        repo_url=gha.repo_url(),
        edit_config_url=gha.edit_url("config.json"),
        workflow_url=gha.workflow_url(),
        site_url=_site_url(),
        notes=list(result.notes),
    )


def _write_preview(name: str, html: str, text: str) -> str:
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    html_path = os.path.join(PREVIEW_DIR, f"{name}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(PREVIEW_DIR, f"{name}.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    return html_path


def _smtp_and_recipients(cfg: Config):
    smtp = SmtpConfig.from_env(default_from=cfg.email.from_address)
    fallback = smtp.username if "@" in smtp.username else ""
    try:
        recipients, source = resolve_recipients(cfg, fallback=fallback)
    except ConfigError as e:              # a bad MAIL_TO secret is an email-setup problem
        raise SetupError(str(e)) from None
    if not recipients:
        raise SetupError("Nobody to send the digest to. Add a MAIL_TO secret with one or more addresses "
                         "(comma-separated).")
    return smtp, recipients, source


def _smtp_ready() -> bool:
    return bool(os.environ.get("SMTP_USERNAME", "").strip() and os.environ.get("SMTP_PASSWORD", "").strip())


# --------------------------------------------------------------------------- #
# GitHub run summary (public on public repos: never include addresses)
# --------------------------------------------------------------------------- #

def _warn_undelivered(what: str, n: int) -> str:
    """Log and annotate a partial delivery (addresses are never shown: run logs can be public)."""
    msg = (f"The {what} couldn't be delivered to {plural(n, 'recipient address', 'recipient addresses')}; "
           "everyone else got it. This is usually a typo in the MAIL_TO secret.")
    LOG.warning(msg)
    gha.annotate("warning", msg, title=f"Some recipients didn't get the {what}")
    return msg


def _summary_table(cfg: Config, result: FetchResult, checked: int, matches: int, unseen: int) -> List[str]:
    if result.source == "rss":
        source = f"Daily RSS feed, announcement of {(result.announced or _today()).strftime('%a %d %b %Y')}"
    else:
        source = f"Search API, last {plural(cfg.fetch.lookback_days, 'day')}"
    cats = ", ".join(cfg.categories) or "all of arXiv"
    rows = [
        "| | |", "|---|---|",
        f"| arXiv source | {source} |",
        f"| Papers checked | {checked} in {gha.md_escape(cats)} |",
        f"| Matched your topics | {matches} ({unseen} not emailed before) |",
    ]
    site = _site_url()
    if site:
        rows.append(f"| Web archive | {site} |")
    else:
        pages = gha.settings_url("pages")
        rows.append("| Web archive | Off. To publish one, set *Settings → Pages → Source* to "
                    f"**GitHub Actions**{f' ([open]({pages}))' if pages else ''}. |")
    return rows


def _summary_notes(result: FetchResult) -> List[str]:
    return [f"> {gha.md_escape(n)}" for n in result.notes] + ([""] if result.notes else [])


def _summary_papers(papers: Sequence[Paper], limit: int = 25) -> List[str]:
    lines = []
    for i, p in enumerate(papers[:limit], start=1):
        kws = ", ".join(p.matched_keywords)
        lines.append(f"{i}. {gha.link(p.title, p.abs_url)} — *{gha.md_escape(kws)}*")
    if len(papers) > limit:
        lines.append(f"\n…and {len(papers) - limit} more.")
    return lines


def _summary_setup_hint() -> List[str]:
    if _smtp_ready():
        return []
    secrets = gha.settings_url("secrets/actions")
    return ["", "> [!IMPORTANT]",
            "> **Email isn't set up yet.** Add the `SMTP_USERNAME` and `SMTP_PASSWORD` repository secrets"
            + (f" ([open settings]({secrets}))" if secrets else "") + ", then run the workflow with "
            "**send test email**. The setup guide (docs/setup-guide.md) walks through each step."]


def _summary_failure(title: str, message: str) -> None:
    body = "\n".join("> " + line if line.strip() else ">" for line in message.splitlines())
    gha.write_summary(f"## ❌ {title}\n\n> [!CAUTION]\n{body}\n")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_run(cfg: Config, *, dry_run: bool, save_state: bool, force: bool, open_preview: bool) -> int:
    repo = gha.repository()
    st = state.load(STATE_PATH, repository=repo)

    smtp = recipients = recipient_source = None
    if not dry_run:                      # fail before fetching if email can't work anyway
        smtp, recipients, recipient_source = _smtp_and_recipients(cfg)

    result = arxiv_fetcher.fetch(cfg, fallback_when_empty=dry_run or force)
    checked = _candidates_count(cfg, result.papers)
    matches = _rank(cfg, result.papers)
    seen = st.seen_set
    unseen = [p for p in matches if p.short_id not in seen]
    new = matches if force else unseen
    digest = new[: cfg.ranking.max_papers_per_email]
    for note in result.notes:
        LOG.info(note)
    LOG.info("%d papers checked, %d match your topics, %d not emailed before%s",
             checked, len(matches), len(unseen), " (--force: including already-sent papers)" if force else "")

    if not digest:
        if not result.papers and result.source == "rss":
            why = "arXiv's latest feed has no papers in your categories (normal on weekends and holidays)."
        elif not result.papers:
            why = f"arXiv's search found no papers in your categories from the last {plural(cfg.fetch.lookback_days, 'day')}."
        elif not matches:
            why = f"None of the {checked} papers matched your topics."
        else:
            why = f"All {len(matches)} matching papers were emailed before."
        LOG.info("No new matching papers — no email this time. %s", why)
        if save_state and _archive_enabled():
            _update_archive(cfg, result.announced or _today(), [])
        gha.write_summary("\n".join(["## No new papers this time", "", why, ""] + _summary_notes(result)
                                    + _summary_table(cfg, result, checked, len(matches), len(unseen))
                                    + _summary_setup_hint()))
        gha.set_output("papers_sent", "0")
        gha.set_output("state_changed", "false")   # read by workflows from version 1
        return 0

    ctx = _context(cfg, result, digest, new)
    subject = cfg.email.subject_template.format(
        n_papers=len(digest), papers="paper" if len(digest) == 1 else "papers", date=ctx.day.isoformat())
    html = render_digest_html(ctx, subject)
    text = render_digest_text(ctx)
    preview = _write_preview("email", html, text)
    LOG.info("Email preview: %s (%.0f KB)", os.path.relpath(preview, ROOT), len(html.encode()) / 1024)

    if dry_run:
        LOG.info("Dry run — nothing was sent and nothing was saved.")
        if open_preview:
            webbrowser.open("file://" + os.path.abspath(preview))
        gha.write_summary("\n".join(
            [f"## 👀 Preview: {plural(len(digest), 'paper')} would be emailed", "",
             f"Subject: **{gha.md_escape(subject)}**. Nothing was sent. The rendered email is attached "
             "below as the **email-preview** artifact.", ""] + _summary_notes(result)
            + _summary_table(cfg, result, checked, len(matches), len(unseen)) + [""]
            + _summary_papers(digest) + _summary_setup_hint()))
        gha.set_output("papers_sent", "0")
        gha.set_output("state_changed", "false")
        return 0

    delivered, failed = send_all(recipients=recipients, subject=subject, html=html, text=text,
                                 from_name=cfg.email.from_name, smtp=smtp)
    if save_state:
        st.mark_seen(p.short_id for p in new)
        st.last_run_utc = st.last_sent_utc = state.now_iso()
        state.save(STATE_PATH, st)
        if _archive_enabled():
            _update_archive(cfg, ctx.day, new)
    if failed:
        _warn_undelivered("digest", len(failed))
    gha.write_summary("\n".join(
        [f"## 📬 Emailed {plural(len(digest), 'paper')} to {plural(len(delivered), 'recipient')}", "",
         f"Subject: **{gha.md_escape(subject)}**", ""] + _summary_notes(result)
        + _summary_table(cfg, result, checked, len(matches), len(unseen)) + [""] + _summary_papers(digest)))
    gha.set_output("papers_sent", str(len(digest)))
    gha.set_output("state_changed", "true" if save_state else "false")
    gha.set_output("subject", subject)
    LOG.info("Done — emailed %s to %s.", plural(len(digest), "paper"), plural(len(delivered), "recipient"))
    return 0


def cmd_test_email(cfg: Config) -> int:
    smtp, recipients, recipient_source = _smtp_and_recipients(cfg)
    problem = ""
    try:
        result = arxiv_fetcher.fetch(cfg, fallback_when_empty=True)
        matches = _rank(cfg, result.papers)
        if not result.papers:
            problem = ("arXiv has no papers in your categories to show right now (it doesn't announce new "
                       "papers on weekends and holidays), so there's no sample this time. Your first digest "
                       "arrives after the next arXiv announcement.")
        elif not matches:
            problem = (f"None of the {_candidates_count(cfg, result.papers)} papers arXiv announced most recently "
                       "match your topics, so there's no sample this time. If that happens often, try broader "
                       "keywords (see docs/configuration.md).")
    except FetchError as e:
        LOG.warning("Couldn't reach arXiv (%s); sending the test email without sample papers.", e)
        result, matches = FetchResult(papers=[], source="rss"), []
        problem = (f"ArxivDaily couldn't reach arXiv just now ({e}), so there are no sample papers this time. "
                   "Your email settings work; the scheduled runs will try arXiv again.")
    ctx = _context(cfg, result, matches[:5], matches[:5])
    test = TestContext(sender=smtp.from_address, smtp_summary=smtp.describe(), recipient_count=len(recipients),
                       recipient_source=recipient_source, schedule=gha.schedule_description(WORKFLOW_PATH),
                       digest=ctx, fetch_problem=problem)
    subject = "ArxivDaily test: your email setup works"
    html, text = render_test_html(test, subject), render_test_text(test)
    _write_preview("test-email", html, text)
    delivered, failed = send_all(recipients=recipients, subject=subject, html=html, text=text,
                                 from_name=cfg.email.from_name, smtp=smtp)
    LOG.info("Test email sent to %s via %s. Check your inbox (and the spam folder, just in case).",
             plural(len(delivered), "recipient"), smtp.describe())
    gha.write_summary("\n".join([
        f"## ✅ Test email sent to {plural(len(delivered), 'recipient')}", "",
        f"Sent via `{smtp.host}:{smtp.port}` from {mask_email(smtp.from_address)}. "
        f"Recipients: {recipients_phrase(len(delivered), recipient_source)}. "
        "Check your inbox — and the spam folder the first time.",
        "", f"From now on, ArxivDaily checks for new papers {gha.schedule_description(WORKFLOW_PATH)} "
        "and emails you whenever some match your topics."]
        + (["", "⚠️ " + _warn_undelivered("test email", len(failed))] if failed else [])))
    return 0


def cmd_check(cfg: Config) -> int:
    ok = True
    print(f"ArxivDaily {__version__} — checking your setup\n")
    print(f"  ✓ config.json is valid: {plural(len(cfg.keywords), 'keyword')}")
    for kw in cfg.keywords:
        print(f"      · {kw}")
    if cfg.categories:
        print(f"  ✓ {plural(len(cfg.categories), 'category', 'categories')}:")
        for c in cfg.categories:
            print(f"      · {c:<10} {taxonomy.category_name(c)}")
    else:
        print("  ✓ No categories: all of arXiv is searched through the API")
    print(f"  ✓ Source: {cfg.fetch.source}; up to {cfg.ranking.max_papers_per_email} papers per email")
    for w in cfg.warnings:
        print(f"  ! {w}")
    try:
        smtp, recipients, source = _smtp_and_recipients(cfg)
        print(f"  ✓ Mail server: {smtp.describe()}")
        print(f"  ✓ Sending as {smtp.from_address}; delivering to: {recipients_phrase(len(recipients), source)}")
        print("    Logging in to the mail server (nothing will be sent)…")
        verify_login(smtp)
        print("  ✓ Login works")
    except SetupError as e:
        ok = False
        print(f"  ✗ {e}")
    print("\nAll good — try `python main.py --test-email` next." if ok
          else "\nFix the item marked ✗ above, then run `python main.py --check` again.")
    return 0 if ok else 1


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the terminal readable
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def cmd_serve(cfg: Config, port: int, open_browser: bool) -> int:
    site = archive.build_preview_site(WEB_DIR, os.path.join(PREVIEW_DIR, "site"))
    data_dir = os.path.join(site, "data")
    try:
        result = arxiv_fetcher.fetch(cfg, fallback_when_empty=True)
        matches = _rank(cfg, result.papers)
        archive.update(data_dir, day=result.announced or _today(), papers=matches, keywords=cfg.keywords,
                       categories=cfg.categories, repository=gha.repository(),
                       keep_days=cfg.archive.keep_days, max_per_day=cfg.archive.max_papers_per_day)
        LOG.info("Added %d matching papers from arXiv's latest announcement to the preview.", len(matches))
    except FetchError as e:
        LOG.warning("Couldn't reach arXiv (%s); showing the archive as it is.", e)
        archive.update(data_dir, day=_today(), papers=[], keywords=cfg.keywords, categories=cfg.categories,
                       repository=gha.repository(), keep_days=cfg.archive.keep_days,
                       max_per_day=cfg.archive.max_papers_per_day)
    handler = functools.partial(_QuietHandler, directory=site)
    httpd = None
    for candidate in range(port, port + 20):
        try:
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", candidate), handler)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        raise SetupError(f"Ports {port}-{port + 19} are all busy; pass --port to choose another one.")
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Web archive preview: {url}\n  (a copy in preview/site — your real archive is untouched)\n"
          "  Press Ctrl+C to stop.\n", flush=True)
    if open_browser:
        webbrowser.open(url)
    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Email yourself the new arXiv papers that match your keywords.",
        epilog="Settings live in config.json; email credentials come from environment variables "
               "(or a .env file next to main.py). See README.md.")
    p.add_argument("--dry-run", action="store_true",
                   help="Build preview/email.html but don't send email and don't update state.json.")
    p.add_argument("--open", action="store_true", help="With --dry-run: open the preview in your browser.")
    p.add_argument("--test-email", action="store_true", help="Send a test email to check your email settings.")
    p.add_argument("--check", action="store_true",
                   help="Validate config.json and log in to the mail server without sending anything.")
    p.add_argument("--serve", action="store_true", help="Preview the web archive in your browser.")
    p.add_argument("--port", type=int, default=8000, help="Port for --serve (default 8000).")
    p.add_argument("--no-browser", action="store_true", help="With --serve: don't open a browser window.")
    p.add_argument("--no-save-state", action="store_true", help="Send, but don't record the papers in state.json.")
    p.add_argument("--force", action="store_true", help="Include papers that were already emailed (they're normally skipped).")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    p.add_argument("--version", action="version", version=f"ArxivDaily {__version__}")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    _setup_logging(args.verbose)
    loaded = load_dotenv(os.path.join(ROOT, ".env"))
    if loaded:
        LOG.debug("loaded %s from .env", ", ".join(loaded))
    try:
        cfg = load_config(CONFIG_PATH)
        for warning in cfg.warnings:
            LOG.warning(warning)
            gha.annotate("warning", warning, title="config.json", file="config.json")
        if args.serve:
            return cmd_serve(cfg, args.port, not args.no_browser)
        if args.check:
            return cmd_check(cfg)
        if args.test_email:
            return cmd_test_email(cfg)
        save_state = not (args.dry_run or args.no_save_state)
        return cmd_run(cfg, dry_run=args.dry_run, save_state=save_state, force=args.force,
                       open_preview=args.open)
    except ConfigError as e:
        LOG.error("%s", e)
        rel = os.path.relpath(e.path, ROOT) if os.path.isabs(e.path) else e.path
        gha.annotate("error", str(e), title="Fix config.json", file=rel if rel.endswith(".json") else "",
                     line=e.line, col=e.column)
        _summary_failure("config.json needs a fix", str(e))
    except SetupError as e:
        LOG.error("%s", e)
        gha.annotate("error", str(e), title="Email setup")
        secrets = gha.settings_url("secrets/actions")
        _summary_failure("Email setup needs attention",
                         str(e) + (f"\n\nOpen your repository secrets: {secrets}" if secrets else ""))
    except FetchError as e:
        msg = (f"Couldn't get papers from arXiv: {e}. This is usually temporary; "
               "the next scheduled run will try again.")
        LOG.error(msg)
        gha.annotate("error", msg, title="arXiv unavailable")
        _summary_failure("arXiv was unavailable", msg)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001
        LOG.exception("unexpected error: %s", e)
        gha.annotate("error", f"Unexpected error: {e}. Please report it at "
                     "https://github.com/Ezharjan/ArxivDaily/issues with the log of this run.",
                     title="ArxivDaily crashed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
