# Changelog

## 2.0.0 (2026-11-18)

A rework focused on reliability and easier setup. Existing forks keep working
after updating; see [Upgrading from 1.x](#upgrading-from-1x).

### Fixed

- **Every run failed.** `main.py` contained a duplicated fragment after its last
  line, which made it a Python syntax error, so the workflow crashed before
  doing anything.
- **Most matching papers were missed.** Keywords only matched their exact
  form, so `"diffusion model"` never matched *diffusion models*. Measured on
  four real announcement days (9, 10, 11 and 13 November 2026) with the
  default topics, version 1 found 206 of the 539 matching papers and missed
  the other 62%.
  Singular and plural forms now both match.
- **arXiv outages looked like quiet days.** When arXiv refused requests (it
  rate-limits its API heavily), runs reported "no new papers" and stayed green.
  Requests are now retried with backoff, fall back to a second source, and
  fail with a clear message if arXiv stays unreachable.
- **Weekend papers could be skipped.** The two-day window missed papers
  submitted before a weekend. The daily feed now determines what's new.
- **The 20:00 UTC run almost never found anything**, because it ran before
  arXiv's 20:00 US Eastern announcement. The schedule now follows arXiv's
  feed refresh.
- **Recipients could see each other's addresses**, and the template shipped
  with a real address in `recipients`, so a fork that didn't change it would
  email a stranger. Each recipient now gets a separate copy (if one address
  is refused, the others still get theirs), and the default is your own
  address.
- **Pushing the history could fail** if you committed while a run was in
  progress. The workflow now rebases and retries.
- A paper without a PDF link crashed the email; author names with LaTeX
  accents (`Ra\'ul`) and affiliations are cleaned up; emails now carry a `Date`
  header, which some spam filters require.

### Added

- **Two-secret setup.** The mail server, port and encryption are detected from
  your address for Gmail, iCloud, Yahoo, QQ, 163, Zoho, Fastmail and more.
- **A Run workflow menu:** *send digest*, *send test email*, *preview only*,
  and *resend latest papers*.
- **Run summaries** on each run's page: what was checked, matched and sent,
  plus clear next steps when something needs fixing.
- **Instant feedback on config.json.** Committing a change runs a check and a
  preview. Mistakes show up as a red ✗ with the exact line, column and a
  suggested fix (including "did you mean" for misspelled settings and
  category codes). Comments and trailing commas are tolerated.
- **A redesigned email** that renders consistently in Gmail, Outlook, Apple
  Mail and on phones. Matched keywords are highlighted in a colour per topic,
  and excerpts always show why a paper matched.
- **An optional web archive** on GitHub Pages: search, topic filters, dark
  mode and phone layout. It picks up new papers on its own, loads older days as
  you scroll, and remembers your place, so there's no need to refresh.
- `MAIL_TO` secret for private recipient lists; `--test-email`, `--check` and
  `--serve` commands; `.env` support for local runs; precise error messages
  for common SMTP problems (app passwords, ports, Outlook's shutdown of SMTP
  passwords).
- Settings `fetch.source`, `fetch.include_cross_lists`,
  `fetch.include_revisions` and the `archive` section.
- A test suite (offline, using saved real arXiv feeds) and a workflow that runs
  it on Python 3.9 and 3.13.
- New documentation: setup guide, configuration reference, troubleshooting and
  local usage.

### Changed

- No third-party packages are needed any more (the `arxiv` and `feedparser`
  packages were replaced by the standard library).
- Papers that matched but didn't fit in an email are no longer carried over
  into the next day's email. They appear in the web archive instead.
- The preview files are now `preview/email.html` and `preview/email.txt`.
- GitHub Actions were updated to their current versions (Node 24).

### Upgrading from 1.x

1. Update your fork (**Sync fork → Update branch**), keeping your own
   `config.json` if GitHub asks.
2. Optional: move the addresses from `recipients` in `config.json` into a
   `MAIL_TO` secret, so they're no longer public, and empty the list.
3. Optional: delete the `SMTP_HOST`, `SMTP_PORT` and `SMTP_SECURITY` secrets
   if you use one of the auto-detected providers.
4. `fetch.max_results_per_keyword` (now `fetch.max_results`) and
   `fetch.sort_by` no longer have any effect. ArxivDaily ignores them and
   reminds you that you can delete them.
5. If your `config.json` still has `"lookback_days": 2`, raise it to `5` or
   delete the line. It only matters when ArxivDaily falls back to arXiv's
   search API, but two days miss papers submitted before a weekend.
