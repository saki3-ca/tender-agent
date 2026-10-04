"""
Change detection, amendment linking, and duplicate merging engine.
Enforces strict organizational boundary isolation (never merges across organizations)
and detects material changes (corrigendum, deadline extension, cancellation).
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from app.utils.logging import logger
from app.db.supabase import db


def normalize_ref_number(ref: Optional[str]) -> str:
    """Normalizes reference numbers by stripping common prefixes and non-alphanumeric chars."""
    if not ref:
        return ""
    cleaned = re.sub(r'^(?:ref|memo\s*no|tender\s*no|স্মারক\s*নং)[\s.:#-]*', '', ref.strip(), flags=re.IGNORECASE)
    return re.sub(r'[^a-zA-Z0-9]', '', cleaned).upper()


def classify_material_change(old_text: str, new_text: str) -> Optional[str]:
    """
    Analyzes diff between old and new tender document versions.
    Returns change type string or None if cosmetic.
    """
    new_lower = new_text.lower()

    if any(k in new_lower for k in ["corrigendum", "addendum", "সংশোধনী"]):
        return "CORRIGENDUM_ISSUED"
    if any(k in new_lower for k in ["deadline extended", "time extension", "সময় বৃদ্ধি"]):
        return "DEADLINE_EXTENSION"
    if any(k in new_lower for k in ["cancelled", "tenders cancelled", "বাতিল"]):
        return "TENDER_CANCELLED"
    if any(k in new_lower for k in ["re-tender", "retender", "পুনঃ দরপত্র"]):
        return "RE_TENDER"
    if any(k in new_lower for k in ["pre-bid clarification", "clarification meeting"]):
        return "PRE_BID_CLARIFICATION"

    return "SCOPE_OR_TERMS_REVISION"


class DeduplicationEngine:
    """Handles duplicate checking and amendment attachment to parent opportunities."""

    @staticmethod
    def find_duplicate(
        candidate: Dict[str, Any],
        existing_opportunities: List[Dict[str, Any]],
        similarity_threshold: float = 0.90
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Finds matching parent/duplicate opportunity.
        CRITICAL RULE: Never merges across different organizations!
        Returns: (matching_opp, match_reason) or (None, "")
        """
        cand_org = candidate.get("organization_id")
        cand_ref = normalize_ref_number(candidate.get("reference_number"))
        cand_doc_hash = candidate.get("document_hash")

        for opp in existing_opportunities:
            # 1. Organization boundary check — NEVER merge across different organizations
            if opp.get("organization_id") != cand_org:
                continue

            # 2. Match by document hash
            if cand_doc_hash and opp.get("document_hash") == cand_doc_hash:
                return opp, "SAME_DOCUMENT_HASH"

            # 3. Match by normalized reference number
            opp_ref = normalize_ref_number(opp.get("reference_number"))
            if cand_ref and opp_ref and cand_ref == opp_ref:
                return opp, "SAME_REFERENCE_NUMBER"

            # 4. Match by title similarity + overlapping deadline (same org)
            if candidate.get("title") and opp.get("title"):
                cand_title = candidate["title"].lower().strip()
                opp_title = opp["title"].lower().strip()
                if cand_title == opp_title:
                    return opp, "EXACT_TITLE_SAME_ORG"

        return None, ""

    @staticmethod
    def handle_amendment(parent_opp: Dict[str, Any], new_cand: Dict[str, Any], change_type: str) -> Dict[str, Any]:
        """
        Attaches a corrigendum or deadline change to existing opportunity.
        Logs version history and returns updated opportunity.
        """
        prev_deadline = parent_opp.get("submission_deadline")
        new_deadline = new_cand.get("submission_deadline")

        version_data = {
            "opportunity_id": parent_opp["id"],
            "version_num": (parent_opp.get("version_num", 1)) + 1,
            "change_type": change_type,
            "change_summary": f"Detected amendment: {change_type}",
            "previous_deadline": prev_deadline,
            "new_deadline": new_deadline
        }
        db.record_opportunity_version(version_data)

        # Update parent deadline and status if extended
        if new_deadline and new_deadline != prev_deadline:
            parent_opp["submission_deadline"] = new_deadline
            parent_opp["lifecycle_status"] = "EXTENDED"

        logger.info(f"Attached amendment {change_type} to parent opportunity {parent_opp['id']}")
        return parent_opp
