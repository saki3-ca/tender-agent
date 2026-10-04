"""
Groq client for Stage 2 Triage, Stage 4 Second-Opinion Review, and Fallback Extraction.
Uses OpenAI-compatible Groq Chat Completions endpoint with JSON mode.
"""

import json
from typing import Any, Dict, Optional, Tuple
import httpx
from app.utils.logging import logger
from app.utils.config import config
from app.db.supabase import db

TRIAGE_SYSTEM_PROMPT = """
You are an expert procurement triage agent for ACNABIN Chartered Accountants, Bangladesh.
The document may be in English, Bangla, or mixed. Determine:
1. Is this a genuine procurement/tender (OPPORTUNITY), background info/circular (MARKET_INTELLIGENCE), or non-advisory/irrelevant (IRRELEVANT)?
2. ACNABIN Category (IFRS9_ECL, AUDIT_ASSURANCE, RISK_CONTROL, ACCOUNTING_REPORTING, PROCESS_ADVISORY, TAX_VAT, FINANCIAL_ADVISORY, TRAINING, OTHER_PROFESSIONAL, or NONE).
3. Keep or Drop.
Output valid JSON only:
{"is_opportunity": "YES|NO|UNCERTAIN", "record_type": "OPPORTUNITY|MARKET_INTELLIGENCE|IRRELEVANT", "category": "...", "keep": true|false, "confidence": "HIGH|MEDIUM|LOW", "reason": "..."}
"""

REVIEW_SYSTEM_PROMPT = """
You are a senior audit partner reviewing an automated tender intelligence assessment for ACNABIN Chartered Accountants.
Review the extracted opportunity against the provided source excerpt.
Verify if it is genuine procurement, if the category is correct, if eligibility flags are sound, and if quoted evidence is accurate.
Output valid JSON only:
{
  "is_genuine_procurement": true|false,
  "acnabin_relevant": true|false,
  "category_correct": true|false,
  "suggested_category": "...",
  "evidence_sufficient": true|false,
  "eligibility_concerns": ["..."],
  "suspect_fields": ["..."],
  "review_summary": "Maximum 3 sentences review summary."
}
"""


class GroqClient:
    """Interacts with Groq API for fast triage, second-opinion review, and fallback extraction."""

    def __init__(self):
        self.api_key = config.groq_api_key
        self.triage_model = config.groq_triage_model
        self.review_model = config.groq_review_model
        self.daily_limit = int(config.settings.get("ai", {}).get("groq_daily_call_limit", 1000))
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        calls_today = db.get_ai_calls_today("groq")
        if calls_today >= self.daily_limit:
            logger.warning("Groq daily free-tier limit reached", extra={"calls_today": calls_today, "limit": self.daily_limit})
            return False
        return True

    async def triage(self, title: str, source_url: str, text_excerpt: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Stage 2 Triage with Groq."""
        if not self.is_available():
            return None, "GROQ_UNAVAILABLE_OR_QUOTA_EXCEEDED"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        user_content = f"Title: {title}\nSource: {source_url}\nText Excerpt:\n{text_excerpt[:3000]}"

        payload = {
            "model": self.triage_model,
            "messages": [
                {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(self.base_url, headers=headers, json=payload)
                if resp.status_code == 429:
                    return None, "GROQ_RATE_LIMITED"
                resp.raise_for_status()
                data = resp.json()

                usage = data.get("usage", {})
                db.record_ai_usage("groq", self.triage_model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

                content = data["choices"][0]["message"]["content"]
                return json.loads(content), None
        except Exception as e:
            logger.error(f"Groq triage failed: {e}")
            return None, str(e)

    async def review_opportunity(self, title: str, extracted_data: Dict[str, Any], source_excerpt: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Stage 4 Second-Opinion Review with Groq using a different model family."""
        if not self.is_available():
            return None, "GROQ_UNAVAILABLE_OR_QUOTA_EXCEEDED"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        user_content = (
            f"Title: {title}\n"
            f"Extracted Assessment:\n{json.dumps(extracted_data, indent=2)}\n\n"
            f"Original Source Excerpt:\n{source_excerpt[:4000]}"
        )

        payload = {
            "model": self.review_model,
            "messages": [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self.base_url, headers=headers, json=payload)
                if resp.status_code == 429:
                    return None, "GROQ_RATE_LIMITED"
                resp.raise_for_status()
                data = resp.json()

                usage = data.get("usage", {})
                db.record_ai_usage("groq", self.review_model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

                content = data["choices"][0]["message"]["content"]
                return json.loads(content), None
        except Exception as e:
            logger.error(f"Groq review failed: {e}")
            return None, str(e)

    async def extract_fallback(self, document_context: str, org_hint: str = "") -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Fallback Stage 3 Extraction when Gemini is unavailable."""
        if not self.is_available():
            return None, "GROQ_UNAVAILABLE_OR_QUOTA_EXCEEDED"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        prompt = (
            "Extract tender opportunity details for ACNABIN Chartered Accountants.\n"
            "Return valid JSON matching this schema:\n"
            "{\n"
            "  \"is_opportunity\": \"YES | NO | UNCERTAIN\",\n"
            "  \"record_type\": \"OPPORTUNITY | MARKET_INTELLIGENCE | IRRELEVANT\",\n"
            "  \"ifrs9_ecl_relevant\": true|false,\n"
            "  \"category\": \"IFRS9_ECL | AUDIT_ASSURANCE | RISK_CONTROL | ACCOUNTING_REPORTING | PROCESS_ADVISORY | TAX_VAT | FINANCIAL_ADVISORY | TRAINING | OTHER_PROFESSIONAL | NONE\",\n"
            "  \"acnabin_relevant\": \"YES | POSSIBLY | NO\",\n"
            "  \"fit_type\": \"DIRECT_FIT | PARTNERSHIP_REQUIRED | NOT_SUITABLE\",\n"
            "  \"organization\": \"...\",\n"
            "  \"title\": \"...\",\n"
            "  \"reference\": \"...\",\n"
            "  \"publication_date_raw\": \"...\",\n"
            "  \"deadline_raw\": \"...\",\n"
            "  \"scope_summary\": \"...\",\n"
            "  \"potential_acnabin_service\": \"...\",\n"
            "  \"relevance_reason\": \"...\",\n"
            "  \"eligibility_summary\": \"...\",\n"
            "  \"eligibility_concerns\": [\"...\"],\n"
            "  \"evidence\": [{\"page\": 1, \"text\": \"...\"}],\n"
            "  \"confidence\": \"HIGH | MEDIUM | LOW\"\n"
            "}\n"
            f"Organization Hint: {org_hint}\n"
            f"Content:\n{document_context[:8000]}"
        )

        payload = {
            "model": self.triage_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self.base_url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

                usage = data.get("usage", {})
                db.record_ai_usage("groq", self.triage_model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

                content = data["choices"][0]["message"]["content"]
                return json.loads(content), None
        except Exception as e:
            return None, str(e)
