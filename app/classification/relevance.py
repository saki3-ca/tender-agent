"""
ACNABIN relevance classification (deterministic, rules in config/relevance.json).

    General  = every active tender from a monitored source (no relevance check)
    Priority = active AND relevant to ACNABIN's services
    IFRS 9   = a Priority signal (IFRS 9 / ECL work), not the definition of Priority

Inputs are the listing title, the listing/notice description and, where available, the
tender document text. Generic service words ("audit", "internal control", "tax consultancy")
are matched only in the title/description, because tender documents are full of bidder
boilerplate ("audited financial statements", "VAT registration"). Document text is checked
for IFRS 9 terms and for specific procurement phrases ("appointment of external auditor").
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Pattern

from app.utils.config import config

IFRS9_LABEL = "IFRS 9 / ECL"


def _compile(phrase: str) -> Pattern:
    # ASCII phrases get word boundaries; Bangla phrases do not (Bangla words take suffixes)
    if phrase.isascii():
        return re.compile(r"(?<![\w])(?:" + phrase + r")(?![\w])", re.I)
    return re.compile(phrase, re.I)


@dataclass
class Relevance:
    is_priority: bool = False
    is_ifrs9: bool = False
    categories: List[str] = field(default_factory=list)       # human-readable labels
    matched_keywords: List[str] = field(default_factory=list)


class RelevanceClassifier:
    def __init__(self, rules: Optional[Dict[str, Any]] = None):
        rules = rules or config.relevance
        ifrs9 = rules["ifrs9"]
        self.ifrs9_strong = [_compile(p) for p in ifrs9["strong"]]
        self.ifrs9_contextual = [
            (_compile(rule["term"]), [_compile(c) for c in rule["context"]])
            for rule in ifrs9.get("contextual", [])
        ]
        self.window = int(ifrs9.get("context_window_chars", 200))
        self.categories = [
            {
                "label": c["label"],
                "phrases": [_compile(p) for p in c.get("phrases", [])],
                "document_phrases": [_compile(p) for p in c.get("document_phrases", [])],
            }
            for c in rules["categories"]
        ]
        self.exclusions = [_compile(p) for p in rules.get("exclusions", [])]
        self.priority_veto = [_compile(p) for p in rules.get("priority_veto", [])]

    # ------------------------------------------------------------------ IFRS 9
    def ifrs9_matches(self, text: str) -> List[str]:
        """IFRS 9 / ECL evidence in text. Generic terms (ECL, PD, LGD...) need nearby context."""
        hits: List[str] = []
        for pattern in self.ifrs9_strong:
            m = pattern.search(text)
            if m:
                hits.append(m.group(0))
        if hits:
            return hits
        for term, contexts in self.ifrs9_contextual:
            for m in term.finditer(text):
                # context on either side of the term (the term itself does not count as context)
                around = text[max(0, m.start() - self.window):m.start()] + " " + text[m.end():m.end() + self.window]
                ctx = next((c.search(around) for c in contexts if c.search(around)), None)
                if ctx:
                    hits.append(f"{m.group(0)} + {ctx.group(0)}")
                    return hits
        return hits

    # --------------------------------------------------------------- services
    def _strip_exclusions(self, text: str) -> str:
        for pattern in self.exclusions:
            text = pattern.sub(" ", text)
        return text

    def classify(self, title: str, description: str = "", document_text: str = "") -> Relevance:
        title = title or ""
        listing_text = self._strip_exclusions(f"{title}\n{description or ''}")
        doc_text = self._strip_exclusions(document_text or "")
        result = Relevance()

        ifrs9_hits = self.ifrs9_matches(f"{title}\n{description or ''}\n{document_text or ''}")
        if ifrs9_hits:
            result.is_ifrs9 = True
            result.categories.append(IFRS9_LABEL)
            result.matched_keywords.extend(ifrs9_hits)

        for cat in self.categories:
            hit = None
            for pattern in cat["phrases"]:
                hit = pattern.search(listing_text)
                if hit:
                    break
            if not hit and doc_text:
                for pattern in cat["document_phrases"]:
                    hit = pattern.search(doc_text)
                    if hit:
                        break
            if hit:
                result.categories.append(cat["label"])
                result.matched_keywords.append(hit.group(0))

        vetoed = any(p.search(title) for p in self.priority_veto)
        result.is_priority = bool(result.categories) and not vetoed
        if vetoed:
            result.is_ifrs9 = False
            result.categories = []
            result.matched_keywords = []
        # unique, readable keywords
        seen, kws = set(), []
        for k in result.matched_keywords:
            key = re.sub(r"\s+", " ", k.strip().lower())
            if key and key not in seen:
                seen.add(key)
                kws.append(re.sub(r"\s+", " ", k.strip()))
        result.matched_keywords = kws[:8]
        return result


# ---------------------------------------------------------------------- IT Services
@dataclass
class ItRelevance:
    is_it: bool = False                                        # an IT tender (IT page, General)
    is_priority: bool = False                                  # IT Priority: ACNABIN or an MoU partner can deliver it
    categories: List[str] = field(default_factory=list)        # capability labels
    partners: List[str] = field(default_factory=list)          # "ACNABIN", "CipherShield", "Brain Station 23"
    matched_keywords: List[str] = field(default_factory=list)


class ItClassifier:
    """IT Services relevance, from the "it" section of config/relevance.json."""

    def __init__(self, rules: Optional[Dict[str, Any]] = None):
        it = (rules or config.relevance)["it"]
        self.subject = [_compile(p) for p in it["subject"]]
        self.subject_exclusions = [_compile(p) for p in it.get("subject_exclusions", [])]
        self.veto = [_compile(p) for p in it.get("priority_veto", [])]
        self.capabilities = [
            {"label": c["label"], "implies_it": bool(c.get("implies_it")),
             "partners": c["partner"] if isinstance(c["partner"], list) else [c["partner"]],
             "phrases": [_compile(p) for p in c["phrases"]]}
            for c in it["capabilities"]
        ]

    def classify(self, title: str, description: str = "", it_source: bool = False) -> ItRelevance:
        title = title or ""
        text = f"{title}\n{description or ''}"
        for pattern in self.subject_exclusions:
            text = pattern.sub(" ", text)
        result = ItRelevance()
        subject = next((m for m in (p.search(text) for p in self.subject) if m), None)
        if not subject:   # e.g. "ISO 27001 certification", "SOC as a service"
            subject = next((m for cap in self.capabilities if cap["implies_it"]
                            for m in (p.search(text) for p in cap["phrases"]) if m), None)
        result.is_it = bool(it_source or subject)
        if not result.is_it:
            return result
        if subject:
            result.matched_keywords.append(subject.group(0))
        if any(p.search(title) for p in self.veto):
            return result
        for cap in self.capabilities:
            hit = next((m for m in (p.search(text) for p in cap["phrases"]) if m), None)
            if hit:
                result.categories.append(cap["label"])
                result.partners += [p for p in cap["partners"] if p not in result.partners]
                result.matched_keywords.append(re.sub(r"\s+", " ", hit.group(0).strip())[:60])
        result.is_priority = bool(result.categories)
        result.matched_keywords = list(dict.fromkeys(result.matched_keywords))[:8]
        return result
