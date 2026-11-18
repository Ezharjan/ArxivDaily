# Run ArxivDaily on your computer

You don't need this to use ArxivDaily; GitHub runs it for you. Running it
locally is handy for previewing the email while you tune your keywords, for
testing email settings, or for working on the code.

**Requirements:** Python 3.9 or newer. ArxivDaily uses only the standard
library, so there's nothing to `pip install`.

```bash
git clone https://github.com/<your-username>/ArxivDaily.git
cd ArxivDaily
```

On Windows, use `py` instead of `python` in the commands below if `python`
isn't found.

## Preview the email

```bash
python main.py --dry-run --open
```

This fetches arXiv's latest announcement, ranks it against your
`config.json`, writes the email to `preview/email.html` (and a plain-text
version next to it), and opens it in your browser. Nothing is sent and
`state.json` isn't touched, so you can run it as often as you like while
editing your keywords. On a weekend, when arXiv's daily feed is empty, the
preview shows the last few days' papers instead.

## Preview the web archive

```bash
python main.py --serve
```

This opens the archive page at <http://127.0.0.1:8000>, filled with your
current archive plus the papers that match in arXiv's latest announcement. It
works on a copy in `preview/site`, so your real archive in `web/data` isn't
changed. Press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop. If port 8000 is busy, it
uses the next free one, or you can choose with `--port 8080`.

## Send email from your computer

1. Copy `.env.example` to `.env` (in the same folder as `main.py`) and fill in
   `SMTP_USERNAME` and `SMTP_PASSWORD`. `.env` is listed in `.gitignore`, so it
   can't be committed by accident.
2. Check the settings. This logs in to your mail server without sending
   anything:

   ```bash
   python main.py --check
   ```

3. Send yourself a test email:

   ```bash
   python main.py --test-email
   ```

4. Run the real thing. This sends the digest and records the papers in
   `state.json`:

   ```bash
   python main.py
   ```

Instead of a `.env` file you can set the same names as environment variables;
those take precedence over `.env`.

> [!NOTE]
> Papers you receive from a local run are remembered only in your local
> `state.json`. If you also run ArxivDaily on GitHub, either commit and push
> `state.json` afterwards, or use `--no-save-state` for local runs, so you don't
> get the same papers twice.

## All commands

| Command | What it does |
|---|---|
| `python main.py` | Fetch, rank, email new papers, and remember them. |
| `python main.py --dry-run` | Build the preview without sending or saving anything. Add `--open` to open it. |
| `python main.py --test-email` | Send a test email with a few sample papers. |
| `python main.py --check` | Validate `config.json` and log in to the mail server. Sends nothing. |
| `python main.py --serve` | Preview the web archive in your browser. Options: `--port`, `--no-browser`. |
| `python main.py --force` | Include papers that were already sent. |
| `python main.py --no-save-state` | Send, but don't update `state.json`. |
| `python main.py -v` | Show more detail in the log. |

## Run the tests

```bash
python -m unittest discover -s tests
```

The tests use saved copies of real arXiv feeds and a small fake mail server,
so they run offline in a few seconds and never send real email.

## Project layout

```
.
├── config.json                  your topics and preferences
├── state.json                   papers already sent (updated by the workflow)
├── main.py                      command-line entry point
├── .env.example                 template for local email settings
├── .github/workflows/
│   ├── arxiv_daily.yml          the daily schedule and the Run workflow menu
│   └── tests.yml                runs the tests when the code changes
├── src/
│   ├── config.py                reads and checks config.json
│   ├── arxiv_fetcher.py         arXiv RSS feed and search API
│   ├── relevance.py             keyword matching and ranking
│   ├── email_render.py          the HTML and plain-text email
│   ├── email_sender.py          SMTP sending and provider detection
│   ├── state.py                 remembers which papers were sent
│   ├── archive.py               data for the web archive
│   ├── github_actions.py        run summaries and annotations on GitHub
│   ├── textutil.py              cleans LaTeX out of titles and names
│   └── taxonomy.py              arXiv's category list
├── web/
│   ├── index.html               the web archive page
│   └── data/                    archive data (created when the archive is on)
├── docs/                        these guides
└── tests/                       unit and end-to-end tests
```
