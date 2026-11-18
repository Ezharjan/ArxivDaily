# Setup guide

This guide takes you from nothing to a working daily digest in about five
minutes. You don't need to install anything or write any code; everything
happens on github.com and in your email account's settings.

**You'll need:** a free GitHub account, and an email account to send the
digest from. Gmail is the simplest; most other providers work too (see
[step 2](#2-get-an-app-password)).

**The steps:**

1. [Copy ArxivDaily to your GitHub account](#1-copy-arxivdaily-to-your-github-account)
2. [Get an app password](#2-get-an-app-password)
3. [Add your secrets](#3-add-your-secrets)
4. [Choose your topics](#4-choose-your-topics)
5. [Send a test email](#5-send-a-test-email)
6. [Optional: turn on the web archive](#6-optional-turn-on-the-web-archive)

> [!TIP]
> The links on this page that point into *Settings* or *Actions* open those
> pages in **your** copy of the repository, as long as you're reading this
> page in your fork.

---

## 1. Copy ArxivDaily to your GitHub account

1. On the ArxivDaily repository page, click **Fork** (top right), then
   **Create fork**. You now have your own copy at
   `github.com/<your-username>/ArxivDaily`.
2. In your fork, click the **Actions** tab. GitHub pauses workflows in new
   forks, so you'll see a notice: click **I understand my workflows, go ahead
   and enable them**.

That's the only time you need to do this. Your fork runs on its own from now
on, using GitHub's free Actions minutes.

<details>
<summary><b>Prefer a private repository?</b></summary>

Forks of public repositories are public. Your topics are visible, but your
email address and password never are, because they live in secrets. If you'd
rather keep everything private:

1. Open [github.com/new/import](https://github.com/new/import).
2. Paste the address of the ArxivDaily repository, choose a name, select
   **Private**, and click **Begin import**.
3. Continue with step 2 below. You don't need to enable Actions separately in
   an imported repository.

Private repositories get 2,000 free Actions minutes a month; ArxivDaily uses
about 60 to 120. The optional web archive (GitHub Pages) needs a paid GitHub
plan in private repositories.

</details>

## 2. Get an app password

ArxivDaily signs in to your email account to send you the digest. For your
security, most providers don't let apps use your normal password. Instead you
create an *app password*: a separate password for apps like this one. It
can't be used to sign in to your account on the web, and you can revoke it at
any time.

### Gmail

1. Open [myaccount.google.com/security](https://myaccount.google.com/security)
   and make sure **2-Step Verification** is on. Google only offers app
   passwords once it is.
2. Open [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
   You may be asked to sign in again.
3. Type `ArxivDaily` as the app name and click **Create**.
4. Google shows a 16-letter password such as `abcd efgh ijkl mnop`. Copy it now;
   Google won't show it again. (If you lose it, just delete it and create a new one.)

<details>
<summary><b>iCloud Mail</b> (@icloud.com, @me.com, @mac.com)</summary>

1. Sign in at [account.apple.com](https://account.apple.com). Two-factor
   authentication must be on for your Apple Account.
2. Open **Sign-In and Security → App-Specific Passwords**, click **Generate**,
   and name it `ArxivDaily`.
3. Copy the password. Use your full iCloud address as `SMTP_USERNAME`.

</details>

<details>
<summary><b>Yahoo Mail</b> and <b>AOL</b></summary>

1. Open your account's **Account security** page.
2. Choose **Generate app password** (sometimes listed under *Other ways to
   sign in*), name it `ArxivDaily`, and copy the password.

</details>

<details>
<summary><b>QQ Mail</b> (QQ邮箱, including Foxmail) and <b>163 / 126 / Yeah.net</b> (网易邮箱)</summary>

These providers call the app password an **authorization code (授权码)**.

- **QQ Mail:** open **Settings (设置) → Account (账户)**, find
  **POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV service**, turn on the
  **POP3/SMTP** or **IMAP/SMTP** service, verify by text message, and copy the
  authorization code that appears.
- **163 / 126 / Yeah.net:** open **Settings (设置) → POP3/SMTP/IMAP**, turn on
  **SMTP**, verify, and copy the authorization code (授权密码).

Use the authorization code as `SMTP_PASSWORD` and your full address as
`SMTP_USERNAME`.

</details>

<details>
<summary><b>Zoho, Fastmail, GMX, Yandex</b></summary>

All of these work, and the mail server is detected automatically.

- **Zoho, Fastmail, Yandex:** create an app-specific password in your account's
  security settings and use it as `SMTP_PASSWORD`.
- **GMX:** first turn on *POP3/IMAP access* in GMX's settings. Then use your
  GMX password, or an app-specific password if you've turned on two-factor
  authentication.

</details>

<details>
<summary><b>Outlook.com, Hotmail, Live</b>: can't send, but can receive</summary>

Microsoft switched off password sign-in (including app passwords) for SMTP on
personal Outlook.com accounts in September 2024, so ArxivDaily can't **send**
from them. You can still **receive** the digest there: send from a Gmail
account and put your Outlook address in the `MAIL_TO` secret.

</details>

<details>
<summary><b>University or work email</b></summary>

Ask your IT department for the SMTP server name and port, and whether "SMTP
authentication" is allowed for your account. Then add `SMTP_HOST` (and
`SMTP_PORT` if it isn't 587) as extra secrets in step 3.

Microsoft 365 accounts (many universities use them) are being moved away from
password-based SMTP; Microsoft disables it by default at the end of 2026. If
yours is one of them, send from a Gmail account and receive at your
university address via `MAIL_TO`.

</details>

## 3. Add your secrets

Secrets are encrypted settings that only your workflow can read. Nobody else
can see them, including visitors to your public repository, and they never
appear in logs.

1. In your fork, open **Settings → Secrets and variables → Actions**
   ([open it](../../../settings/secrets/actions)).
2. Click **New repository secret**.
3. Enter the **Name** and the **Secret** from the table below, then click
   **Add secret**. Repeat for the second one.

| Name | Secret | |
|---|---|---|
| `SMTP_USERNAME` | Your full email address, e.g. `ada.lovelace@gmail.com` | **required** |
| `SMTP_PASSWORD` | The app password from step 2. Spaces don't matter. | **required** |
| `MAIL_TO` | Who should receive the digest, if not you: `me@uni.edu, colleague@lab.org` | optional |
| `SMTP_HOST` | Your provider's SMTP server. Only needed if it isn't detected automatically. | optional |
| `SMTP_PORT` | Only needed if your provider uses an unusual port (the usual ones are `587` and `465`). | optional |

Names must be typed exactly as shown, in capitals. You can't view a secret
after saving it, but you can always replace it with the pencil icon next to
its name.

<details>
<summary>Which providers are detected automatically?</summary>

Gmail, Googlemail, iCloud (icloud.com, me.com, mac.com), Yahoo, AOL, QQ Mail,
Foxmail, 163, 126, Yeah.net, Zoho (.com, .eu), Fastmail, GMX and Yandex. For
these, `SMTP_USERNAME` and `SMTP_PASSWORD` are all you need. Everyone else adds
`SMTP_HOST`. The port then defaults to 587, and the encryption follows from the
port (465 means SSL, anything else STARTTLS) unless you set `SMTP_PORT` or
`SMTP_SECURITY` yourself.

</details>

## 4. Choose your topics

Your topics live in `config.json`, which you can edit right on GitHub:

1. In your fork, click **config.json** ([open it](../config.json)), then the
   pencil icon (**Edit this file**).
2. Replace the example `keywords` with phrases from your field, and the
   `categories` with the [arXiv categories](https://arxiv.org/category_taxonomy)
   you follow. For example:

   ```json
     "keywords": [
       "graph neural network",
       "molecular generation",
       "protein structure prediction",
       "GNN"
     ],
     "categories": ["cs.LG", "q-bio.BM", "physics.chem-ph"],
   ```

3. Click **Commit changes…**, then **Commit changes**.

A minute later, the commit shows a green ✓ if all is well. If something is
wrong, say a missing comma, it shows a red ✗ instead. Click it, then
**Details**, and you'll see the exact line and what to change. The same run
also previews which of arXiv's latest papers match your new topics.

**Tips for good keywords**

- Use the phrases people actually put in titles: `"contrastive learning"`
  rather than `"learning"`.
- Don't worry about capitals, hyphens or plurals: `"vision transformer"`
  already matches *Vision-Transformers*.
- Add common acronyms as their own keywords, e.g. both
  `"retrieval augmented generation"` and `"RAG"`.
- Start with 3 to 10 keywords. You can always tune them after a few digests.

All other settings are optional; the [configuration reference](configuration.md)
explains each of them.

## 5. Send a test email

1. Open the **Actions** tab ([open it](../../../actions/workflows/arxiv_daily.yml)) and
   click **ArxivDaily** in the list on the left.
2. Click **Run workflow** (on the right), choose **send test email**, and
   click the green **Run workflow** button.
3. After a minute or two the run turns green. Open it to see a short summary,
   then check your inbox for **ArxivDaily test: your email setup works**.

The test email repeats your settings and shows a few recent matching papers
in the same layout as the real digest. If it doesn't arrive, look in your
spam folder first, then at the run's summary. A red run tells you exactly what
went wrong; see [Troubleshooting](troubleshooting.md).

## 6. Optional: turn on the web archive

ArxivDaily can publish a page where you can browse and search everything it
has found, at `https://<your-username>.github.io/ArxivDaily/`.

1. Open **Settings → Pages** ([open it](../../../settings/pages)).
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Run the workflow once (step 5, any option). The run page shows the
   address of your archive when it's done.

From then on, every run that finds new papers updates the archive. The page
refreshes itself, so you never need to reload it.

---

## What happens next

- **Every day** ArxivDaily runs at 06:23 UTC, after arXiv's nightly update.
  When new papers match your topics, you get one email with the most relevant
  ones.
- **On weekends** there's no email: arXiv makes no announcements on Friday
  and Saturday evenings, so its feed is empty on Saturday and Sunday.
- **A second run** at 14:23 UTC catches up if the morning run failed. It never
  sends a paper twice.
- **Each run** leaves a summary on its page in the Actions tab, and commits an
  updated `state.json` whenever it emails new papers. These small commits are
  normal: they're how ArxivDaily remembers what you've received.

Want the email at a different time? See
[Delivery time](configuration.md#delivery-time).

## Keeping ArxivDaily up to date

When a new version of ArxivDaily comes out, open your fork on GitHub and click
**Sync fork → Update branch**. Your `config.json`, secrets and history are
kept. If GitHub reports a conflict, it's almost always in `config.json`
because you changed it and the original did too. Choose **Open pull request**
and keep your own version of that file.
