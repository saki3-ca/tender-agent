"""
Deterministic rules pre-filter and classification engine for ACNABIN Tender Agent.
Enforces pipeline routing (Pipeline A vs B), strong/weak keyword matching,
irrelevant procurement rejection, and Opportunity vs Market Intelligence determination.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from app.utils.config import config
from app.parsers.date_cleaner import parse_deadline


class RulesClassifier:
    """Pre-filters documents and deterministically assigns pipeline, category, and record type."""

    def __init__(self):
        self.ifrs9_banks = config.ifrs9_banks
        self.organizations = config.organizations
        self.keywords = config.keywords
        self.categories = config.categories
        self.scoring = config.scoring
        self.outside_target_mode = config.settings.get("ifrs9_outside_target_mode", "general_market")

        # Compile regex sets for fast matching
        self.strong_terms = [t.lower() for t in self.keywords["ifrs9_ecl"]["strong_terms"]]
        self.weak_terms = [t.lower() for t in self.keywords["ifrs9_ecl"]["weak_terms"]]
        self.procurement_terms = [t.lower() for t in self.keywords["procurement_terms"]["english"] + self.keywords["procurement_terms"]["bangla"]]
        self.irrelevant_terms = [t.lower() for t in self.keywords.get("irrelevant_procurement", [])]

    def match_organization(self, text: str, org_hint: Optional[str] = None) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Matches text or org_hint against known organizations and the 30 target banks.
        Returns: (organization_id, canonical_name, is_ifrs9_target)
        """
        # First check against the 30 fixed target banks
        search_corpus = f"{org_hint or ''} {text[:1500]}".lower()

        for bank in self.ifrs9_banks:
            # Check canonical name
            if bank["canonical_name"].lower() in search_corpus:
                return bank["id"], bank["canonical_name"], True
            # Check aliases
            for alias in bank.get("aliases", []):
                alias_lower = alias.lower()
                # Boundary check for short acronyms like RAKUB, BKB, BDBL, MTB, JBL, ABL
                if len(alias_lower) <= 5:
                    if re.search(rf'\b{re.escape(alias_lower)}\b', search_corpus):
                        return bank["id"], bank["canonical_name"], True
                else:
                    if alias_lower in search_corpus:
                        return bank["id"], bank["canonical_name"], True

        # Check against general organization registry
        for org in self.organizations:
            if org["canonical_name"].lower() in search_corpus:
                return org["organization_id"], org["canonical_name"], org.get("is_ifrs9_target", False)
            for alias in org.get("aliases", []):
                alias_lower = alias.lower()
                if len(alias_lower) <= 5:
                    if re.search(rf'\b{re.escape(alias_lower)}\b', search_corpus):
                        return org["organization_id"], org["canonical_name"], org.get("is_ifrs9_target", False)
                else:
                    if alias_lower in search_corpus:
                        return org["organization_id"], org["canonical_name"], org.get("is_ifrs9_target", False)

        return None, org_hint or "Unknown Organization", False

    def check_ifrs9_relevance(self, text: str) -> Tuple[bool, List[str]]:
        """
        Determines if text is IFRS 9 / ECL relevant.
        Strong terms: one hit makes it relevant.
        Weak terms: count ONLY if strong term OR procurement term is also present!
        Prevents 'PD = Project Director' and IT 'provisioning' false positives.
        """
        text_lower = text.lower()
        matched_strong = [st for st in self.strong_terms if st in text_lower]
        if matched_strong:
            return True, matched_strong

        # Check weak terms with boundary match
        matched_weak = []
        for wt in self.weak_terms:
            if len(wt) <= 3:
                # e.g., 'pd', 'lgd', 'ead', 'ecl'
                # Check that PD doesn't mean Project Director
                if wt == "pd" and ("project director" in text_lower or "প্রকল্প পরিচালক" in text_lower):
                    continue
                if re.search(rf'\b{re.escape(wt)}\b', text_lower):
                    matched_weak.append(wt)
            else:
                if wt in text_lower:
                    matched_weak.append(wt)

        # Only count weak terms if a procurement term is also in the document
        has_procurement = any(pt in text_lower for pt in self.procurement_terms)
        if matched_weak and has_procurement:
            return True, matched_weak

        return False, []

    def check_procurement_language(self, text: str) -> Tuple[bool, List[str]]:
        """Checks if text contains genuine procurement language."""
        text_lower = text.lower()
        hits = []
        for pt in self.procurement_terms:
            if len(pt) <= 4:
                if re.search(rf'\b{re.escape(pt)}\b', text_lower):
                    hits.append(pt)
            else:
                if pt in text_lower:
                    hits.append(pt)
        return len(hits) > 0, hits

    def check_irrelevant_procurement(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Checks if tender is irrelevant procurement (construction, office supplies, etc.).
        Returns (is_irrelevant, matched_term).
        """
        text_lower = text.lower()
        has_advisory_or_audit = any(
            t in text_lower for t in [
                "audit", "assurance", "advisory", "consultant", "consultancy",
                "chartered accountants", "ifrs", "tax", "due diligence",
                "নিরীক্ষা", "পরামর্শক"
            ]
        )
        if has_advisory_or_audit:
            return False, None

        for term in self.irrelevant_terms:
            if re.search(rf'\b{re.escape(term)}\b', text_lower):
                return True, term

        return False, None

    def determine_service_category(self, text: str, ifrs9_relevant: bool) -> Tuple[str, float]:
        """
        Determines ACNABIN service category based on weighted keyword match.
        Returns: (category_code, confidence_score)
        """
        if ifrs9_relevant:
            return "IFRS9_ECL", 1.0

        text_lower = text.lower()
        scores: Dict[str, int] = {}

        for cat in self.categories:
            code = cat["code"]
            if code == "IFRS9_ECL":
                continue
            cat_hits = 0
            for kw in cat.get("keywords_en", []):
                if kw.lower() in text_lower:
                    cat_hits += 2
            for kw in cat.get("keywords_bn", []):
                if kw.lower() in text_lower:
                    cat_hits += 2
            scores[code] = cat_hits

        best_cat = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else "OTHER_PROFESSIONAL"
        max_score = scores.get(best_cat, 0)
        conf = min(1.0, max_score / 6.0)
        return best_cat, conf

    def classify_candidate(self, text: str, org_hint: Optional[str] = None, source_url: str = "") -> Dict[str, Any]:
        """
        Full Stage 0 deterministic pre-filter and classification.
        Assigns:
          - pipeline: IFRS9_TARGET | GENERAL_MARKET
          - record_type: OPPORTUNITY | MARKET_INTELLIGENCE | IRRELEVANT
          - category: enum code
          - fit_type: DIRECT_FIT | PARTNERSHIP_REQUIRED | NOT_SUITABLE
        """
        # 1. Organization match
        org_id, org_name, is_target = self.match_organization(text, org_hint)

        # 2. Check irrelevant procurement terms
        is_physical_or_general, irr_term = self.check_irrelevant_procurement(text)

        # 3. Check IFRS 9 / ECL relevance
        is_ifrs9, matched_terms = self.check_ifrs9_relevance(text)

        # 4. Check procurement language & deadline
        has_procurement, proc_hits = self.check_procurement_language(text)
        parsed_dt, dt_note = parse_deadline(text)

        # 5. Opportunity vs Market Intelligence determination
        # Keep ALL procurement notices from all banks as OPPORTUNITY so no tenders are discarded.
        is_tender_signal = (
            has_procurement or 
            is_physical_or_general or 
            parsed_dt is not None or 
            any(w in text.lower() for w in ["tender", "rfp", "eoi", "quotation", "procurement", "দরপত্র", "বিজ্ঞপ্তি", "deadline", "submission", "শেষ তারিখ"])
        )

        if is_tender_signal:
            record_type = "OPPORTUNITY"
        elif is_ifrs9 or any(ac in text.lower() for ac in ["audit", "circular", "annual report", "financial statement", "নিরীক্ষা"]):
            record_type = "MARKET_INTELLIGENCE"
        else:
            # Still default to OPPORTUNITY if coming from a monitored bank source
            record_type = "OPPORTUNITY"

        # 6. Category determination
        if is_physical_or_general and not is_ifrs9:
            category, cat_conf = "OTHER_PROFESSIONAL", 0.5
        else:
            category, cat_conf = self.determine_service_category(text, is_ifrs9)

        # 7. Pipeline Routing (Section 4)
        if is_target and is_ifrs9:
            pipeline = "IFRS9_TARGET"
            outside_target = False
        elif not is_target and is_ifrs9:
            pipeline = "GENERAL_MARKET"
            outside_target = True
            if self.outside_target_mode == "intelligence_only" and record_type == "OPPORTUNITY":
                record_type = "MARKET_INTELLIGENCE"
        else:
            pipeline = "GENERAL_MARKET"
            outside_target = False

        # 8. Fit Type determination (Section 9 & 16.4)
        # Software/core banking/IT transform -> PARTNERSHIP_REQUIRED
        text_lower = text.lower()
        if any(pt in text_lower for pt in ["software", "solution provider", "core banking", "system integration", "সফটওয়্যার"]):
            fit_type = "PARTNERSHIP_REQUIRED"
        elif record_type == "IRRELEVANT":
            fit_type = "NOT_SUITABLE"
        else:
            fit_type = "DIRECT_FIT"

        return {
            "organization_id": org_id,
            "organization_name": org_name,
            "is_target": is_target,
            "pipeline": pipeline,
            "outside_ifrs9_target": outside_target,
            "record_type": record_type,
            "category": category,
            "fit_type": fit_type,
            "ifrs9_ecl_relevant": is_ifrs9,
            "procurement_detected": has_procurement,
            "matched_terms": matched_terms or proc_hits,
            "deadline_utc": parsed_dt,
            "deadline_note": dt_note,
            "acnabin_relevant": record_type != "IRRELEVANT"
        }
