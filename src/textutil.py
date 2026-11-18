"""Small text helpers: clean up the LaTeX that arXiv metadata often contains.

arXiv titles and author lists are written by authors in LaTeX, so a feed may
contain ``Ra\\'ul``, ``M{\\aa}rten`` or ``$\\gamma$-weakly``. These helpers turn
the common cases into plain Unicode ("Raúl", "Mårten", "γ-weakly") and leave
anything they don't understand untouched.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

# --- accents and special letters -------------------------------------------

_SPECIAL_LETTERS = {
    "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
    "o": "ø", "O": "Ø", "l": "ł", "L": "Ł", "ss": "ß", "i": "ı", "j": "ȷ",
}
_SPECIAL_RE = re.compile(r"\{\\(aa|AA|ae|AE|oe|OE|ss|o|O|l|L|i|j)\}|\\(aa|AA|ae|AE|oe|OE|ss|o|O|l|L|i|j)(?![A-Za-z])\s?")

_COMBINING = {
    "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303",
    "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b",
    "c": "\u0327", "k": "\u0328", "r": "\u030a", "d": "\u0323", "b": "\u0331",
}
_LETTER = r"[A-Za-zıȷ]"
# \'e  \'{e}  \' e  -- symbol accents may touch the letter directly
_SYMBOL_ACCENT_RE = re.compile(r"\\([\'`^\"~=.])\s*(?:\{\s*(" + _LETTER + r")\s*\}|(" + _LETTER + r"))")
# \v{S}  \c c  -- letter accents need braces or a space before the letter
_LETTER_ACCENT_RE = re.compile(r"\\([uvHckrdb])(?:\s*\{\s*(" + _LETTER + r")\s*\}|\s+(" + _LETTER + r"))")
_BRACED_CHAR_RE = re.compile(r"\{([^\W\d_])\}")


def _accent(m: "re.Match[str]") -> str:
    base = m.group(2) or m.group(3)
    base = {"ı": "i", "ȷ": "j"}.get(base, base)
    return unicodedata.normalize("NFC", base + _COMBINING[m.group(1)])


# --- inline math --------------------------------------------------------------

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ",
    "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
_SYMBOLS = {
    "ell": "ℓ", "infty": "∞", "times": "×", "cdot": "·", "pm": "±", "le": "≤",
    "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠", "approx": "≈",
    "sim": "∼", "to": "→", "rightarrow": "→", "leftarrow": "←", "in": "∈",
    "partial": "∂", "nabla": "∇", "sum": "∑", "prod": "∏", "log": "log",
    "exp": "exp", "ldots": "…", "dots": "…", "cdots": "⋯",
}
_BLACKBOARD = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "E": "𝔼", "P": "ℙ"}
_SUPERSCRIPTS = str.maketrans("0123456789+-n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ")
_SUBSCRIPTS = str.maketrans("0123456789+-", "₀₁₂₃₄₅₆₇₈₉₊₋")
_MATH_RE = re.compile(r"\$([^$]{1,80})\$")


def _convert_math(expr: str) -> "str | None":
    """Convert a short inline-math snippet to Unicode, or None if it's too complex."""
    s = expr.strip()
    s = re.sub(r"\\mathbb\{([A-Z])\}", lambda m: _BLACKBOARD.get(m.group(1), m.group(0)), s)
    s = re.sub(r"\\(?:mathrm|mathcal|mathbf|mathit|text|textbf|textit|operatorname)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\sqrt\s*\{([^{}]+)\}", lambda m: "√" + (m.group(1) if len(m.group(1)) == 1 else f"({m.group(1)})"), s)
    s = re.sub(r"\\sqrt\s*([A-Za-z0-9])", r"√\1", s)
    s = re.sub(r"\\([A-Za-z]+)", lambda m: _GREEK.get(m.group(1)) or _SYMBOLS.get(m.group(1)) or m.group(0), s)
    s = re.sub(r"\^\{?([0-9+\-n]+)\}?", lambda m: m.group(1).translate(_SUPERSCRIPTS), s)
    s = re.sub(r"_\{?([0-9+\-]+)\}?", lambda m: m.group(1).translate(_SUBSCRIPTS), s)
    s = s.replace("{", "").replace("}", "") if re.fullmatch(r"[^\\]*", s) else s
    if re.search(r"[\\^_]", s):
        return None
    return re.sub(r"\s+", " ", s).strip()


def _math(m: "re.Match[str]") -> str:
    expr = m.group(1)
    # Only touch real math: "$\gamma$", "$L_2$", "$k$". A pair of prices such as
    # "$5 and $10" must survive untouched.
    if not (re.search(r"[\\^_]", expr) or re.fullmatch(r"\s*[A-Za-z0-9]{1,3}\s*", expr)):
        return m.group(0)
    converted = _convert_math(expr)
    return converted if converted is not None else m.group(0)


_TEXT_MACRO_RE = re.compile(r"\\(?:emph|textit|textbf|texttt|textsc|textrm|textsf|mathrm|mathbf|text)\{([^{}]*)\}")


# --- public helpers -------------------------------------------------------------

def squash(text: str) -> str:
    """Collapse runs of whitespace (arXiv wraps titles and abstracts at ~80 cols)."""
    return " ".join((text or "").split())


def latex_to_unicode(text: str) -> str:
    """Best-effort conversion of common LaTeX markup to plain Unicode text."""
    if not text or ("\\" not in text and "$" not in text and "{" not in text and "--" not in text):
        return text or ""
    s = _MATH_RE.sub(_math, text)
    # Math we couldn't convert stays exactly as written: park it while the
    # text-mode passes below run, then put it back.
    parked: List[str] = []

    def _park(m: "re.Match[str]") -> str:
        parked.append(m.group(0))
        return f"\x00{len(parked) - 1}\x00"

    s = _MATH_RE.sub(_park, s)
    s = _TEXT_MACRO_RE.sub(r"\1", s)
    s = _SPECIAL_RE.sub(lambda m: _SPECIAL_LETTERS[m.group(1) or m.group(2)], s)
    s = _SYMBOL_ACCENT_RE.sub(_accent, s)
    s = _LETTER_ACCENT_RE.sub(_accent, s)
    s = _BRACED_CHAR_RE.sub(r"\1", s)
    s = re.sub(r"\\([&%_#$])", r"\1", s)
    s = re.sub(r"(?<=\w)---(?=\w)", "—", s)
    s = re.sub(r"(?<=\w)--(?=\w)", "–", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: parked[int(m.group(1))], s)


def clean(text: str) -> str:
    return squash(latex_to_unicode(squash(text)))


def split_authors(creator: str) -> List[str]:
    """Split an arXiv author string into names, dropping affiliations.

    ``"A. Smith (MIT, USA), B. Jones"`` -> ``["A. Smith", "B. Jones"]``.
    Commas inside parentheses belong to affiliations, not to the list.
    """
    names, buf, depth = [], [], 0
    for ch in creator or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            names.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    names.append("".join(buf))
    out = []
    for name in names:
        name = re.sub(r"\([^()]*\)", " ", name)       # drop "(affiliation)"
        name = clean(name).strip(" ,;")
        if name:
            out.append(name)
    return out
