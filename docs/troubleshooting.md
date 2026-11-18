# Troubleshooting

**Start with the run summary.** Every run writes a short report: open the
**Actions** tab, click the latest **ArxivDaily** run, and read the summary at
the top. It says what was checked, what matched, what was sent, and, if
something failed, what to change. The messages below are quoted exactly as
they appear there, so you can search this page for the one you see.

- [No email arrived](#no-email-arrived)
- [Email setup errors](#email-setup-errors)
- [config.json errors](#configjson-errors)
- [arXiv errors](#arxiv-errors)
- [The schedule doesn't run](#the-schedule-doesnt-run)
- [Too many or too few papers](#too-many-or-too-few-papers)
- [Web archive problems](#web-archive-problems)

---

## No email arrived

1. **Check your spam folder.** The first digest sometimes lands there. Mark it
   as *not spam* and future ones will arrive normally.
2. **Check the run.** A green ✓ with the heading **No new papers this time**
   is normal on many days. The summary says why:
   - *arXiv's latest feed has no papers in your categories (normal on weekends
     and holidays).* arXiv doesn't announce papers on Friday and Saturday
     evenings (US Eastern), so there's no digest on Saturday or Sunday.
   - *None of the 742 papers matched your topics.* Your keywords are narrow
     today; see [too few papers](#too-many-or-too-few-papers).
   - *All 31 matching papers were emailed before.* Today's papers already went
     out in an earlier run.
3. **A red ✗ means it failed.** Click the run; the summary explains the cause.
   The sections below cover each message.
4. **Want a fresh email now?** Run the workflow with **resend latest papers**.
   That sends the current top matches even if you've received them before.

## Email setup errors

### Email isn't set up yet: missing SMTP_USERNAME and SMTP_PASSWORD

The two required secrets aren't there, or their names are spelled
differently. Open **Settings → Secrets and variables → Actions** and check
that both exist, written exactly like this, in capitals. Note that
*Variables* is a different tab: these must be **Secrets**.

### smtp.gmail.com rejected the username or password (535)

The mail server didn't accept the login. In order of likelihood:

- `SMTP_PASSWORD` is your normal password. It must be an **app password**;
  see [step 2 of the setup guide](setup-guide.md#2-get-an-app-password).
- `SMTP_USERNAME` isn't the full address: use `you@gmail.com`, not `you`.
- The app password was revoked, or you changed your account password (which
  revokes app passwords). Create a new one and update the secret.
- Gmail only: 2-Step Verification is off. App passwords stop working when it's
  turned off.

### Microsoft no longer accepts passwords or app passwords for SMTP on Outlook.com/Hotmail accounts

Personal Outlook.com, Hotmail and Live accounts can't send mail from apps
like ArxivDaily any more. Send from another account (Gmail works well) and
keep receiving at your Outlook address by putting it in the `MAIL_TO` secret.
Microsoft 365 work and university accounts are heading the same way: if you
see *no longer accepts passwords for sending*, do the same.

### Can't tell which mail server to use for @example.edu

Your provider isn't one ArxivDaily recognises. Add an `SMTP_HOST` secret with
its SMTP server, which your provider's help pages or your IT department can
tell you (for example `smtp.example.edu`). Add `SMTP_PORT` too if it isn't 587.

### Can't find the mail server 'smtp.example.com'

The server name in `SMTP_HOST` doesn't exist, usually because of a typo.
Copy it again from your provider's help pages.

### Couldn't connect to smtp.example.com:587

The server name or port is wrong, or the server blocks connections from
outside its network (some universities do). Check `SMTP_HOST` and `SMTP_PORT`
against your provider's settings. If your IT department only allows sending
from campus, send from a Gmail account instead.

### Encryption handshake with smtp.example.com:465 failed

The port and the encryption don't fit together: port 465 expects SSL, port
587 expects STARTTLS. Delete the `SMTP_SECURITY` secret and ArxivDaily picks
the right one from the port.

### smtp.example.com refused the From address

Most providers only let you send as yourself. Delete the `SMTP_FROM` secret
and the `email.from_address` setting (or set it to your own address).

### smtp.example.com didn't accept the message

ArxivDaily signed in, but the server refused the email itself. The code and
text in brackets are the server's own reason; it's usually a spam filter or a
daily sending limit. Try **send test email** again later. If it keeps
happening, send from another account (Gmail works well).

### Nobody to send the digest to

`SMTP_USERNAME` isn't an email address (some providers use a user name), so
ArxivDaily doesn't know where to deliver. Add a `MAIL_TO` secret with your
address.

### The MAIL_TO secret contains an entry that isn't an email address

Each entry must be a full address such as `ada@uni.edu`, and entries are
separated by commas: `ada@uni.edu, alan@lab.org`. Open **Settings → Secrets
and variables → Actions**, click the pencil icon next to `MAIL_TO`, and enter
the corrected list. (A saved secret can't be viewed, only replaced.)

### Some recipients didn't get the digest

The mail server refused some of the addresses in `MAIL_TO`, usually because
of a typo. Everyone else got the digest as normal.

## config.json errors

When `config.json` has a problem, the commit that introduced it gets a red ✗,
and the run points at the line. Common messages:

| Message | Fix |
|---|---|
| *config.json is not valid JSON (line 4, column 5: Expecting ',' delimiter)* | A comma is missing at the end of the previous line. |
| *Expecting property name enclosed in double quotes* | A setting name has no quotes, or single quotes: write `"keywords"`, not `'keywords'`. |
| *Expecting value* | A value is missing, or text is in single quotes: write `"cs.LG"`, not `'cs.LG'`. |
| *Replace the curly quotes (“ ” ‘ ’) with straight double quotes* | Your editor turned `"` into `“`. Retype the quotes. |
| *The file ends too early* | A closing `}` or `]` is missing, often the very last `}`. |
| *Unknown arXiv category "cs.lg". Did you mean "cs.LG"?* | Category codes are case-sensitive; copy them from the [taxonomy](https://arxiv.org/category_taxonomy). |
| *Add at least one entry to "keywords"* | The keyword list is empty. |
| *Unknown setting "ranking.max_paper_per_email" is ignored. Did you mean "max_papers_per_email"?* | A warning, not an error: fix the spelling to make the setting take effect. |
| *"email.subject_template" has an unknown placeholder* | Only `{n_papers}`, `{papers}` and `{date}` can be used. |

## arXiv errors

### Couldn't get papers from arXiv: rate limit reached (HTTP 429)

arXiv was too busy to answer, even after several polite retries. This is
usually temporary: the catch-up run later in the day tries again and sends
anything that hasn't gone out yet. If it happens every day, look at
`fetch.source`: the default `"auto"` relies mostly on arXiv's RSS feed, which
is much less affected by rate limits than `"api"`.

### Couldn't get papers from arXiv: could not connect

arXiv or the network was down. As above, the next run retries automatically.

## The schedule doesn't run

- **Workflows aren't enabled in your fork.** Open the **Actions** tab. If you
  see *Workflows aren't being run on this forked repository*, click the button
  to enable them.
- **The workflow was disabled after 60 days.** GitHub pauses scheduled
  workflows in public repositories that have had no commits for 60 days.
  ArxivDaily's own history commits normally prevent this, but if your topics
  matched nothing for two months, it can happen. Open **Actions →
  ArxivDaily** and click **Enable workflow**.
- **Runs start late.** GitHub's scheduler often starts runs a few minutes
  late, and later still when it's busy. That's expected.
- **Times look off.** Cron times are in UTC. See
  [Delivery time](configuration.md#delivery-time) for a conversion table.

## Too many or too few papers

**Too many:** make keywords more specific ("speculative decoding" rather
than "decoding"), raise `ranking.min_score` to `3` so a paper needs its
keyword in the title or several mentions in the abstract, set
`fetch.include_cross_lists` to `false`, or lower
`ranking.max_papers_per_email`.

**Too few:** add synonyms and acronyms as separate keywords ("RAG" next to
"retrieval augmented generation"), add neighbouring categories, or check the
run summary's *Matched your topics* count against *Papers checked*. Run the
workflow with **preview only (no email)** after each change to see the effect
right away.

## Web archive problems

### The run summary's *Web archive* row says "Off"

GitHub Pages isn't enabled for **GitHub Actions**. Open **Settings → Pages**
and set **Source** to **GitHub Actions** (not *Deploy from a branch*), then run
the workflow once.

### The page says "No papers here yet"

The archive fills in after the first run that finds new papers. To fill it
right away, run the workflow with **resend latest papers**; that also emails
you the latest matches again.

### The page is out of date

It isn't for long: the page checks for new papers every five minutes, and
whenever you return to the tab. New papers appear behind a **Show N new papers**
button at the top. If the archive itself didn't change, look at the latest run
in the Actions tab: on scheduled runs, the *Publish web archive* job runs only
when there was something new to add.

### "This archive was copied along with the repository"

Your fork still contains the original repository's archive. It's replaced by
your own as soon as ArxivDaily first emails you.
