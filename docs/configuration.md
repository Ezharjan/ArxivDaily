# Configuration reference

ArxivDaily has two kinds of settings:

- **`config.json`**: what to look for and how the digest looks. It's a normal
  file in your repository; edit it on GitHub with the pencil icon.
- **Repository secrets**: your email login and recipients. They're private and
  are set under *Settings → Secrets and variables → Actions*.

Only `keywords` is required. Every other setting has a default, so a complete
`config.json` can be as short as:

```json
{
  "keywords": ["diffusion model", "score matching"],
  "categories": ["cs.LG", "stat.ML"]
}
```

ArxivDaily checks `config.json` every time you commit it. Mistakes are reported
with the line number and a suggestion, for example *Unknown setting
"ranking.max_paper_per_email" is ignored. Did you mean "max_papers_per_email"?*
Comments (`// like this`) and a stray trailing comma are tolerated.

---

## Topics

### `keywords` (required)

A list of phrases to look for in each paper's title and abstract.

```json
"keywords": ["large language model", "LLM", "in-context learning"]
```

Matching is forgiving where it should be and strict where it matters:

| Rule | Example: keyword `"diffusion model"` |
|---|---|
| Capitals don't matter | matches *Diffusion Model* |
| Hyphens, spaces and slashes are interchangeable | matches *diffusion-model* |
| Singular and plural both match | matches *Diffusion Models* |
| Whole words only | `"gpt"` doesn't match *Egypt* or *ChatGPT* |

Each keyword gets its own highlighter colour in the email and the web archive,
in the order you list them (six colours, then they repeat).

### `categories`

Default: `[]` (all of arXiv)

The [arXiv categories](https://arxiv.org/category_taxonomy) to watch, such as
`"cs.CV"` or `"astro-ph.GA"`. You can also give a whole archive, e.g.
`"physics"` or `"math"`. Papers cross-listed *into* these categories are
included too (see `fetch.include_cross_lists`).

Category codes are case-sensitive. ArxivDaily knows the full list and suggests
the right spelling if you mistype one (`cs.lg` becomes "Did you mean `cs.LG`?").

With no categories, ArxivDaily can't use arXiv's daily feed (which is organised
by category) and searches all of arXiv through the API instead.

### `recipients`

Default: `[]`

Email addresses that receive the digest. **Prefer the `MAIL_TO` secret**
instead: `config.json` is public in a public repository, and spam bots harvest
addresses from GitHub. Who gets the digest is decided in this order:

1. the `MAIL_TO` secret, if it's set;
2. otherwise `recipients` in `config.json`;
3. otherwise your own address (`SMTP_USERNAME`).

Every recipient gets a separate copy, so nobody sees the other addresses.

## Fetching: `fetch`

| Setting | Default | What it does |
|---|---|---|
| `source` | `"auto"` | Where papers come from. `"auto"` reads arXiv's daily RSS feed for your categories and falls back to the search API if the feed is unavailable (or unexpectedly empty on a weekday). `"rss"` uses only the feed; `"api"` uses only the search API. |
| `include_cross_lists` | `true` | Include papers from other categories that the authors cross-listed into yours. |
| `include_revisions` | `false` | Also include new versions of older papers (arXiv's "replacements"). |
| `lookback_days` | `5` | API only: how many days back to search, by submission date. The papers you get on a Monday were submitted as early as Thursday afternoon, so five days covers a weekend plus a holiday. Papers you've already received are skipped, so a longer window does no harm. |
| `max_results` | `500` | API only: the most papers to fetch per run (per group of 10 keywords, if you have more). |

**RSS or API?** The RSS feed lists exactly the papers in arXiv's latest
announcement, comes in one request, and is the most reliable choice, so
`"auto"` uses it. The API is a search engine: useful for weekly digests or for
following all of arXiv, but it limits how often you can query it. When it's
busy, ArxivDaily waits and retries automatically.

## Ranking: `ranking`

| Setting | Default | What it does |
|---|---|---|
| `max_papers_per_email` | `25` | How many of the best matches go into one email. The rest go to the web archive, if it's on. |
| `min_score` | `1.0` | Papers scoring below this are skipped. |
| `title_weight` | `3.0` | Points for each keyword occurrence in the title. |
| `abstract_weight` | `1.0` | Points for each keyword occurrence in the abstract. |
| `multi_keyword_bonus` | `0.5` | Extra points for each additional distinct keyword a paper matches. |

The score of a paper is:

```
score = title_weight × (keyword hits in title)
      + abstract_weight × (keyword hits in abstract)
      + multi_keyword_bonus × (number of different keywords matched − 1)
```

So with the defaults, a single mention in the abstract scores 1.0, enough to
be included, while a keyword in the title scores at least 3.0. To keep only
papers that are clearly about your topics, set `min_score` to `3`: then a
paper needs its keyword in the title, or several mentions in the abstract.

## The email: `email`

| Setting | Default | What it does |
|---|---|---|
| `subject_template` | `"[ArxivDaily] {n_papers} new {papers} — {date}"` | The subject line. Placeholders: `{n_papers}` (a number), `{papers}` ("paper" or "papers"), `{date}` (e.g. 2026-11-13). |
| `from_name` | `"ArxivDaily"` | The sender name shown in your inbox. |
| `from_address` | `""` | The sender address. Leave empty to use `SMTP_USERNAME`; most providers refuse any other address. |
| `abstract_chars` | `320` | How much of each abstract to show (`0` shows all of it). If a paper's keyword only appears later in its abstract, the excerpt starts at that sentence instead. |
| `include_authors_max` | `5` | Show at most this many authors, then "and N more" (`0` shows all). |

## The web archive: `archive`

Used only when the [web archive](../README.md#web-archive-optional) is on.

| Setting | Default | What it does |
|---|---|---|
| `keep_days` | `90` | How many days of papers to keep. |
| `max_papers_per_day` | `200` | The most papers stored per announcement day, best first. |

With broad topics, each announcement day takes about 200 KB, so 90 days is
roughly 15 MB in your repository. Lower these numbers for a smaller footprint.

## Secrets

Set under *Settings → Secrets and variables → Actions → New repository secret*.

| Secret | Required | What it is |
|---|---|---|
| `SMTP_USERNAME` | yes | Your full email address, used to sign in to the mail server. |
| `SMTP_PASSWORD` | yes | An app password (see the [setup guide](setup-guide.md#2-get-an-app-password)). Never your normal password. |
| `MAIL_TO` | no | Recipients, separated by commas. Default: `SMTP_USERNAME`. |
| `SMTP_HOST` | no | The SMTP server, e.g. `smtp.example.com`. Detected automatically for Gmail, iCloud, Yahoo, AOL, QQ, Foxmail, 163, 126, Yeah.net, Zoho, Fastmail, GMX and Yandex. |
| `SMTP_PORT` | no | `465` (SSL) or `587` (STARTTLS). Default: the provider's port, or 587. |
| `SMTP_SECURITY` | no | `ssl`, `starttls` or `none`. Default: worked out from the port. |
| `SMTP_FROM` | no | A different From address, if your provider allows it. |

## Delivery time

arXiv announces new papers **Sunday to Thursday at 20:00 US Eastern time**.
Its daily feed refreshes at midnight Eastern, which is 05:00 UTC in winter and
04:00 UTC in summer. ArxivDaily runs shortly after, at **06:23 UTC**, plus a
catch-up run at 14:23 UTC that sends something only if the first run missed it.

In your time zone, the 06:23 UTC run arrives at about:

| Time zone | Winter | Summer |
|---|---|---|
| San Francisco | 22:23 (previous evening) | 23:23 (previous evening) |
| New York | 01:23 | 02:23 |
| London | 06:23 | 07:23 |
| Berlin, Paris | 07:23 | 08:23 |
| India | 11:53 | 11:53 |
| Beijing, Singapore | 14:23 | 14:23 |
| Tokyo, Seoul | 15:23 | 15:23 |

To change it, edit the two `cron:` lines near the top of
`.github/workflows/arxiv_daily.yml`. A cron line is
`minute hour day-of-month month day-of-week`, always in UTC:

```yaml
on:
  schedule:
    - cron: "23 6 * * *"     # every day at 06:23 UTC
    - cron: "23 14 * * *"    # every day at 14:23 UTC (catch-up)
```

Keep the first run after 05:00 UTC, when the feed is fresh. Avoid minute `0`,
because GitHub delays runs at the top of the hour when it's busy. Scheduled
runs can start a few minutes late in any case.

<details>
<summary><b>Recipe: the earliest possible email</b></summary>

New papers reach the feed, and arXiv's search API, at midnight US Eastern
time: 05:00 UTC in winter, 04:00 UTC in summer. That's 13:00 in Beijing, so in
East Asia the digest can't arrive before early afternoon. To get it about an
hour sooner than the default, all year round:

```yaml
    - cron: "17 5 * * *"     # 05:17 UTC = 13:17 in Beijing, 06:17 in London
    - cron: "23 14 * * *"    # catch-up
```

If arXiv is late refreshing its feed, the catch-up run sends the papers instead.

</details>

<details>
<summary><b>Recipe: one weekly digest</b></summary>

Ten days back reaches every paper announced since the previous Monday's run;
anything you already received is skipped.

```json
"fetch": { "source": "api", "lookback_days": 10, "max_results": 1500 },
"ranking": { "max_papers_per_email": 50 }
```

```yaml
    - cron: "23 6 * * 1"    # Mondays at 06:23 UTC
```

</details>

## Example configurations

<details>
<summary>Computer vision</summary>

```json
{
  "keywords": ["vision transformer", "3D reconstruction", "gaussian splatting",
               "video generation", "open-vocabulary segmentation"],
  "categories": ["cs.CV", "cs.GR"]
}
```

</details>

<details>
<summary>Language models and NLP</summary>

```json
{
  "keywords": ["large language model", "LLM", "instruction tuning", "RLHF",
               "retrieval augmented generation", "RAG", "chain of thought"],
  "categories": ["cs.CL", "cs.LG", "cs.AI"],
  "ranking": { "min_score": 3 }
}
```

</details>

<details>
<summary>Quantum computing</summary>

```json
{
  "keywords": ["quantum error correction", "surface code", "variational quantum",
               "quantum advantage"],
  "categories": ["quant-ph", "cs.ET"]
}
```

</details>

<details>
<summary>Computational biology</summary>

```json
{
  "keywords": ["protein structure", "single-cell", "gene regulatory network", "drug discovery"],
  "categories": ["q-bio", "cs.LG"]
}
```

</details>
