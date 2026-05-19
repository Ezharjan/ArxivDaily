"""ArxivDaily — entry point.

Pipeline:
  1. Load config.json
  2. Query arXiv once per keyword (within configured categories + lookback)
  3. Score + rank by keyword relevance
  4. Diff against state.json (`seen_ids`) — keep only papers we haven't sent
  5. If anything is new, render + send the digest email
  6. Persist new IDs back to state.json

Designed to run inside GitHub Actions, but works locally too:
  python main.py --dry-run         # render preview.html/.txt only
  python main.py                   # full send (needs SMTP_* env vars)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from typing import Sequence

from src import arxiv_fetcher, email_sender, relevance, state

LOG = logging.getLogger("arxivdaily")

# Resolve everything relative to this file so the script works regardless of cwd.
ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "state.json")
PREVIEW_DIR = os.path.join(ROOT, "preview")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg.get("keywords"), list) or not cfg["keywords"]:
        raise ValueError("config.json must define a non-empty 'keywords' list")
    if not isinstance(cfg.get("recipients"), list) or not cfg["recipients"]:
        raise ValueError("config.json must define a non-empty 'recipients' list")
    cfg.setdefault("categories", [])
    cfg.setdefault("fetch", {})
    cfg.setdefault("ranking", {})
    cfg.setdefault("email", {})
    return cfg


def _set_github_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    safe = str(value).replace("\n", " ").strip()
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"{name}={safe}\n")


def run(*, dry_run: bool, save_state: bool, force: bool, verbose: bool) -> int:
    _setup_logging(verbose)
    cfg = _load_config(CONFIG_PATH)
    st = state.load(STATE_PATH)

    keywords: Sequence[str] = cfg["keywords"]
    categories: Sequence[str] = cfg["categories"]
    fetch_cfg = cfg["fetch"]
    rank_cfg = cfg["ranking"]
    email_cfg = cfg["email"]
    recipients: Sequence[str] = cfg["recipients"]

    # 1) Fetch
    papers = arxiv_fetcher.fetch_all(
        keywords=keywords,
        categories=categories,
        max_results_per_keyword=int(fetch_cfg.get("max_results_per_keyword", 30)),
        sort_by=str(fetch_cfg.get("sort_by", "submittedDate")),
        lookback_days=int(fetch_cfg.get("lookback_days", 2)),
    )
    LOG.info("fetched %d unique papers within lookback window", len(papers))

    # 2) Score + rank
    ranked = relevance.score_and_rank(
        papers,
        keywords=keywords,
        title_weight=float(rank_cfg.get("title_weight", 3.0)),
        abstract_weight=float(rank_cfg.get("abstract_weight", 1.0)),
        multi_keyword_bonus=float(rank_cfg.get("multi_keyword_bonus", 0.5)),
        min_score=float(rank_cfg.get("min_score", 1.0)),
        max_papers=int(rank_cfg.get("max_papers_per_email", 25)),
    )
    LOG.info("%d papers passed scoring threshold", len(ranked))

    # 3) Diff against state — the "only on update" gate.
    # `genuinely_new` is what determines whether state.json must be rewritten;
    # `unseen` is what we'll actually email (broader when --force is set).
    seen = st.seen_set
    genuinely_new = [p for p in ranked if p.short_id not in seen]
    if force:
        unseen = ranked
        LOG.info("--force set: emailing all %d ranked papers (%d are genuinely new)",
                 len(ranked), len(genuinely_new))
    else:
        unseen = genuinely_new
    LOG.info("%d papers are NEW since last successful run", len(genuinely_new))

    state_grew = len(genuinely_new) > 0

    # Mark all ranked papers as seen so we never re-notify, even on retries.
    # Only persist when state actually grew — otherwise we'd commit a noisy
    # timestamp-only diff every cron tick.
    if save_state and state_grew:
        st.mark_seen([p.short_id for p in ranked])
        st.last_run_utc = state.now_iso()

    state_changed_signal = "true" if (save_state and state_grew) else "false"

    # No new papers => skip the email entirely (arXiv hasn't updated for us).
    if not unseen:
        LOG.info("no new matching papers — skipping email")
        _set_github_output("papers_sent", "0")
        _set_github_output("state_changed", state_changed_signal)
        if save_state and state_grew:
            state.save(STATE_PATH, st)
        return 0

    # 4) Compose + send
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    n = len(unseen)
    subject_template = str(email_cfg.get(
        "subject_template", "[ArxivDaily] {n_papers} new {papers} — {date}"
    ))
    subject = subject_template.format(
        n_papers=n,
        papers="papers" if n != 1 else "paper",
        date=today,
    )

    email_sender.send_digest(
        unseen,
        recipients=recipients,
        subject=subject,
        from_name=str(email_cfg.get("from_name", "ArxivDaily")),
        from_address=str(email_cfg.get("from_address", "")),
        abstract_chars=int(email_cfg.get("abstract_chars", 320)),
        max_authors=int(email_cfg.get("include_authors_max", 5)),
        date_label=today,
        dry_run=dry_run,
        output_dir=PREVIEW_DIR,
    )

    if save_state and state_grew:
        if not dry_run:
            st.last_sent_utc = state.now_iso()
        state.save(STATE_PATH, st)

    _set_github_output("papers_sent", str(n))
    _set_github_output("state_changed", state_changed_signal)
    _set_github_output("subject", subject)
    LOG.info("done — %d papers, dry_run=%s, state_changed=%s",
             n, dry_run, state_changed_signal)
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send the daily arXiv digest email.")
    p.add_argument("--dry-run", action="store_true", help="Render preview.html/.txt but do not send and do not write state.")
    p.add_argument("--no-save-state", action="store_true", help="Don't update state.json (useful for debugging).")
    p.add_argument("--force", action="store_true", help="Resend papers even if they are already in state.seen_ids.")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    save_state = not (args.dry_run or args.no_save_state)
    try:
        return run(dry_run=args.dry_run, save_state=save_state, force=args.force, verbose=args.verbose)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("arxivdaily").exception("fatal error: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
papers even if they are already in state.seen_ids.")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    save_state = not (args.dry_run or args.no_save_state)
    try:
        return run(dry_run=args.dry_run, save_state=save_state, force=args.force, verbose=args.verbose)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("arxivdaily").exception("fatal error: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
