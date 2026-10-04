"""
AI Pipeline Router coordinating Stage 0 (Rules), Stage 1 (Embeddings),
Stage 2 (Groq Triage), Stage 3 (Gemini Extraction), and Stage 4 (Groq Review).
Enforces AI_MODE, fallback chain, evidence verification, and safe error handling.
"""

import re
from typing import Any, Dict, List, Optional
from app.utils.logging import logger
from app.utils.config import config
from app.classification.rules import RulesClassifier
from app.ai.cloudflare import CloudflareWorkersAIClient
from app.ai.groq import GroqClient
from app.ai.gemini import GeminiClient


def verify_evidence_in_text(evidence_list: List[Dict[str, Any]], source_text: str) -> List[Dict[str, Any]]:
    """
    Verifies that each quoted evidence snippet appears in the source text.
    Uses normalized substring matching. Drops hallucinations.
    """
    if not evidence_list:
        return []

    normalized_source = re.sub(r'\s+', ' ', source_text.lower())
    verified: List[Dict[str, Any]] = []

    for ev in evidence_list:
        quote = ev.get("text", "").strip()
        if not quote:
            continue
        normalized_quote = re.sub(r'\s+', ' ', quote.lower())
        # Check if quote or at least 25 characters of quote appears in source
        if len(normalized_quote) > 20:
            sub = normalized_quote[:40]
            if sub in normalized_source:
                verified.append(ev)
            else:
                logger.debug(f"Evidence quote dropped (not in source text): {quote[:50]}...")
        elif normalized_quote in normalized_source:
            verified.append(ev)

    return verified


class AIRouter:
    """Coordinates classification and extraction stages across providers with fallbacks."""

    def __init__(self):
        self.rules = RulesClassifier()
        self.cloudflare = CloudflareWorkersAIClient()
        self.groq = GroqClient()
        self.gemini = GeminiClient()

    async def process_candidate(self, candidate: Dict[str, Any], full_text: str) -> Dict[str, Any]:
        """
        Processes a candidate through the AI pipeline according to configured AI_MODE.
        Returns unified opportunity extraction dictionary.
        """
        mode = config.ai_mode # 'off' | 'triage_only' | 'full'
        title = candidate.get("title", "")
        source_url = candidate.get("source_url", "")
        org_hint = candidate.get("organization_name")

        # -------------------------------------------------------------
        # Stage 0: Deterministic Rules Pre-Filter
        # -------------------------------------------------------------
        stage0 = self.rules.classify_candidate(full_text, org_hint=org_hint, source_url=source_url)

        # If rules pre-filter rejects as IRRELEVANT (and not advisory), return early
        if stage0["record_type"] == "IRRELEVANT":
            return {
                **stage0,
                "confidence": "HIGH",
                "evidence": [],
                "eligibility_concerns": [],
                "scope_summary": title,
                "review_status": "NOT_PURSUING"
            }

        # -------------------------------------------------------------
        # AI_MODE = 'off': Pure rule-based processing (Section 16.4)
        # -------------------------------------------------------------
        if mode == "off":
            logger.info("Processing in AI_MODE=off (pure rules)", extra={"title": title})
            return self._build_rule_based_result(candidate, full_text, stage0)

        # -------------------------------------------------------------
        # Stage 1: Multilingual Embeddings (Cloudflare Workers AI)
        # -------------------------------------------------------------
        embedding, embed_err = None, None
        if mode in ("triage_only", "full") and self.cloudflare.is_available():
            embedding, embed_err = await self.cloudflare.generate_embedding(f"{title} {full_text[:1500]}")
            if embed_err:
                logger.warning(f"Stage 1 embedding skipped: {embed_err}")

        # -------------------------------------------------------------
        # Stage 2: Triage (Groq)
        # -------------------------------------------------------------
        triage_res, triage_err = None, None
        if mode in ("triage_only", "full") and self.groq.is_available():
            triage_res, triage_err = await self.groq.triage(title, source_url, full_text[:3000])

        if mode == "triage_only":
            result = self._build_rule_based_result(candidate, full_text, stage0)
            if triage_res:
                result["confidence"] = triage_res.get("confidence", "MEDIUM")
                if triage_res.get("is_opportunity") == "NO":
                    result["record_type"] = "MARKET_INTELLIGENCE"
            return result

        # -------------------------------------------------------------
        # Stage 3: Full Structured Extraction (Gemini with Groq fallback)
        # -------------------------------------------------------------
        extracted_data = None
        extract_err = None

        if self.gemini.is_available():
            extracted_data, extract_err = await self.gemini.extract_tender(full_text, org_hint=stage0["organization_name"])

        # Fallback to Groq if Gemini failed or unavailable
        if not extracted_data and self.groq.is_available():
            logger.info("Using Groq as fallback for Stage 3 extraction", extra={"title": title})
            extracted_data, extract_err = await self.groq.extract_fallback(full_text, org_hint=stage0["organization_name"])

        # Fallback to rules if both AI providers failed
        if not extracted_data:
            logger.warning("All AI providers unavailable or failed; using rule-based fallback", extra={"error": extract_err})
            result = self._build_rule_based_result(candidate, full_text, stage0)
            result["review_status"] = "AI_REVIEW_PENDING"
            return result

        # Validate evidence against source text (Section 16.7)
        raw_evidence = extracted_data.get("evidence", [])
        verified_evidence = verify_evidence_in_text(raw_evidence, full_text)
        extracted_data["evidence"] = verified_evidence

        # Merge Stage 0 deterministic routing (Code routes pipeline, not LLM!)
        merged = {
            **stage0,
            "title": extracted_data.get("title") or title,
            "reference_number": extracted_data.get("reference") or candidate.get("reference_number"),
            "category": stage0["category"] if stage0["category"] != "OTHER_PROFESSIONAL" else (extracted_data.get("category") or "OTHER_PROFESSIONAL"),
            "fit_type": extracted_data.get("fit_type") or stage0["fit_type"],
            "scope_summary": extracted_data.get("scope_summary", ""),
            "potential_acnabin_service": extracted_data.get("potential_acnabin_service", ""),
            "relevance_reason": extracted_data.get("relevance_reason", ""),
            "eligibility_summary": extracted_data.get("eligibility_summary", ""),
            "eligibility_concerns": extracted_data.get("eligibility_concerns", []),
            "confidence": extracted_data.get("confidence", "MEDIUM"),
            "evidence": verified_evidence,
            "embedding": embedding,
            "extraction_result": extracted_data,
            "review_status": "VERIFIED" if extracted_data.get("confidence") == "HIGH" else "REVIEW_REQUIRED"
        }

        # -------------------------------------------------------------
        # Stage 4: Second-Opinion Review (Groq)
        # Runs if: category IFRS9_ECL, confidence LOW, or UNCERTAIN (Section 16.3)
        # -------------------------------------------------------------
        should_review = (
            merged["category"] == "IFRS9_ECL" or
            merged["confidence"] == "LOW" or
            extracted_data.get("is_opportunity") == "UNCERTAIN"
        )

        if should_review and self.groq.is_available():
            review_res, rev_err = await self.groq.review_opportunity(merged["title"], extracted_data, full_text[:3000])
            if review_res:
                merged["review_result"] = review_res
                if not review_res.get("is_genuine_procurement", True):
                    merged["review_status"] = "REVIEW_REQUIRED"

        return merged

    def _build_rule_based_result(self, candidate: Dict[str, Any], full_text: str, stage0: Dict[str, Any]) -> Dict[str, Any]:
        """Constructs extraction result purely using regex and rules (Section 16.4)."""
        title = candidate.get("title", "")

        # Extract reference number by regex
        ref_match = re.search(r'(?:ref|tender\s*no|memo\s*no|স্মারক\s*নং)[\s.:#-]+([A-Za-z0-9/_-]+)', full_text, re.IGNORECASE)
        ref_no = ref_match.group(1) if ref_match else ""

        # Extract evidence snippet
        evidence = []
        for term in stage0.get("matched_terms", []):
            idx = full_text.lower().find(term.lower())
            if idx != -1:
                start = max(0, idx - 40)
                end = min(len(full_text), idx + len(term) + 60)
                snippet = full_text[start:end].replace("\n", " ").strip()
                evidence.append({"page": 1, "text": snippet})
                break

        return {
            **stage0,
            "title": title,
            "reference_number": ref_no,
            "scope_summary": title,
            "potential_acnabin_service": f"ACNABIN {stage0['category']} Professional Advisory",
            "relevance_reason": f"Matched terms: {', '.join(stage0.get('matched_terms', []))}",
            "eligibility_summary": "Potentially eligible — verify tender eligibility and ACNABIN credentials.",
            "eligibility_concerns": [],
            "confidence": "HIGH" if stage0.get("deadline_utc") and len(stage0.get("matched_terms", [])) >= 2 else "MEDIUM",
            "evidence": evidence,
            "review_status": "REVIEW_REQUIRED"
        }
