import datetime as dt
import json
import os
import tempfile
import unittest

import support  # noqa: F401
from src import archive, state
from src.arxiv_fetcher import Paper


def paper(i, score=1.0, kw=("diffusion model",)):
    return Paper(short_id=f"2611.{i:05d}", version=1, title=f"Paper {i}", summary="s", authors=["A"],
                 primary_category="cs.LG", categories=["cs.LG"], matched_keywords=list(kw), score=score)


class StateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "state.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip_and_order(self):
        st = state.load(self.path, repository="ada/ArxivDaily")
        self.assertEqual(st.mark_seen(["b", "a", "b"]), 2)
        self.assertEqual(st.mark_seen(["c", "a"]), 1)
        state.save(self.path, st)
        again = state.load(self.path, repository="ada/ArxivDaily")
        self.assertEqual(again.seen_ids, ["c", "b", "a"])
        self.assertEqual(again.repository, "ada/ArxivDaily")

    def test_v1_file_is_accepted(self):
        with open(self.path, "w") as f:
            json.dump({"version": 1, "last_run_utc": "", "last_sent_utc": "", "seen_ids": ["x"]}, f)
        self.assertEqual(state.load(self.path, repository="ada/ArxivDaily").seen_ids, ["x"])

    def test_a_fork_does_not_inherit_history(self):
        state.save(self.path, state.State(repository="someone/ArxivDaily", seen_ids=["x"]))
        st = state.load(self.path, repository="ada/ArxivDaily")
        self.assertEqual((st.seen_ids, st.repository), ([], "ada/ArxivDaily"))
        self.assertEqual(state.load(self.path, repository="SOMEONE/arxivdaily").seen_ids, ["x"])
        self.assertEqual(state.load(self.path).seen_ids, ["x"])                 # local run: keep it

    def test_corrupt_file_starts_fresh(self):
        with open(self.path, "w") as f:
            f.write("{oops")
        self.assertEqual(state.load(self.path).seen_ids, [])


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "data")
        self.kw = ["diffusion model", "large language model"]

    def tearDown(self):
        self._tmp.cleanup()

    def index(self):
        with open(os.path.join(self.dir, "index.json")) as f:
            return json.load(f)

    def update(self, day, papers, **kw):
        kw.setdefault("repository", "ada/ArxivDaily")
        return archive.update(self.dir, day=day, papers=papers, keywords=self.kw, categories=["cs.LG"], **kw)

    def test_writes_days_and_index(self):
        self.assertTrue(self.update(dt.date(2026, 11, 12), [paper(1), paper(2, 3.0)]))
        self.assertTrue(self.update(dt.date(2026, 11, 13), [paper(3)]))
        idx = self.index()
        self.assertEqual([d["date"] for d in idx["days"]], ["2026-11-13", "2026-11-12"])
        self.assertEqual(idx["days"][1]["count"], 2)
        self.assertEqual(idx["days"][1]["kw"], {"diffusion model": 2})
        self.assertEqual(idx["keywords"], self.kw)
        self.assertEqual(idx["category_names"]["cs.LG"], "Machine Learning")
        with open(os.path.join(self.dir, "days", "2026-11-12.json")) as f:
            self.assertEqual([p["id"] for p in json.load(f)["papers"]], ["2611.00002", "2611.00001"])

    def test_no_change_means_no_rewrite(self):
        self.update(dt.date(2026, 11, 13), [paper(1)])
        before = self.index()["generated_at"]
        self.assertFalse(self.update(dt.date(2026, 11, 13), [paper(1)]))
        self.assertEqual(self.index()["generated_at"], before)

    def test_rev_changes_when_a_day_changes(self):
        self.update(dt.date(2026, 11, 13), [paper(1)])
        rev = self.index()["days"][0]["rev"]
        self.update(dt.date(2026, 11, 13), [paper(2)])
        self.assertNotEqual(self.index()["days"][0]["rev"], rev)
        self.assertEqual(self.index()["days"][0]["count"], 2)

    def test_limits_and_pruning(self):
        self.update(dt.date(2026, 8, 1), [paper(1)], keep_days=30)
        self.update(dt.date(2026, 11, 13), [paper(i, score=i) for i in range(10)], keep_days=30, max_per_day=4)
        idx = self.index()
        self.assertEqual([d["date"] for d in idx["days"]], ["2026-11-13"])
        self.assertEqual(idx["days"][0]["count"], 4)

    def test_foreign_archive_is_replaced(self):
        self.update(dt.date(2026, 11, 12), [paper(1)], repository="someone/ArxivDaily")
        self.assertFalse(archive.belongs_to(self.dir, "ada/ArxivDaily"))
        self.update(dt.date(2026, 11, 13), [paper(2)])
        idx = self.index()
        self.assertEqual((idx["repository"], [d["date"] for d in idx["days"]]), ("ada/ArxivDaily", ["2026-11-13"]))


if __name__ == "__main__":
    unittest.main()
