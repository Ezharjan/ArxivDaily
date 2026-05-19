# ArxivDaily

A zero-cost GitHub-Actions toolkit that watches arXiv, picks out the papers
matching your keywords, and emails you an elegant digest **only when there
is something new**.

- Runs entirely on GitHub's free Actions minutes (public repo = unlimited).
- All knobs live in `config.json` — no code edits to add keywords or recipients.
- Generic SMTP transport, so it works with Gmail, Outlook, Fastmail, AWS SES,
  Mailgun SMTP, etc.
- "Only on update" is enforced by `state.json`: each run records the arXiv
  IDs it has already sent, and the next run will only email papers the diff
  shows as new.

## Quick start

1. Push this repo to GitHub.
2. Add the SMTP secrets in **Settings → Secrets and variables → Actions**:

   | Secret          | Example                  | Notes                                 |
   |-----------------|--------------------------|---------------------------------------|
   | `SMTP_HOST`     | `smtp.gmail.com`         | Required.                             |
   | `SMTP_PORT`     | `587`                    | Required.                             |
   | `SMTP_USERNAME` | `you@example.com`        | Required.                             |
   | `SMTP_PASSWORD` | `xxxxxxxxxxxxxxxx`       | App-Password for Gmail, normal pw for SES, etc. |
   | `SMTP_FROM`     | `you@example.com`        | Optional; defaults to `SMTP_USERNAME`. |
   | `SMTP_SECURITY` | `starttls` / `ssl` / `none` | Optional; defaults to `starttls`.  |

3. Edit `config.json` to set your `keywords`, arXiv `categories`, and
   `recipients`. Commit and push.
4. (Optional) trigger the workflow once manually from the **Actions** tab
   to verify everything works. Use the `dry_run` input to render a preview
   without sending.

The scheduled workflow runs at **08:00 UTC** and **20:00 UTC** every day.
Each run only sends an email if at least one matching paper is new since
the previous successful run.

## Configuration reference

```jsonc
{
  "keywords": ["large language model", "..."],   // phrase-matched in title/abstract
  "categories": ["cs.LG", "cs.CL", "cs.AI"],     // arXiv category filter
  "recipients": ["you@example.com"],
  "fetch": {
    "max_results_per_keyword": 30,
    "lookback_days": 2,                          // ignore papers older than this
    "sort_by": "submittedDate"                   // or "lastUpdatedDate" / "relevance"
  },
  "ranking": {
    "max_papers_per_email": 25,
    "min_score": 1.0,
    "title_weight": 3.0,
    "abstract_weight": 1.0,
    "multi_keyword_bonus": 0.5
  },
  "email": {
    "from_name": "ArxivDaily",
    "from_address": "",                          // defaults to SMTP_FROM / SMTP_USERNAME
    "subject_template": "[ArxivDaily] {n_papers} new {papers} — {date}",  // {papers} = "paper" / "papers"
    "abstract_chars": 320,
    "include_authors_max": 5
  }
}
```

A paper's score is `title_weight × #title_hits + abstract_weight × #abstract_hits`,
plus `multi_keyword_bonus` per additional distinct keyword it matches.
Papers below `min_score` are dropped; the top `max_papers_per_email` are sent.

## Local development

```bash
pip install -r requirements.txt

# Render a preview to preview/preview.html without sending or updating state.
python main.py --dry-run --verbose

# Force-resend the current top matches, ignoring state.json.
python main.py --force --dry-run
```

## How "only on update" works

`state.json` holds the rolling list of arXiv IDs we've already sent (capped
at 5 000 entries). Each run:

1. Fetches today's matches.
2. Subtracts anything already in `seen_ids`.
3. If the remainder is empty → exits without sending.
4. Otherwise → sends the digest, adds those IDs to `seen_ids`, and the
   workflow commits the updated `state.json` back to the repo.

Because the schedule polls twice a day, you get the day's new papers
shortly after arXiv publishes them, and never the same paper twice.

## File layout

```
.
├── .github/workflows/arxiv_daily.yml   # scheduled action
├── config.json                         # your keywords / categories / recipients
├── state.json                          # auto-updated by the action
├── main.py                             # CLI entry point
├── requirements.txt
└── src/
    ├── arxiv_fetcher.py                # arXiv API queries
    ├── email_sender.py                 # HTML + SMTP
    ├── relevance.py                    # keyword scoring
    └── state.py                        # seen_ids persistence
```

## Cost

GitHub Actions: free for public repos; private repos get 2 000 minutes/month
on the free tier and each ArxivDaily run takes ≤ 30 s, so the toolkit fits
comfortably even with twice-daily scheduling on a private repo.
