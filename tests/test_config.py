import json
import os
import tempfile
import unittest

from support import env
from src.config import ConfigError, load_config, load_dotenv, mask_email, parse_json, resolve_recipients, validate


def write(tmp, text, name="config.json", encoding="utf-8"):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding=encoding) as f:
        f.write(text)
    return path


class LoadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_repository_config_is_valid(self):
        # Only validity: in a fork this is the owner's own config.json, and reminders
        # (such as settings left over from version 1) are fine there.
        cfg = load_config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"))
        self.assertTrue(cfg.keywords)


    def test_minimal_config_gets_defaults(self):
        cfg = load_config(write(self.tmp, '{"keywords": ["graph neural network"]}'))
        self.assertEqual(cfg.fetch.source, "auto")
        self.assertEqual(cfg.ranking.max_papers_per_email, 25)
        self.assertEqual(cfg.email.subject_template, "[ArxivDaily] {n_papers} new {papers} — {date}")
        self.assertEqual(cfg.categories, [])

    def test_comments_trailing_commas_and_bom_are_forgiven(self):
        text = '{\n  // my topics\n  "keywords": ["a", "b",],\n  /* block */ "categories": ["cs.LG"],\n}\n'
        cfg = load_config(write(self.tmp, text, encoding="utf-8-sig"))
        self.assertEqual(cfg.keywords, ["a", "b"])
        self.assertIn("comments or trailing commas", cfg.warnings[0])

    def test_comment_markers_inside_strings_are_kept(self):
        data, lenient = parse_json('{"keywords": ["http://x.org/a", "a, b"],}')
        self.assertTrue(lenient)
        self.assertEqual(data["keywords"], ["http://x.org/a", "a, b"])

    def test_syntax_error_points_at_line_and_column(self):
        text = '{\n  "keywords": [\n    "a"\n    "b"\n  ]\n}\n'
        with self.assertRaises(ConfigError) as ctx:
            load_config(write(self.tmp, text))
        err = ctx.exception
        self.assertEqual((err.line, err.column), (4, 5))
        self.assertIn("comma is probably missing", str(err))
        self.assertIn('    4 |     "b"', str(err))

    def test_curly_quotes_hint(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(write(self.tmp, '{“keywords”: ["a"]}'))
        self.assertIn("curly quotes", str(ctx.exception))
        with self.assertRaises(ConfigError) as ctx:          # curly quotes inside a value are fine
            load_config(write(self.tmp, '{\n  "keywords": ["“a”"]\n  "categories": []\n}'))
        self.assertNotIn("curly", str(ctx.exception))
        self.assertIn("comma is probably missing", str(ctx.exception))

    def test_missing_closing_brace_points_at_the_end(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(write(self.tmp, '{\n  "keywords": ["a"]\n\n'))
        err = ctx.exception
        self.assertEqual((err.line, err.column), (2, 20))
        self.assertIn("ends too early", str(err))
        with self.assertRaises(ConfigError) as ctx:
            load_config(write(self.tmp, "  \n"))
        self.assertIn("The file is empty", str(ctx.exception))

    def test_missing_keywords(self):
        with self.assertRaises(ConfigError) as ctx:
            validate({"keywords": []})
        self.assertIn("at least one", str(ctx.exception))

    def test_unknown_setting_suggests_a_fix(self):
        cfg = validate({"keywords": ["a"], "ranking": {"max_paper_per_email": 3}})
        self.assertIn('Did you mean "max_papers_per_email"', cfg.warnings[0])

    def test_category_typos(self):
        with self.assertRaises(ConfigError) as ctx:
            validate({"keywords": ["a"], "categories": ["cs.lg"]})
        self.assertIn('Did you mean "cs.LG"', str(ctx.exception))
        with self.assertRaises(ConfigError) as ctx:
            validate({"keywords": ["a"], "categories": ["cs.LGG"]})
        self.assertIn('"cs.LG"', str(ctx.exception))
        self.assertEqual(validate({"keywords": ["a"], "categories": ["cs", "stat.ML"]}).categories, ["cs", "stat.ML"])

    def test_error_line_for_semantic_errors(self):
        text = json.dumps({"keywords": ["a"], "fetch": {"source": "nope"}}, indent=2)
        with self.assertRaises(ConfigError) as ctx:
            load_config(write(self.tmp, text))
        self.assertEqual(ctx.exception.line, text.splitlines().index('    "source": "nope"') + 1)

    def test_v1_settings_are_accepted_with_a_reminder(self):
        cfg = validate({"keywords": ["a", "b"], "fetch": {"max_results_per_keyword": 30, "sort_by": "submittedDate"}})
        self.assertEqual(cfg.fetch.max_results, 500)                    # the old setting has no effect
        self.assertEqual(len(cfg.warnings), 2)
        self.assertTrue(all("from version 1" in w and "You can delete it" in w for w in cfg.warnings))

    def test_value_checks(self):
        for bad in ({"ranking": {"min_score": "high"}}, {"email": {"subject_template": "{nope}"}},
                    {"recipients": ["not-an-email"]}, {"fetch": {"include_revisions": "maybe"}},
                    {"fetch": {"source": "rss"}}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                validate({"keywords": ["a"], **bad})
        self.assertEqual(validate({"keywords": ["a"], "ranking": {"max_papers_per_email": "10"}})
                         .ranking.max_papers_per_email, 10)

    def test_duplicate_keywords(self):
        cfg = validate({"keywords": ["LLM", "llm", "RAG"]})
        self.assertEqual(cfg.keywords, ["LLM", "RAG"])
        self.assertTrue(cfg.warnings)


class RecipientsTest(unittest.TestCase):
    def test_order_of_precedence(self):
        cfg = validate({"keywords": ["a"], "recipients": ["cfg@example.org"]})
        with env(MAIL_TO="a@x.org; b@y.org,a@x.org"):
            self.assertEqual(resolve_recipients(cfg, "me@z.org"), (["a@x.org", "b@y.org"], "MAIL_TO secret"))
        with env(MAIL_TO=None):
            self.assertEqual(resolve_recipients(cfg, "me@z.org"), (["cfg@example.org"], "config.json"))
            self.assertEqual(resolve_recipients(validate({"keywords": ["a"]}), "me@z.org"),
                             (["me@z.org"], "your sending address"))

    def test_bad_mail_to(self):
        with env(MAIL_TO="a@x.org, oops"), self.assertRaises(ConfigError):
            resolve_recipients(validate({"keywords": ["a"]}))

    def test_mask(self):
        self.assertEqual(mask_email("alice@example.com"), "al***@example.com")


class DotenvTest(unittest.TestCase):
    def test_load_dotenv_does_not_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, '# c\nexport ARXIVDAILY_T1="quoted value"\nARXIVDAILY_T2=plain # note\n'
                              'ARXIVDAILY_T3=keep\n', name=".env")
            with env(ARXIVDAILY_T1=None, ARXIVDAILY_T2=None, ARXIVDAILY_T3="already set"):
                loaded = load_dotenv(path)
                self.assertEqual(os.environ["ARXIVDAILY_T1"], "quoted value")
                self.assertEqual(os.environ["ARXIVDAILY_T2"], "plain")
                self.assertEqual(os.environ["ARXIVDAILY_T3"], "already set")
                self.assertEqual(sorted(loaded), ["ARXIVDAILY_T1", "ARXIVDAILY_T2"])


if __name__ == "__main__":
    unittest.main()
