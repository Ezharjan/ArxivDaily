import unittest

import support  # noqa: F401  (puts the project on sys.path)
from src.arxiv_fetcher import Paper
from src.relevance import compile_keywords, highlight_spans, keyword_counts, make_pattern, score_and_rank, score_paper


def paper(pid="2611.00001", title="", summary="", atype="new"):
    return Paper(short_id=pid, version=1, title=title, summary=summary, authors=[],
                 primary_category="cs.LG", categories=["cs.LG"], announce_type=atype)


class MatchingTest(unittest.TestCase):
    def assertMatches(self, keyword, *texts):
        pat = make_pattern(keyword)
        for text in texts:
            self.assertTrue(pat.search(text), f"{keyword!r} should match {text!r}")

    def assertNoMatch(self, keyword, *texts):
        pat = make_pattern(keyword)
        for text in texts:
            self.assertFalse(pat.search(text), f"{keyword!r} should not match {text!r}")

    def test_plural_of_last_word(self):
        # The v1 bug: "diffusion model" never matched the far more common plural.
        self.assertMatches("diffusion model", "Diffusion Models for X", "a diffusion model", "diffusion-models")
        self.assertMatches("large language model", "Large Language Models (LLMs) are")
        self.assertMatches("diffusion models", "a diffusion model")          # plural keyword, singular text

    def test_irregular_endings(self):
        self.assertMatches("strategy", "strategies")
        self.assertMatches("KV cache", "KV caches", "kv-cache")
        self.assertMatches("approaches", "approach")
        self.assertMatches("analysis", "analyses")
        self.assertMatches("bias", "biases", "bias")
        self.assertMatches("LLMs", "LLM", "LLMs")

    def test_hyphens_spaces_and_case(self):
        self.assertMatches("in-context learning", "In-Context Learning", "in context learning",
                           "in‑context learning", "incontext learning")
        self.assertMatches("retrieval augmented generation", "Retrieval-Augmented Generation (RAG)")
        self.assertMatches("mixture of experts", "Mixture-of-Experts models")

    def test_whole_words_only(self):
        self.assertNoMatch("gpt", "egypt", "chatgpt")
        self.assertNoMatch("rag", "storage", "dragon")
        self.assertMatches("rag", "RAG pipelines", "(RAG)")

    def test_symbols_are_literal(self):
        self.assertMatches("C++", "written in C++ today")
        self.assertNoMatch("C++", "C programming")


class ScoringTest(unittest.TestCase):
    KW = ["diffusion model", "large language model"]

    def test_title_counts_more(self):
        a = paper(title="Diffusion models at scale", summary="We study things.")
        b = paper(title="Things at scale", summary="We study diffusion models.")
        score_paper(a, self.KW)
        score_paper(b, self.KW)
        self.assertEqual(a.score, 3.0)
        self.assertEqual(b.score, 1.0)
        self.assertEqual(a.matched_keywords, ["diffusion model"])

    def test_multi_keyword_bonus(self):
        p = paper(title="LLMs", summary="large language models meet diffusion models")
        score_paper(p, self.KW, multi_keyword_bonus=0.5)
        self.assertEqual(p.score, 2.5)
        self.assertEqual(p.matched_keywords, self.KW)

    def test_rank_order_and_threshold(self):
        papers = [
            paper("2611.00001", "Unrelated", "nothing here"),
            paper("2611.00002", "Diffusion model", "diffusion model"),
            paper("2611.00003", "x", "diffusion model", atype="cross"),
            paper("2611.00004", "x", "diffusion model", atype="new"),
        ]
        ranked = score_and_rank(papers, self.KW, min_score=1.0)
        self.assertEqual([p.short_id for p in ranked], ["2611.00002", "2611.00004", "2611.00003"])
        self.assertEqual(score_and_rank(papers, self.KW, max_papers=1)[0].short_id, "2611.00002")
        self.assertEqual(keyword_counts(ranked, self.KW), {"diffusion model": 3, "large language model": 0})

    def test_highlight_spans_do_not_overlap(self):
        pats = compile_keywords(["language model", "large language model"])
        text = "A large language model and a language model."
        spans = highlight_spans(text, pats)
        self.assertEqual([text[s:e] for s, e, _ in spans], ["large language model", "language model"])
        self.assertEqual([i for _, _, i in spans], [1, 0])


if __name__ == "__main__":
    unittest.main()
