"""End-to-end runs of main.py against a temporary copy of the project.

arXiv is replaced by saved real feeds and email by a local fake SMTP server,
so these tests exercise exactly what GitHub Actions runs, without the network.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from support import ROOT, env, fixture, smtp_env, smtp_server

import main
from src import arxiv_fetcher as af
from src import github_actions as gha

GITHUB_VARS = ("GITHUB_ACTIONS", "GITHUB_REPOSITORY", "GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT", "GITHUB_RUN_ID",
               "GITHUB_REF_NAME", "GITHUB_WORKFLOW_REF", "ARXIVDAILY_ARCHIVE", "ARXIVDAILY_SITE_URL", "MAIL_TO")

# The tests bring their own topics and schedule, so a fork's customised config.json
# and cron lines never make them fail.
TEST_CONFIG = {"keywords": ["large language model", "retrieval augmented generation", "diffusion model",
                            "mixture of experts", "in-context learning"],
               "categories": ["cs.LG", "cs.CL", "cs.AI", "cs.CV"]}
TEST_SCHEDULE = 'on:\n  schedule:\n    - cron: "23 6 * * *"\n    - cron: "23 14 * * *"\n'


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = self.tmp = self._tmp.name
        with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
            json.dump(TEST_CONFIG, f)
        with open(os.path.join(tmp, "arxiv_daily.yml"), "w", encoding="utf-8") as f:
            f.write(TEST_SCHEDULE)
        shutil.copytree(os.path.join(ROOT, "web"), os.path.join(tmp, "web"),
                        ignore=shutil.ignore_patterns("data"))
        paths = dict(ROOT=tmp, CONFIG_PATH=os.path.join(tmp, "config.json"), STATE_PATH=os.path.join(tmp, "state.json"),
                     PREVIEW_DIR=os.path.join(tmp, "preview"), WEB_DIR=os.path.join(tmp, "web"),
                     ARCHIVE_DIR=os.path.join(tmp, "web", "data"), WORKFLOW_PATH=os.path.join(tmp, "arxiv_daily.yml"))
        for name, value in paths.items():
            p = mock.patch.object(main, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.http_calls = []
        self.feed = fixture("rss_2026-11-13_sample.xml")

        def fake_get(url, **_):
            self.http_calls.append(url)
            if url.startswith(af.RSS_URL):
                return self.feed
            raise af.FetchError("no API in tests")
        for name, value in (("http_get", fake_get), ("_sleep", lambda s: None)):
            p = mock.patch.object(af, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.clean_env = env(**{k: None for k in GITHUB_VARS})
        self.clean_env.__enter__()
        self.addCleanup(self.clean_env.__exit__, None, None, None)

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main.main(list(args))
        return code, out.getvalue()

    def state(self):
        with open(os.path.join(self.tmp, "state.json")) as f:
            return json.load(f)

    # ------------------------------------------------------------------ runs
    def test_dry_run_writes_a_preview_and_nothing_else(self):
        code, _ = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "preview", "email.html")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "web", "data")))

    def test_digest_is_sent_once(self):
        with smtp_server() as srv, smtp_env(srv), env(ARXIVDAILY_ARCHIVE="true"):
            self.assertEqual(self.run_main()[0], 0)
            self.assertEqual(len(srv.messages), 1)
            seen = self.state()["seen_ids"]
            self.assertTrue(seen)
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "web", "data", "index.json")))
            self.assertRegex(srv.parsed()["Subject"], r"^\[ArxivDaily\] \d+ new papers? — 2026-11-13$")

            self.assertEqual(self.run_main()[0], 0)                        # same feed again: nothing new
            self.assertEqual(len(srv.messages), 1)
            self.assertEqual(self.state()["seen_ids"], seen)

            self.assertEqual(self.run_main("--force")[0], 0)               # --force resends
            self.assertEqual(len(srv.messages), 2)

    def test_archive_trouble_never_costs_the_history(self):
        def broken(*a, **k):
            raise OSError("disk full")
        with smtp_server() as srv, smtp_env(srv), env(ARXIVDAILY_ARCHIVE="true"), \
                mock.patch.object(main.archive, "update", broken), self.assertLogs("arxivdaily", "WARNING") as logs:
            self.assertEqual(self.run_main()[0], 0)
            self.assertEqual(len(srv.messages), 1)
        self.assertTrue(self.state()["seen_ids"])
        self.assertIn("Couldn't update the web archive", "\n".join(logs.output))

    def test_missing_email_settings_fail_before_contacting_arxiv(self):
        with env(SMTP_USERNAME=None, SMTP_PASSWORD=None), self.assertLogs("arxivdaily", "ERROR") as logs:
            self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.http_calls, [])
        self.assertIn("SMTP_USERNAME and SMTP_PASSWORD", logs.output[0])

    def test_arxiv_down_is_reported(self):
        def down(url, **_):
            raise af.FetchError("HTTP 503 from rss.arxiv.org")
        with smtp_server() as srv, smtp_env(srv), mock.patch.object(af, "http_get", down), \
                self.assertLogs("arxivdaily", "ERROR") as logs:
            self.assertEqual(self.run_main()[0], 1)
        self.assertIn("Couldn't get papers from arXiv", logs.output[0])

    def test_test_email(self):
        with smtp_server() as srv, smtp_env(srv):
            self.assertEqual(self.run_main("--test-email")[0], 0)
            msg = srv.parsed()
            self.assertEqual(msg["Subject"], "ArxivDaily test: your email setup works")
            body = msg.get_body(("plain",)).get_content()
            self.assertIn("Checks for new papers daily at 06:23 and 14:23 UTC", body)
            self.assertIn("A sample of recent matches", body)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state.json")))

    def test_schedule_is_described_from_the_workflow(self):
        path = os.path.join(self.tmp, "w.yml")
        for crons, want in (([], "only when you start it from the Actions tab"),
                            (["23 6 * * *", "23 14 * * *"], "daily at 06:23 and 14:23 UTC"),
                            (["23 6 * * 1"], "on the cron schedule '23 6 * * 1' (UTC)")):
            with open(path, "w", encoding="utf-8") as f:
                f.write("on:\n  schedule:\n" + "".join(f'    - cron: "{c}"\n' for c in crons))
            self.assertEqual(gha.schedule_description(path), want)
        self.assertIn("arxiv_daily.yml", gha.schedule_description(os.path.join(self.tmp, "missing.yml")))

    def test_test_email_explains_a_missing_sample(self):
        with open(os.path.join(self.tmp, "config.json"), "w") as f:
            json.dump({"keywords": ["a topic nobody writes about"], "categories": ["cs.LG"]}, f)
        with smtp_server() as srv, smtp_env(srv):
            self.assertEqual(self.run_main("--test-email")[0], 0)
            body = srv.parsed().get_body(("plain",)).get_content()
        self.assertIn("None of the 14 papers arXiv announced most recently match your topics", body)
        self.assertNotIn("weekend", body)

    def test_bad_mail_to_is_an_email_setup_problem(self):
        summary = os.path.join(self.tmp, "summary.md")
        with smtp_server() as srv, smtp_env(srv, MAIL_TO="a@example.org, not-an-address"), \
                env(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=summary), self.assertLogs("arxivdaily", "ERROR"):
            code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("::error title=Email setup::The MAIL_TO secret contains an entry that isn't an email address", out)
        with open(summary) as f:
            text = f.read()
        self.assertIn("Email setup needs attention", text)
        self.assertNotIn("not-an-address", text)

    def test_a_refused_recipient_is_reported_without_its_address(self):
        summary = os.path.join(self.tmp, "summary.md")
        with smtp_server(refuse={"typo@example.org"}) as srv, smtp_env(srv, MAIL_TO="a@example.org, typo@example.org"), \
                env(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=summary), self.assertLogs("arxivdaily", "WARNING"):
            code, out = self.run_main()
            self.assertEqual(len(srv.messages), 1)
        self.assertEqual(code, 0)
        self.assertIn("::warning title=Some recipients didn't get the digest::The digest couldn't be delivered to "
                      "1 recipient address; everyone else got it.", out)
        self.assertTrue(self.state()["seen_ids"])                         # the papers still count as sent
        with open(summary) as f:
            text = f.read()
        self.assertIn("to 1 recipient", text)
        self.assertNotIn("typo@", text + out)

    def test_check(self):
        with smtp_server() as srv, smtp_env(srv):
            code, out = self.run_main("--check")
            self.assertEqual(code, 0)
            self.assertIn("Login works", out)
        with smtp_server() as srv, smtp_env(srv, SMTP_PASSWORD="wrong"):
            code, out = self.run_main("--check")
            self.assertEqual(code, 1)
            self.assertIn("rejected the username or password", out)
        self.assertEqual(srv.messages, [])

    # --------------------------------------------------------- GitHub Actions
    def test_config_error_becomes_an_inline_annotation(self):
        with open(os.path.join(self.tmp, "config.json"), "w") as f:
            f.write('{\n  "keywords": ["a"\n  "b"]\n}\n')
        summary = os.path.join(self.tmp, "summary.md")
        with env(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=summary), self.assertLogs("arxivdaily", "ERROR"):
            code, out = self.run_main("--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("::error title=Fix config.json,file=config.json,line=3,col=3::", out)
        with open(summary) as f:
            self.assertIn("config.json needs a fix", f.read())

    def test_public_summary_never_contains_addresses(self):
        summary, outputs = os.path.join(self.tmp, "summary.md"), os.path.join(self.tmp, "out.txt")
        with smtp_server() as srv, smtp_env(srv, MAIL_TO="secret.person@private.example"), \
                env(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=summary, GITHUB_OUTPUT=outputs,
                    GITHUB_REPOSITORY="ada/ArxivDaily", GITHUB_RUN_ID="1"):
            self.assertEqual(self.run_main()[0], 0)
            self.assertEqual(srv.messages[0]["to"], ["secret.person@private.example"])
        with open(summary) as f:
            text = f.read()
        self.assertIn("Emailed", text)
        self.assertNotIn("secret.person", text)
        self.assertNotIn(srv.user, text)
        with open(outputs) as f:
            out = f.read()
        self.assertRegex(out, r"papers_sent=\d+")
        self.assertIn("state_changed=true", out)        # keeps version-1 workflows committing state.json
        self.assertEqual(self.state()["repository"], "ada/ArxivDaily")


if __name__ == "__main__":
    unittest.main()
