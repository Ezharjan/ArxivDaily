# ArxivDaily

A zero-cost GitHub Actions toolkit that watches arXiv for new papers matching
your keywords, scores them by relevance, and emails you an elegant digest
**only when there is something new**.

## Table of Contents

1. [Features](#features)
2. [Prerequisites](#prerequisites)
3. [Setup Guide](#setup-guide)
   - [Step 1 — Fork or push this repo](#step-1--fork-or-push-this-repo)
   - [Step 2 — Create a Gmail App Password (or other SMTP credentials)](#step-2--create-a-gmail-app-password-or-other-smtp-credentials)
   - [Step 3 — Add SMTP secrets to GitHub](#step-3--add-smtp-secrets-to-github)
   - [Step 4 — Configure your keywords and recipients](#step-4--configure-your-keywords-and-recipients)
   - [Step 5 — Test it](#step-5--test-it)
4. [SMTP Setup for Other Providers](#smtp-setup-for-other-providers)
5. [Configuration Reference](#configuration-reference)
6. [How the Scoring Works](#how-the-scoring-works)
7. [How "Only on Update" Works](#how-only-on-update-works)
8. [Local Development](#local-development)
9. [CLI Options](#cli-options)
10. [File Layout](#file-layout)
11. [Troubleshooting](#troubleshooting)
12. [Cost](#cost)

---

## Features

- **Free** — runs entirely on GitHub Actions free minutes (public repo = unlimited).
- **Config-only setup** — all knobs live in `config.json`; no code edits needed.
- **Generic SMTP transport** — works with Gmail, Outlook, Fastmail, AWS SES,
  Mailgun, or any provider that speaks SMTP.
- **Smart deduplication** — `state.json` tracks every paper ID already sent,
  so you never get the same paper twice.
- **Keyword relevance scoring** — papers are ranked by how many of your keywords
  appear in the title and abstract, with configurable weights and bonuses.
- **Dual-format email** — sends a responsive HTML digest with paper cards, badges,
  and links, plus a plain-text fallback for all email clients.

---

## Prerequisites

- A **GitHub account** (free tier is fine).
- An **email account** with SMTP access. Gmail with an App Password is the
  easiest option (detailed below), but any SMTP provider works.
- Python 3.9+ (only needed if you want to run locally; GitHub Actions handles
  this automatically).

---

## Setup Guide

### Step 1 — Fork or push this repo

**Option A: Fork on GitHub**

1. Click the **Fork** button in the top-right corner of this repo's page.
2. This creates your own copy under `github.com/<your-username>/ArxivDaily`.
3. GitHub Actions workflows are paused on forks by default. Go to the
   **Actions** tab in your fork and click **"I understand my workflows, go
   ahead and enable them"**.

**Option B: Push a fresh copy**

```bash
git clone https://github.com/<original-owner>/ArxivDaily.git
cd ArxivDaily
git remote set-url origin https://github.com/<your-username>/ArxivDaily.git
git push -u origin main
```

### Step 2 — Create a Gmail App Password (or other SMTP credentials)

If you are using **Gmail** as your sending email, you need to generate an
App Password. Gmail blocks sign-ins from "less secure apps" by default, so a
regular password will not work.

1. **Enable 2-Step Verification** (required before you can create App Passwords):
   - Go to <https://myaccount.google.com/security>.
   - Under **"How you sign in to Google"**, click **2-Step Verification**.
   - Follow the prompts to turn it on (you will add a phone number or
     authenticator app).

2. **Generate an App Password**:
   - Go to <https://myaccount.google.com/apppasswords>.
   - You may be asked to sign in again.
   - In the **"App name"** field, type something like `ArxivDaily` and click
     **Create**.
   - Google will show a **16-character password** (formatted as `xxxx xxxx xxxx xxxx`).
   - **Copy this password immediately** — you will not be able to see it again.
   - When entering it as a GitHub secret, you can include or omit the spaces;
     both work.

3. **Important notes**:
   - If you don't see the App Passwords page, make sure 2-Step Verification
     is turned on first.
   - An App Password gives limited SMTP access — it cannot be used to sign in
     to your Google account on the web.
   - You can revoke the App Password at any time from the same page.

> **Not using Gmail?** See [SMTP Setup for Other Providers](#smtp-setup-for-other-providers) below.

### Step 3 — Add SMTP secrets to GitHub

GitHub Actions secrets keep your credentials encrypted and out of your code.
The workflow reads them at runtime as environment variables.

1. Go to your repo on GitHub.
2. Click **Settings** (the gear icon in the repo's top navigation bar).
3. In the left sidebar, click **Secrets and variables** → **Actions**.
4. Click the **"New repository secret"** button.
5. Add each of the following secrets **one at a time** (click "Add secret"
   after each):

| Secret name     | Value to enter              | Required? | Notes |
|-----------------|-----------------------------|-----------|-------|
| `SMTP_HOST`     | `smtp.gmail.com`            | Yes | The SMTP server hostname of your email provider. |
| `SMTP_PORT`     | `587`                       | Yes | Use `587` for STARTTLS (most providers), `465` for SSL. |
| `SMTP_USERNAME` | `you@gmail.com`             | Yes | Your full email address used to log in to the SMTP server. |
| `SMTP_PASSWORD` | `xxxx xxxx xxxx xxxx`       | Yes | Your Gmail App Password (from Step 2) or normal SMTP password. |
| `SMTP_FROM`     | `you@gmail.com`             | No  | The "From" address on the digest email. Defaults to `SMTP_USERNAME` if omitted. |
| `SMTP_SECURITY` | `starttls`                  | No  | One of `starttls` (default), `ssl`, or `none`. Leave blank for most providers. |

**Visual walkthrough:**

```
Your repo page
  → Settings (tab)
    → Secrets and variables (left sidebar)
      → Actions
        → "New repository secret" (green button)
          → Name: SMTP_HOST
          → Secret: smtp.gmail.com
          → "Add secret"
        (repeat for each secret)
```

After adding all secrets, your **Actions secrets** page should list:
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` (and optionally
`SMTP_FROM` and `SMTP_SECURITY`).

### Step 4 — Configure your keywords and recipients

Edit `config.json` in your repo. The two most important fields are:

```jsonc
{
  "keywords": [
    "large language model",
    "retrieval augmented generation",
    "diffusion model"
    // Add your own research topics here
  ],
  "recipients": [
    "your-email@example.com"
    // Add more email addresses to send the digest to multiple people
  ]
}
```

You can also customize the arXiv categories to search within:

```jsonc
{
  "categories": [
    "cs.LG",   // Machine Learning
    "cs.CL",   // Computation and Language (NLP)
    "cs.AI",   // Artificial Intelligence
    "cs.CV"    // Computer Vision
    // Full list: https://arxiv.org/category_taxonomy
  ]
}
```

Commit and push your changes:

```bash
git add config.json
git commit -m "configure keywords and recipients"
git push
```

### Step 5 — Test it

1. Go to the **Actions** tab in your GitHub repo.
2. In the left sidebar, click on the **ArxivDaily** workflow.
3. Click the **"Run workflow"** dropdown button (top right of the runs list).
4. Check the **"Render preview only, don't send email"** box for a safe first test.
5. Click **"Run workflow"**.

The run should complete in under 30 seconds. Click on the completed run to see
its logs and download the **arxiv-digest-preview** artifact — this is the HTML
email that would have been sent.

Once you're happy with the preview, run the workflow again **without** the
dry-run checkbox to send a real email. If it succeeds, you're all set — the
workflow will now run automatically at **08:00 UTC** and **20:00 UTC** every day.

---

## SMTP Setup for Other Providers

The toolkit works with any SMTP provider. Here are the settings for common ones:

### Outlook / Hotmail

| Secret           | Value                       |
|------------------|-----------------------------|
| `SMTP_HOST`      | `smtp-mail.outlook.com`     |
| `SMTP_PORT`      | `587`                       |
| `SMTP_USERNAME`  | `you@outlook.com`           |
| `SMTP_PASSWORD`  | Your account password (or App Password if 2FA is enabled) |
| `SMTP_SECURITY`  | `starttls`                  |

### Fastmail

| Secret           | Value                       |
|------------------|-----------------------------|
| `SMTP_HOST`      | `smtp.fastmail.com`         |
| `SMTP_PORT`      | `465`                       |
| `SMTP_USERNAME`  | `you@fastmail.com`          |
| `SMTP_PASSWORD`  | Generate at Settings → Privacy & Security → App Passwords |
| `SMTP_SECURITY`  | `ssl`                       |

### AWS SES (Simple Email Service)

| Secret           | Value                       |
|------------------|-----------------------------|
| `SMTP_HOST`      | `email-smtp.us-east-1.amazonaws.com` (use your region) |
| `SMTP_PORT`      | `587`                       |
| `SMTP_USERNAME`  | Your SES SMTP username (from IAM) |
| `SMTP_PASSWORD`  | Your SES SMTP password (from IAM) |
| `SMTP_SECURITY`  | `starttls`                  |

Note: Your "From" address must be verified in SES. Set `SMTP_FROM` to the
verified address if it differs from `SMTP_USERNAME`.

### Mailgun

| Secret           | Value                       |
|------------------|-----------------------------|
| `SMTP_HOST`      | `smtp.mailgun.org`          |
| `SMTP_PORT`      | `587`                       |
| `SMTP_USERNAME`  | `postmaster@your-domain.com` |
| `SMTP_PASSWORD`  | Your Mailgun SMTP password  |
| `SMTP_SECURITY`  | `starttls`                  |

---

## Configuration Reference

All settings live in `config.json`. Here is the full schema with defaults:

```jsonc
{
  // === Keywords (required) ===
  // Phrases to search for in paper titles and abstracts.
  // Matching is case-insensitive; hyphens and spaces are interchangeable
  // (e.g., "in-context learning" also matches "in context learning").
  "keywords": ["large language model", "..."],

  // === Categories (optional, default: all) ===
  // arXiv category codes to restrict the search.
  // Full taxonomy: https://arxiv.org/category_taxonomy
  "categories": ["cs.LG", "cs.CL", "cs.AI"],

  // === Recipients (required) ===
  // Email addresses that will receive the digest.
  "recipients": ["you@example.com"],

  // === Fetch settings ===
  "fetch": {
    "max_results_per_keyword": 30,   // max papers to retrieve per keyword query
    "lookback_days": 2,              // ignore papers older than this many days
    "sort_by": "submittedDate"       // "submittedDate", "lastUpdatedDate", or "relevance"
  },

  // === Ranking settings ===
  "ranking": {
    "max_papers_per_email": 25,      // cap on papers included in one digest
    "min_score": 1.0,                // papers below this score are dropped
    "title_weight": 3.0,             // multiplier for keyword hits in the title
    "abstract_weight": 1.0,          // multiplier for keyword hits in the abstract
    "multi_keyword_bonus": 0.5       // bonus per additional distinct keyword matched
  },

  // === Email template settings ===
  "email": {
    "from_name": "ArxivDaily",       // display name on the From header
    "from_address": "",              // From email; defaults to SMTP_FROM or SMTP_USERNAME
    "subject_template": "[ArxivDaily] {n_papers} new {papers} — {date}",
    //   Available placeholders: {n_papers}, {papers} ("paper"/"papers"), {date}
    "abstract_chars": 320,           // max characters of abstract to include
    "include_authors_max": 5         // show at most N authors (rest become "et al.")
  }
}
```

---

## How the Scoring Works

Each paper is scored as:

```
score = (title_weight x title_hits) + (abstract_weight x abstract_hits)
      + multi_keyword_bonus x (distinct_keywords_matched - 1)
```

Where `title_hits` and `abstract_hits` are the number of times any keyword
phrase appears (case-insensitively) in the title or abstract. The
`multi_keyword_bonus` rewards papers that match multiple different keywords.

Papers with a score below `min_score` are discarded. The remaining papers are
sorted by score (descending), then by update date (most recent first), and
the top `max_papers_per_email` are sent.

---

## How "Only on Update" Works

`state.json` holds a rolling list of arXiv paper IDs already sent (capped
at 5,000 entries). Each run:

1. Fetches today's matching papers from arXiv.
2. Subtracts any paper already in `seen_ids`.
3. If no new papers remain, the run exits without sending an email.
4. Otherwise, it sends the digest, adds the new IDs to `seen_ids`, and the
   GitHub Actions workflow automatically commits the updated `state.json`
   back to the repo.

Because the schedule polls twice a day, you get new papers shortly after
arXiv publishes them, and never receive the same paper twice.

---

## Local Development

You can run ArxivDaily on your own machine for testing and previewing.

### Install dependencies

```bash
pip install -r requirements.txt
```

### Preview without sending (dry run)

This renders the digest to `preview/preview.html` and `preview/preview.txt`
without sending any email or updating `state.json`:

```bash
python main.py --dry-run --verbose
```

Open `preview/preview.html` in your browser to see exactly what the email
would look like.

### Send a real email locally

Set the SMTP environment variables and run without `--dry-run`:

```bash
# Linux / macOS
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USERNAME="you@gmail.com"
export SMTP_PASSWORD="xxxx xxxx xxxx xxxx"
export SMTP_SECURITY="starttls"

python main.py --verbose
```

```powershell
# Windows (PowerShell)
$env:SMTP_HOST = "smtp.gmail.com"
$env:SMTP_PORT = "587"
$env:SMTP_USERNAME = "you@gmail.com"
$env:SMTP_PASSWORD = "xxxx xxxx xxxx xxxx"
$env:SMTP_SECURITY = "starttls"

python main.py --verbose
```

### Force resend (ignore seen papers)

```bash
python main.py --force --verbose          # send all top matches, even if seen before
python main.py --force --dry-run          # preview what would be resent
```

---

## CLI Options

| Flag               | Description |
|--------------------|-------------|
| `--dry-run`        | Render `preview/preview.html` and `preview/preview.txt` but do not send email and do not update `state.json`. |
| `--force`          | Resend all top-ranked papers, even if they are already in `state.json`'s `seen_ids`. |
| `--no-save-state`  | Skip writing to `state.json` after the run (useful for debugging). |
| `-v` / `--verbose` | Enable debug-level logging for more detailed output. |

Flags can be combined. For example, `--force --dry-run` previews all current
top matches regardless of what has been sent before.

---

## File Layout

```
.
├── .github/workflows/
│   └── arxiv_daily.yml         # GitHub Actions workflow (scheduled + manual trigger)
├── config.json                 # Your keywords, categories, recipients, and settings
├── state.json                  # Auto-updated by the workflow (tracks seen paper IDs)
├── main.py                     # CLI entry point — orchestrates the full pipeline
├── requirements.txt            # Python dependencies (arxiv, feedparser)
├── preview/                    # Generated email previews (git-ignored in production)
│   ├── preview.html
│   └── preview.txt
└── src/
    ├── __init__.py             # Package init (version string)
    ├── arxiv_fetcher.py        # arXiv API queries and Paper dataclass
    ├── email_sender.py         # HTML/text rendering + SMTP transport
    ├── relevance.py            # Keyword scoring and ranking logic
    └── state.py                # seen_ids persistence and deduplication
```

---

## Troubleshooting

### "Missing required SMTP environment variables: SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD"

You haven't added the secrets to your GitHub repo yet, or the secret names
have a typo. Go to **Settings → Secrets and variables → Actions** and verify
each secret is present and named exactly as shown (all uppercase, underscores).

### Gmail: "Username and Password not accepted" (error 535)

This means Gmail rejected your credentials. Common causes:

- You used your regular Gmail password instead of an **App Password**.
  Follow [Step 2](#step-2--create-a-gmail-app-password-or-other-smtp-credentials)
  to generate one.
- The App Password was revoked or expired. Generate a new one.
- `SMTP_USERNAME` must be your full email address (e.g., `you@gmail.com`),
  not just the username part.

### Gmail: "Please log in via your web browser" (error 534)

This error occurs when 2-Step Verification is not enabled. Google requires it
before you can use App Passwords. Enable it at
<https://myaccount.google.com/security>.

### The workflow runs but no email arrives

Check the workflow logs in **Actions → ArxivDaily → (latest run)**:

- **"no new matching papers — skipping email"** — ArxivDaily found papers but
  they were all in `seen_ids` from a previous run. Try running with the
  **force** option to resend.
- **"0 papers passed scoring threshold"** — None of the fetched papers matched
  your keywords well enough. Try lowering `min_score` in `config.json` or
  adding broader keywords.
- **"fetched 0 unique papers"** — No papers were found in your categories
  within the lookback window. Try increasing `lookback_days` or adding more
  categories.

Also check your spam/junk folder — automated emails sometimes land there the
first time.

### The workflow does not run on schedule

- On **forked repos**, scheduled workflows are disabled by default. Go to the
  **Actions** tab and enable them.
- GitHub may delay or skip scheduled runs if Actions is under heavy load.
  Runs are guaranteed to execute but may be delayed by a few minutes.
- If the repo has had no activity (commits, issues, PRs) for **60 days**,
  GitHub automatically disables scheduled workflows. Push any commit to
  re-enable them.

### state.json is not being committed back

The workflow only commits `state.json` when at least one new paper was sent.
If you see `state.json unchanged, nothing to commit` in the logs, that is
normal — it means no new papers were found in that run.

### "Connection refused" or timeout errors

Verify that `SMTP_HOST` and `SMTP_PORT` are correct for your provider. Common
mismatches: using port `465` with `starttls` (should be `ssl`) or port `587`
with `ssl` (should be `starttls`).

---

## Cost

GitHub Actions is **free for public repositories** (unlimited minutes). For
private repos, the free tier provides 2,000 minutes per month. Each ArxivDaily
run takes under 30 seconds, so even with twice-daily scheduling you use about
1 minute per day — well within any plan's limits.
