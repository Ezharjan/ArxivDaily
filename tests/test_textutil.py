import unittest

import support  # noqa: F401
from src.textutil import clean, latex_to_unicode, split_authors


class LatexTest(unittest.TestCase):
    def test_accents_seen_in_real_feeds(self):
        cases = {
            r"Ra\'ul Alejandro Aquino-Ibarra": "Raúl Alejandro Aquino-Ibarra",
            r"Jorge Octavio Nicol\'as-D\'iaz": "Jorge Octavio Nicolás-Díaz",
            r"M{\aa}rten Schultzberg": "Mårten Schultzberg",
            r"{\L}ukasz Brzozowski": "Łukasz Brzozowski",
            r"Kristina \v{S}ekrst": "Kristina Šekrst",
            r"Universit\"at Erlangen-N\"urnberg": "Universität Erlangen-Nürnberg",
            r"Garc\'{\i}a": "García",
            r"Bj\o rn": "Bjørn",
            r"Fran\c{c}ois": "François",
        }
        for raw, want in cases.items():
            self.assertEqual(latex_to_unicode(raw), want)

    def test_simple_math_in_titles(self):
        self.assertEqual(latex_to_unicode(r"Optimal $\sqrt S$ and $\sqrt K$ Dependencies"),
                         "Optimal √S and √K Dependencies")
        self.assertEqual(latex_to_unicode(r"$\gamma$-weakly $\theta$-up-concavity"), "γ-weakly θ-up-concavity")
        self.assertEqual(latex_to_unicode(r"$k$-means with $O(\sqrt{T})$ regret"), "k-means with O(√T) regret")

    def test_leaves_what_it_does_not_understand(self):
        self.assertEqual(latex_to_unicode(r"in $\mathbb{R}^d$ space"), r"in $\mathbb{R}^d$ space")
        self.assertEqual(latex_to_unicode("Costs under $5 and $10 per query"), "Costs under $5 and $10 per query")
        self.assertEqual(latex_to_unicode("Plain title"), "Plain title")

    def test_dashes_and_text_macros(self):
        self.assertEqual(latex_to_unicode("Patient--Provider"), "Patient–Provider")
        self.assertEqual(latex_to_unicode(r"\textit{Lost} in the Middle"), "Lost in the Middle")

    def test_clean_collapses_whitespace(self):
        self.assertEqual(clean("  A\n  wrapped\ttitle "), "A wrapped title")


class AuthorsTest(unittest.TestCase):
    def test_affiliations_with_commas(self):
        raw = ("Zaid Abulawi (Department of Nuclear Engineering, Texas A&M University), "
               "William Oliveira (Politecnico di Milano, Italy), Akzhol Almukhametov")
        self.assertEqual(split_authors(raw), ["Zaid Abulawi", "William Oliveira", "Akzhol Almukhametov"])

    def test_latex_names(self):
        self.assertEqual(split_authors(r"Kristina \v{S}ekrst, Jeremy McHugh"), ["Kristina Šekrst", "Jeremy McHugh"])

    def test_empty(self):
        self.assertEqual(split_authors(""), [])


if __name__ == "__main__":
    unittest.main()
