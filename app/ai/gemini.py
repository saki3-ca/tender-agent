"""
Gemini client for Stage 3 Full Extraction using structured JSON outputs.
Uses HTTP requests to Google Gemini REST API, respecting daily limits and rate limits.
"""

import json
from typing import Any, Dict, Optional, Tuple
import httpx
from app.utils.logging import logger
from app.utils.config import config
from app.db.supabase import db

EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_opportunity": {"type": "STRING", "enum": ["YES", "NO", "UNCERTAIN"]},
        "record_type": {"type": "STRING", "enum": ["OPPORTUNITY", "MARKET_INTELLIGENCE", "IRRELEVANT"]},
        "ifrs9_ecl_relevant": {"type": "BOOLEAN"},
        "category": {
            "type": "STRING",
            "enum": [
                "IFRS9_ECL", "AUDIT_ASSURANCE", "RISK_CONTROL", "ACCOUNTING_REPORTING",
                "PROCESS_ADVISORY", "TAX_VAT", "FINANCIAL_ADVISORY", "TRAINING",
                "OTHER_PROFESSIONAL", "NONE"
            ]
        },
        "acnabin_relevant": {"type": "STRING", "enum": ["YES", "POSSIBLY", "NO"]},
        "fit_type": {"type": "STRING", "enum": ["DIRECT_FIT", "PARTNERSHIP_REQUIRED", "NOT_SUITABLE"]},
        "organization": {"type": "STRING"},
        "title": {"type": "STRING"},
        "reference": {"type": "STRING"},
        "publication_date_raw": {"type": "STRING"},
        "deadline_raw": {"type": "STRING"},
        "scope_summary": {"type": "STRING"},
        "potential_acnabin_service": {"type": "STRING"},
        "relevance_reason": {"type": "STRING"},
        "eligibility_summary": {"type": "STRING"},
        "eligibility_concerns": {"type": "ARRAY", "items": {"type": "STRING"}},
        "evidence": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "page": {"type": "INTEGER"},
                    "text": {"type": "STRING"}
                },
                "required": ["page", "text"]
            }
        },
        "confidence": {"type": "STRING", "enum": ["HIGH", "MEDIUM", "LOW"]}
    },
    "required": [
        "is_opportunity", "record_type", "ifrs9_ecl_relevant", "category",
        "acnabin_relevant", "fit_type", "title", "confidence"
    ]
}


class GeminiClient:
    """Interacts with Google Gemini API for structured tender extraction."""

    def __init__(self):
        self.api_key = config.gemini_api_key
        self.model = config.gemini_model
        self.daily_limit = int(config.settings.get("ai", {}).get("gemini_daily_call_limit", 500))

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        calls_today = db.get_ai_calls_today("gemini")
        if calls_today >= self.daily_limit:
            logger.warning("Gemini daily free-tier limit reached", extra={"calls_today": calls_today, "limit": self.daily_limit})
            return False
        return True

    async def extract_tender(self, document_context: str, org_hint: str = "") -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Sends document text to Gemini with structured JSON output instructions."""
        if not self.is_available():
            return None, "GEMINI_UNAVAILABLE_OR_QUOTA_EXCEEDED"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        prompt = (
            "You are an expert procurement and tender analyst reviewing public tender/opportunity documents "
            "for ACNABIN Chartered Accountants, Bangladesh. The input text may be in English, Bangla, or mixed bilingual.\n"
            "Extract the opportunity details strictly into the provided JSON schema. All explanations and summaries must be in English.\n"
            "Do NOT invent facts, dates, or reference numbers. Use exact quotes from the document text for evidence.\n"
            f"Known organization hint: {org_hint}\n\n"
            f"Document Content:\n{document_context[:12000]}"
        )

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": EXTRACTION_SCHEMA
            }
        }

        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 429:
                    logger.warning("Gemini API rate limit (429) hit")
                    return None, "GEMINI_RATE_LIMITED"
                resp.raise_for_status()
                data = resp.json()

                # Extract generated text
                candidates = data.get("candidates", [])
                if not candidates:
                    return None, "NO_CANDIDATE_FROM_GEMINI"

                raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                parsed = json.loads(raw_text)

                # Record token usage
                usage = data.get("usageMetadata", {})
                prompt_tokens = usage.get("promptTokenCount", 0)
                cand_tokens = usage.get("candidatesTokenCount", 0)
                db.record_ai_usage("gemini", self.model, prompt_tokens, cand_tokens)

                return parsed, None
        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}", extra={"error": str(e)})
            return None, str(e)
