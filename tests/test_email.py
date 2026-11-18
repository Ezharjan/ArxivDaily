import datetime as dt
import re
import unittest

from support import env, fixture, smtp_env, smtp_server
from src import arxiv_fetcher as af
from src.email_render import DigestContext, excerpt, render_digest_html, render_digest_text
import smtplib

from src.email_sender import SetupError, SmtpConfig, _explain, send_all
from src.relevance import compile_keywords, score_and_rank

KW = ["large language model", "retrieval augmented generation", "diffusion model", "mixture of experts"]


def context(papers, **kw):
    kw.setdefault("total_matches", len(papers))
    return DigestContext(papers=papers, keywords=KW, day=dt.date(2026, 11, 13),
                         keyword_counts={k: 1 for k in KW}, categories=["cs.LG", "cs.CL"], **kw)


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        papers, _ = af.parse_rss(fixture("rss_2026-11-13_sample.xml"))
        cls.ranked = score_and_rank(papers, KW)

    def test_digest_html(self):
        html = render_digest_html(context(self.ranked[:5], total_matches=9), "subject")
        self.assertIn("5 new papers on your topics", html)
        self.assertIn("The 5 most relevant of 9 matches", html)
        self.assertIn("background-color:#", html)                          # highlighter marks
        self.assertIn('name="viewport"', html)
        self.assertNotIn("<script", html)
        self.assertIn("4 more papers matched your topics", html)

    def test_overflow_note_matches_in_html_and_text(self):
        for site, want in (("", "To get more per email, raise ranking.max_papers_per_email"),
                           ("https://ada.github.io/ArxivDaily/", "Browse them in the web archive")):
            ctx = context(self.ranked[:5], total_matches=9, site_url=site)
            visible = re.sub(r"<[^>]+>", "", render_digest_html(ctx, "s"))      # the HTML as a reader sees it
            self.assertIn("4 more papers matched your topics. " + want, visible)
            self.assertIn("4 more papers matched your topics. " + want, render_digest_text(ctx))

    def test_untrusted_text_is_escaped(self):
        p = af.Paper(short_id="2611.00001", version=1, title='<img src=x onerror="alert(1)"> diffusion model',
                     summary="a & b < c", authors=["<b>Eve</b>"], primary_category="cs.LG", categories=["cs.LG"])
        html = render_digest_html(context([p]), "s")
        self.assertNotIn("<img", html)
        self.assertNotIn("<b>Eve", html)
        self.assertIn("&lt;img", html)

    def test_size_stays_under_gmail_clipping_limit(self):
        long = "diffusion model " + "word " * 400
        papers = [af.Paper(short_id=f"2611.{i:05d}", version=1, title="Large language models " * 6,
                           summary=long, authors=[f"Author {j}" for j in range(30)], primary_category="cs.LG",
                           categories=["cs.LG", "cs.AI", "cs.CL"]) for i in range(25)]
        score_and_rank(papers, KW)
        html = render_digest_html(context(papers, total_matches=200, site_url="https://ada.github.io/ArxivDaily/",
                                          repo="ada/ArxivDaily", repo_url="https://github.com/ada/ArxivDaily",
                                          edit_config_url="https://github.com/ada/ArxivDaily/edit/master/config.json",
                                          workflow_url="https://github.com/ada/ArxivDaily/actions"), "s")
        self.assertLess(len(html.encode("utf-8")), 102 * 1024)

    def test_text_version(self):
        text = render_digest_text(context(self.ranked[:3]))
        self.assertIn("1. ", text)
        self.assertIn("https://arxiv.org/abs/", text)
        self.assertIn("Thank you to arXiv", text)

    def test_excerpt_keeps_the_match_visible(self):
        p = af.Paper(short_id="1", version=1, title="A title without the topic",
                     summary=("Background sentence. " * 30) + "We train a diffusion model here. More text follows.",
                     authors=[], primary_category="cs.LG", categories=["cs.LG"])
        out = excerpt(p, 200, compile_keywords(KW))
        self.assertTrue(out.startswith("…We train a diffusion model"))
        self.assertLessEqual(len(out), 200)


class SmtpSettingsTest(unittest.TestCase):
    def cfg(self, **values):
        base = dict(SMTP_USERNAME=None, SMTP_PASSWORD=None, SMTP_HOST=None, SMTP_PORT=None,
                    SMTP_SECURITY=None, SMTP_FROM=None)
        base.update(values)
        with env(**base):
            return SmtpConfig.from_env()

    def test_gmail_is_detected_and_password_spaces_removed(self):
        c = self.cfg(SMTP_USERNAME="ada@gmail.com", SMTP_PASSWORD=" abcd efgh ijkl mnop \n")
        self.assertEqual((c.host, c.port, c.security, c.password), ("smtp.gmail.com", 587, "starttls", "abcdefghijklmnop"))
        self.assertTrue(c.detected)

    def test_other_presets_and_port_inference(self):
        self.assertEqual(self.cfg(SMTP_USERNAME="a@qq.com", SMTP_PASSWORD="x").describe(),
                         "smtp.qq.com:465 (SSL), detected automatically")
        c = self.cfg(SMTP_USERNAME="a@uni.edu", SMTP_PASSWORD="x", SMTP_HOST="mail.uni.edu", SMTP_PORT="465")
        self.assertEqual((c.security, c.detected), ("ssl", False))

    def test_helpful_errors(self):
        with self.assertRaises(SetupError) as ctx:
            self.cfg()
        self.assertIn("SMTP_USERNAME and SMTP_PASSWORD", str(ctx.exception))
        with self.assertRaises(SetupError) as ctx:
            self.cfg(SMTP_USERNAME="a@outlook.com", SMTP_PASSWORD="x")
        self.assertIn("Microsoft", str(ctx.exception))
        with self.assertRaises(SetupError) as ctx:
            self.cfg(SMTP_USERNAME="a@unknown-domain.org", SMTP_PASSWORD="x")
        self.assertIn("SMTP_HOST", str(ctx.exception))
        with self.assertRaises(SetupError):
            self.cfg(SMTP_USERNAME="a@gmail.com", SMTP_PASSWORD="x", SMTP_PORT="five")


class SendTest(unittest.TestCase):
    def test_one_copy_per_recipient_with_proper_headers(self):
        with smtp_server(refuse={"nobody@example.org"}) as srv, smtp_env(srv):
            smtp = SmtpConfig.from_env()
            delivered, failed = send_all(recipients=["a@example.org", "b@example.org", "nobody@example.org"],
                                         subject="Hello ✓", html="<p>hi</p>", text="hi", from_name="ArxivDaily",
                                         smtp=smtp)
            self.assertEqual((delivered, failed), (["a@example.org", "b@example.org"], ["nobody@example.org"]))
            self.assertEqual(srv.logins, 1)
            self.assertEqual([m["to"] for m in srv.messages], [["a@example.org"], ["b@example.org"]])
            msg = srv.parsed(0)
            self.assertEqual(msg["To"], "a@example.org")             # nobody sees the other recipients
            self.assertEqual(msg["Subject"], "Hello ✓")
            self.assertEqual(msg["Auto-Submitted"], "auto-generated")
            self.assertTrue(msg["Date"] and msg["Message-ID"])
            self.assertEqual(msg.get_content_type(), "multipart/alternative")

    def test_one_rejected_message_does_not_stop_the_others(self):
        with smtp_server(reject_data={"b@example.org"}) as srv, smtp_env(srv):
            delivered, failed = send_all(recipients=["a@example.org", "b@example.org", "c@example.org"],
                                         subject="s", html="h", text="t", from_name="x", smtp=SmtpConfig.from_env())
        self.assertEqual((delivered, failed), (["a@example.org", "c@example.org"], ["b@example.org"]))

    def test_everything_rejected_is_explained(self):
        with smtp_server(reject_data={"a@example.org"}) as srv, smtp_env(srv):
            with self.assertRaises(SetupError) as ctx:
                send_all(recipients=["a@example.org"], subject="s", html="h", text="t", from_name="x",
                         smtp=SmtpConfig.from_env())
        self.assertIn("didn't accept the message (554 5.7.1", str(ctx.exception))
        self.assertIn("rejected as spam", str(ctx.exception))
        self.assertNotIn("Couldn't connect", str(ctx.exception))    # a refusal isn't a connection problem

    def test_wrong_password_explains_app_passwords(self):
        with smtp_server() as srv, smtp_env(srv, SMTP_PASSWORD="wrong"):
            with self.assertRaises(SetupError) as ctx:
                send_all(recipients=["a@example.org"], subject="s", html="h", text="t", from_name="x",
                         smtp=SmtpConfig.from_env())
        self.assertIn("rejected the username or password", str(ctx.exception))
        self.assertIn('"app password". Step 2 of docs/setup-guide.md', str(ctx.exception))

    def test_password_advice_fits_the_provider(self):
        refused = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
        with env(SMTP_USERNAME="ada@gmail.com", SMTP_PASSWORD="x"):
            gmail = _explain(refused, SmtpConfig.from_env())
        with env(SMTP_USERNAME="ada@gmx.net", SMTP_PASSWORD="x"):
            gmx = _explain(refused, SmtpConfig.from_env())
        self.assertIn("a Google App Password, not your normal login password", gmail)
        self.assertIn("myaccount.google.com/apppasswords", gmail)
        self.assertIn("your GMX password", gmx)
        self.assertNotIn("not your normal login password", gmx)
        self.assertNotIn("google", gmx.lower())

    def test_unreachable_server(self):
        with env(SMTP_USERNAME="a@example.org", SMTP_PASSWORD="x", SMTP_HOST="127.0.0.1", SMTP_PORT="1",
                 SMTP_SECURITY="none"):
            with self.assertRaises(SetupError) as ctx:
                send_all(recipients=["a@example.org"], subject="s", html="h", text="t", from_name="x",
                         smtp=SmtpConfig.from_env())
        self.assertTrue(re.search(r"Couldn't connect to 127\.0\.0\.1:1", str(ctx.exception)))


if __name__ == "__main__":
    unittest.main()
