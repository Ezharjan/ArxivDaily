import datetime as dt
import email.message
import io
import unittest
import urllib.error
from unittest import mock

from support import api_feed, fixture
from src import arxiv_fetcher as af
from src.config import validate


class RssParsingTest(unittest.TestCase):
    """Parsing a real arXiv RSS feed (13 Nov 2026, cs.LG+cs.CL+cs.AI+cs.CV, trimmed)."""

    @classmethod
    def setUpClass(cls):
        cls.papers, cls.announced = af.parse_rss(fixture("rss_2026-11-13_sample.xml"))
        cls.by_id = {p.short_id: p for p in cls.papers}

    def test_announcement_date_and_types(self):
        self.assertEqual(self.announced, dt.date(2026, 11, 13))
        types = sorted({p.announce_type for p in self.papers})
        self.assertEqual(types, ["cross", "new", "replace", "replace-cross"])

    def test_fields(self):
        p = next(p for p in self.papers if p.title.startswith("Overcoming Spurious Correlations"))
        self.assertEqual(p.authors, ["Eiichi Sakurai", "Kenji Yamanishi"])
        self.assertTrue(p.summary.startswith("While conditional diffusion models"))
        self.assertNotIn("Announce Type", p.summary)
        self.assertEqual(p.primary_category, p.categories[0])
        self.assertEqual(p.abs_url, f"https://arxiv.org/abs/{p.short_id}")
        self.assertRegex(p.short_id, r"^\d{4}\.\d{5}$")

    def test_latex_and_affiliations_are_cleaned(self):
        for p in self.papers:
            for name in p.authors:
                self.assertNotIn("\\", name, name)
                self.assertNotIn("(", name, name)

    def test_weekend_and_broken_feeds(self):
        self.assertEqual(af.parse_rss(fixture("rss_2026-11-14_empty_weekend.xml")), ([], dt.date(2026, 11, 14)))
        with self.assertRaises(af.FetchError):
            af.parse_rss(b"<html>Service unavailable</html>")


class ApiParsingTest(unittest.TestCase):
    def test_real_api_response(self):
        papers = af.parse_api(fixture("api_sample.xml"))
        self.assertEqual([p.short_id for p in papers], ["1108.0157", "hep-ph/9502380", "0810.4447"])
        self.assertEqual(papers[1].version, 3)
        self.assertEqual(papers[1].announce_type, "replace")
        self.assertEqual(papers[0].primary_category, "hep-ph")
        self.assertNotIn("\n", papers[0].title)
        self.assertEqual(papers[0].published.tzinfo, dt.timezone.utc)

    def test_error_response(self):
        with self.assertRaises(af.FetchError) as ctx:
            af.parse_api(fixture("api_error.xml"))
        self.assertIn("incorrect id format", str(ctx.exception))

    def test_cross_lists_are_detected(self):
        now = dt.datetime.now(dt.timezone.utc)
        data = api_feed([{"id": "2611.00001", "title": "t", "published": now, "cats": ["stat.ML", "cs.LG"]}])
        self.assertEqual(af.parse_api(data, ["cs.LG"])[0].announce_type, "cross")
        self.assertEqual(af.parse_api(data, ["stat"])[0].announce_type, "new")

    def test_query(self):
        q = af.build_api_query(['in-context "learning"', "diffusion model"], ["cs.LG", "stat"])
        self.assertIn('abs:"in context learning"', q)
        self.assertIn('ti:"diffusion models"', q)
        self.assertIn("cat:stat.ML", q)
        self.assertNotIn('""', q)


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://x", code, "err", headers, io.BytesIO(b""))


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        patcher = mock.patch.object(af, "_sleep", self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_retries_rate_limits_then_succeeds(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b"data"
        with mock.patch("urllib.request.urlopen", side_effect=[http_error(429, "20"), http_error(503), ok]):
            self.assertEqual(af.http_get("https://export.arxiv.org/api/query", waits=(5, 15)), b"data")
        self.assertEqual(self.sleeps, [20.0, 15])

    def test_gives_up_with_a_clear_message(self):
        with mock.patch("urllib.request.urlopen", side_effect=[http_error(429)] * 3):
            with self.assertRaises(af.FetchError) as ctx:
                af.http_get("https://export.arxiv.org/api/query", waits=(1, 1))
        self.assertIn("rate limit", str(ctx.exception))

    def test_does_not_retry_client_errors(self):
        with mock.patch("urllib.request.urlopen", side_effect=[http_error(404)]) as m:
            with self.assertRaises(af.FetchError):
                af.http_get("https://rss.arxiv.org/rss/cs.XX")
        self.assertEqual(m.call_count, 1)


class FetchStrategyTest(unittest.TestCase):
    """Which source is used when (auto mode)."""

    def setUp(self):
        self.cfg = validate({"keywords": ["diffusion model"], "categories": ["cs.LG"]})
        self.calls = []
        now = dt.datetime.now(dt.timezone.utc)
        self.api = api_feed([
            {"id": "2611.10001", "title": "Diffusion models, fresh", "published": now - dt.timedelta(hours=5)},
            {"id": "2611.10000", "title": "Diffusion models, old", "published": now - dt.timedelta(days=9)},
        ])
        for name, value in (("_sleep", lambda s: None),):
            p = mock.patch.object(af, name, value)
            p.start()
            self.addCleanup(p.stop)

    def run_fetch(self, rss, api=None, **kw):
        def fake(url, **_):
            self.calls.append("rss" if url.startswith(af.RSS_URL) else "api")
            source = rss if url.startswith(af.RSS_URL) else api
            if isinstance(source, Exception):
                raise source
            return source
        with mock.patch.object(af, "http_get", fake):
            return af.fetch(self.cfg, **kw)

    def test_rss_is_used_when_it_works(self):
        res = self.run_fetch(fixture("rss_2026-11-13_sample.xml"))
        self.assertEqual((res.source, self.calls), ("rss", ["rss"]))

    def test_api_takes_over_when_rss_fails(self):
        res = self.run_fetch(af.FetchError("HTTP 503"), self.api)
        self.assertEqual((res.source, self.calls), ("api", ["rss", "api"]))
        self.assertEqual([p.short_id for p in res.papers], ["2611.10001"])     # outside lookback dropped
        self.assertIn("unavailable", res.notes[0])

    def test_quiet_weekend_makes_no_api_calls(self):
        res = self.run_fetch(fixture("rss_2026-11-14_empty_weekend.xml"), self.api)
        self.assertEqual((res.papers, self.calls), ([], ["rss"]))

    def test_manual_preview_on_a_weekend_searches_recent_papers(self):
        res = self.run_fetch(fixture("rss_2026-11-14_empty_weekend.xml"), self.api, fallback_when_empty=True)
        self.assertEqual(res.source, "api")
        self.assertIn("weekends", res.notes[0])

    def test_empty_weekday_feed_is_double_checked(self):
        res = self.run_fetch(fixture("rss_2026-11-12_empty_weekday.xml"), self.api)
        self.assertEqual((res.source, self.calls), ("api", ["rss", "api"]))

    def test_empty_weekday_feed_with_api_down_is_not_an_error(self):
        res = self.run_fetch(fixture("rss_2026-11-12_empty_weekday.xml"), af.FetchError("HTTP 429"))
        self.assertEqual((res.source, res.papers), ("rss", []))
        self.assertTrue(res.notes)

    def test_both_down_raises(self):
        with self.assertRaises(af.FetchError):
            self.run_fetch(af.FetchError("HTTP 503"), af.FetchError("HTTP 429"))

    def test_type_filter(self):
        papers, _ = af.parse_rss(fixture("rss_2026-11-13_sample.xml"))
        f = af.filter_announce_types
        self.assertEqual({p.announce_type for p in f(papers, include_cross_lists=True, include_revisions=False)},
                         {"new", "cross"})
        self.assertEqual({p.announce_type for p in f(papers, include_cross_lists=False, include_revisions=False)},
                         {"new"})
        self.assertEqual(len(f(papers, include_cross_lists=True, include_revisions=True)), len(papers))


if __name__ == "__main__":
    unittest.main()
