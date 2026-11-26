"""
Faithfulness check: does an answer say only what the clauses it cites actually say?

The Verifier already proves a citation is real and current. It cannot tell whether the sentence next to the
citation matches the clause. This module closes that gap with fixed rules, no model, so the same answer always
gets the same verdict and the result can double as a training reward.

Each substantive sentence is tested against the text of the CITED clauses:
  number_not_in_clause   a figure (percent, rupee amount, years) that no cited clause contains. Units are compared
                         by meaning: "30 lakh" = "Rs. 30 lakhs" = "3,000,000"; a percent only matches a percent.
  category_not_in_clause an applicant or enterprise category (micro, small, medium, women, SC/ST, rural ...) the
                         clauses never mention, the classic swap error.
  unsupported_negative   "does not provide / not eligible" with no negation in a related clause sentence.
  scheme_not_cited       the answer names a scheme that none of the cited clauses belong to or mention.
  low_overlap            almost none of the sentence's content words appear in the clauses.

Sentences that talk about the clauses themselves ("the clauses do not state this", "please confirm with the bank")
are honest hedges and are not checked. What the rules cannot do: judge a paraphrase that changes meaning without
changing numbers, categories or polarity. It narrows the gap; it does not prove an answer correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HARD_KINDS = ("number_not_in_clause", "category_not_in_clause", "unsupported_negative", "scheme_not_cited", "low_overlap")
MIN_OVERLAP = 0.25            # share of a sentence's content words that must appear in the cited text
MIN_CONTENT_WORDS = 5         # shorter sentences are not judged on overlap alone


@dataclass
class Issue:
    kind: str
    sentence: str
    detail: str


@dataclass
class FaithResult:
    passed: bool
    score: float                         # 1.0 = every checked sentence is supported; usable as a reward
    checked: int
    issues: list[Issue] = field(default_factory=list)

    def reasons(self) -> list[str]:
        return [f"unsupported by the cited clauses ({i.kind}): {i.detail} [in: \"{i.sentence[:90]}\"]" for i in self.issues]


# ---------------------------------------------------------------------------------------------- text preparation
_ABBREV = re.compile(r"\b(Rs|No|Cr|Dr|Sh|Smt|Mr|Ms|approx|viz|etc)\.", re.I)
_CITE = re.compile(r"\[\d+(?:\s*[,;]\s*\d+)*\]")
_CLAUSE_REF = re.compile(r"\bClauses?\s+\d[\d,\s]*(?:\band\b\s*\d+)?", re.I)
_SCHEMEREF = re.compile(r"[A-Z][A-Z0-9_]{3,}\s*/\s*[\w.]+")
_PAREN_REF = re.compile(r"\([^)]*(?:clause|page|section|ref)\b[^)]*\)", re.I)
_SECTION = re.compile(r"\b\d+(?:\.\d+){2,}\.?")
_META_LINE = re.compile(r"^\s*(\(?sources?:|this (comes|information is|is from)|these figures come)", re.I)
_HEDGE = re.compile(
    r"\b(not (provided|specified|stated|mentioned|available|covered|settled|clear|given|included)\b[^.]{0,40}\b(clauses?|text|information|documents?)"
    r"|(clauses?|text|information|documents?)\b[^.]{0,60}\b(do(es)? not|don't|doesn't|did not|never)\b"
    r"|(do(es)? not|don't|cannot|can't) (state|specify|mention|say|settle|confirm|cover|show|know)\b"
    r"|outside my|not enough information|no information|i (do not|don't|cannot|can't) (know|confirm|find)"
    r"|please (confirm|check|verify|ask|contact|visit|read)|you (should|may|can|could|need to) (check|ask|contact|confirm|visit|verify)"
    r"|for (more|full|exact|further|complete) (details|information)|the (bank|lender|portal|authority) (decides|will decide|makes)"
    r"|still needed|i (need|would need) (to know|more)|prepared? (for|by) your review|a draft"
    r"|according to the (given|cited|provided|available) (clauses?|text|information|documents?)"
    r"|does not (specifically|explicitly|directly) (mention|state|say|cover|include|provide))",
    re.I)
_STOP = frozenset(
    "the a an and or of to in for on is are was be can could do does did i my me we our you your it this that with from as at by "
    "how what which who when where why any have has had will would should about get need want under into than then there their them "
    "also not no yes may must shall such these those other each every both more most only some per via upon within without been being "
    "scheme schemes clause clauses given provided provide provides state states stated according".split())


def _sentences(text: str) -> list[str]:
    t = _ABBREV.sub(lambda m: m.group(1), text)
    t = _CITE.sub("", t)
    t = _CLAUSE_REF.sub("", t)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'“])|\n+|;\s+(?=[A-Z])", t)
    out = []
    for p in parts:
        p = p.strip(" \t-*•")
        if len(p) >= 12 and not _META_LINE.match(p):
            out.append(p)
    return out


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return w


def _content(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}


# ---------------------------------------------------------------------------------------------------- numbers
_NUM = re.compile(
    r"(?P<rs>(?:Rs\.?|₹|INR)\s*)?(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|per\s?cent\b|percent\b|lakhs?\b|lacs?\b|crores?\b|cr\b|million\b|billion\b|years?\b|yrs?\b|months?\b|days?\b)?", re.I)
_MULT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "million": 1e6, "billion": 1e9}


def _nums(text: str) -> list[tuple[float, str]]:
    """(value, class) pairs. Class 'pct' and 'time' only match themselves; money and plain counts share 'amt'."""
    t = _SECTION.sub(" ", text)
    out = []
    for m in _NUM.finditer(t):
        try:
            v = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        unit = re.sub(r"\s", "", (m.group("unit") or "").lower())
        if unit in ("%", "percent"):
            out.append((v, "pct")); continue
        if unit in _MULT:
            out.append((v * _MULT[unit], "amt")); continue
        if unit.startswith(("year", "yr")):
            out.append((v * 12, "time")); continue
        if unit.startswith("month"):
            out.append((v, "time")); continue
        if unit.startswith("day"):
            out.append((v / 30.0, "time")); continue
        if 1900 <= v <= 2100 and not m.group("rs"):
            continue                                              # a calendar year
        out.append((v, "amt"))
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.051, 0.005 * abs(b))


def _number_issues(sentence: str, clause_nums: list[tuple[float, str]]) -> list[str]:
    bad = []
    cleaned = _SCHEMEREF.sub(" ", sentence)
    cleaned = _PAREN_REF.sub(" ", cleaned)
    cleaned = re.sub(r"\(\d{3,}\)", " ", cleaned)
    cleaned = re.sub(r"\b\d{4}[- ]\d{2,4}\b", " ", cleaned)
    for v, cls in _nums(cleaned):
        if cls == "amt" and v < 10 and float(v).is_integer():
            continue                                              # "2 categories", list numbering
        if not any(c == cls and _close(v, x) for x, c in clause_nums):
            shown = {"pct": f"{v:g}%", "time": f"{v:g} months", "amt": f"{v:,.0f}"}[cls]
            bad.append(shown)
    return bad


# -------------------------------------------------------------------------------------------------- categories
_CATS: dict[str, re.Pattern] = {
    "micro": re.compile(r"\bmicro\b", re.I),
    "small": re.compile(r"\bsmall (and|&|or|,) (micro|medium)\b|\b(micro|medium)(,)? (and|&|or) small\b|"
                        r"\bsmall[- ](enterprise|unit|scale|industr|manufactur|firm|and)", re.I),
    "medium": re.compile(r"\bmedium\b", re.I),
    "women": re.compile(r"\bwom[ae]n\b|\bfemale\b|\bmahila\b", re.I),
    "sc_st": re.compile(r"(?<![A-Za-z])S\.?C\.?\s?/\s?S\.?T\.?(?![A-Za-z])|(?<![A-Za-z])(SC|ST)(?![A-Za-z])|scheduled (caste|tribe)", re.I),
    "minority": re.compile(r"\bminorit", re.I),
    "obc": re.compile(r"(?<![A-Za-z])OBC(?![A-Za-z])|other backward", re.I),
    "ex_servicemen": re.compile(r"ex-?servicem[ae]n", re.I),
    "disabled": re.compile(r"physically (challenged|handicapped)|differently[- ]abled|\bdisabled\b|divyang", re.I),
    "manufacturing": re.compile(r"\bmanufactur", re.I),
    "service_sector": re.compile(r"\bservice (sector|enterprise|unit|industr|activit)|\bservices sector|\bbusiness/service", re.I),
    "rural": re.compile(r"\brural\b", re.I),
    "urban": re.compile(r"\burban\b", re.I),
    "north_east": re.compile(r"north[- ]?east|\bNER\b|himalayan|hill (state|area)", re.I),
}
_SUPERSET = {"micro": ("msme", "mse"), "small": ("msme", "mse"), "medium": ("msme",)}
_SUPER_RE = {"msme": re.compile(r"\bMSMEs?\b", re.I), "mse": re.compile(r"\bMSEs?\b", re.I)}
_GENERIC_OK = {"sc_st": ("special categor", "reserved categor", "weaker section"),
               "women": ("special categor",), "minority": ("special categor",), "disabled": ("special categor",),
               "ex_servicemen": ("special categor",)}


def _cats_in(text: str) -> set[str]:
    return {k for k, p in _CATS.items() if p.search(text)}


def _category_gap(sentence: str, clause_text: str, clause_cats: set[str]) -> list[str]:
    miss = []
    low = clause_text.lower()
    for k in _cats_in(sentence):
        if k in clause_cats:
            continue
        if any(_SUPER_RE[s].search(clause_text) for s in _SUPERSET.get(k, ())):
            continue
        if any(g in low for g in _GENERIC_OK.get(k, ())):
            continue
        miss.append(k.replace("_", "/"))
    return miss


# --------------------------------------------------------------------------------------------------- negation
_NEG_CLAIM = re.compile(
    r"\b(does not|do not|doesn't|don't|did not|is not|are not|isn't|aren't|cannot|can't|never|neither|nor|ineligible|excluded|"
    r"not (eligible|available|allowed|applicable|offered|covered|permitted|possible)|no (subsid|support|assistance|benefit|incentive|"
    r"provision|loan|scheme|reimbursement|grant)|not (provide|offer|give|include|cover|allow))\b", re.I)
_NEG_CUE = re.compile(r"\b(not|no|nor|never|none|neither|except|excluding|excluded|ineligible|shall not|cannot|unless|other than|only|barring)\b", re.I)


def _negative_supported(sentence: str, clause_sentences: list[str]) -> bool:
    want = _content(sentence)
    need = 1 if len(want) <= 3 else 2
    for cs in clause_sentences:
        if _NEG_CUE.search(cs) and len(want & _content(cs)) >= need:
            return True
    return False


# ------------------------------------------------------------------------------------------------- scheme names
_SCHEME_GENERIC = frozenset({
    "udyam", "startup", "start-up", "seed fund", "credit guarantee", "guarantee fund",
    "micro enterprise", "msme classification", "msme definition",
    "cluster development", "credit linked capital subsidy",
})


def _scheme_gap(sentence: str, families: set[str], clause_text_low: str) -> list[str]:
    from .scheme import _ALIASES, _family            # lazy: scheme imports the Verifier, the Verifier imports this
    low = sentence.lower()
    miss = []
    for alias, fam in _ALIASES.items():
        if alias in _SCHEME_GENERIC:
            continue
        if alias in low and _family(fam) not in families and alias not in clause_text_low:
            miss.append(alias)
    return sorted(set(miss))


# ------------------------------------------------------------------------------------------------------ check
def check(answer: str, clauses: list[dict]) -> FaithResult:
    """clauses: [{"scheme_code": str, "text": str}, ...], the clauses the answer cites."""
    if not clauses:
        return FaithResult(True, 1.0, 0, [])
    from .scheme import _family
    text = "\n".join(c["text"] for c in clauses)
    low = text.lower()
    clause_nums = _nums(text)
    clause_cats = _cats_in(text)
    clause_words = _content(text)
    clause_sents = _sentences(text) + [s for s in re.split(r"(?<=[.!?;:])\s+|\n+", _ABBREV.sub(lambda m: m.group(1), text)) if s.strip()]
    families = {_family(c.get("scheme_code", "")) for c in clauses}

    issues: list[Issue] = []
    checked = 0
    for s in _sentences(answer):
        if _HEDGE.search(s):
            continue
        checked += 1
        bad = _number_issues(s, clause_nums)
        if bad:
            issues.append(Issue("number_not_in_clause", s, "figure(s) not in the cited text: " + ", ".join(bad[:4])))
        miss = _category_gap(s, text, clause_cats)
        if miss:
            issues.append(Issue("category_not_in_clause", s, "category not in the cited text: " + ", ".join(miss)))
        if _NEG_CLAIM.search(s) and not _negative_supported(s, clause_sents):
            issues.append(Issue("unsupported_negative", s, "says something is not offered or allowed, but no cited clause says so"))
        gap = _scheme_gap(s, families, low)
        if gap:
            issues.append(Issue("scheme_not_cited", s, "names a scheme the cited clauses do not belong to: " + ", ".join(gap[:3])))
        words = _content(s)
        if len(words) >= MIN_CONTENT_WORDS and len(words & clause_words) / len(words) < MIN_OVERLAP:
            issues.append(Issue("low_overlap", s, "little of this sentence appears in the cited text"))
    bad_sentences = len({i.sentence for i in issues})
    score = 1.0 if not checked else max(0.0, 1.0 - bad_sentences / checked)
    return FaithResult(passed=not issues, score=round(score, 3), checked=checked, issues=issues)
