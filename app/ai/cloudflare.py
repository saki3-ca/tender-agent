"""
Cloudflare Workers AI client for multilingual embeddings (@cf/baai/bge-m3).
Used for Stage 1 semantic matching, semantic catch of non-keyword tenders, and vector deduplication.
"""

from typing import Any, Dict, List, Optional, Tuple
import httpx
from app.utils.logging import logger
from app.utils.config import config
from app.db.supabase import db


class CloudflareWorkersAIClient:
    """Interacts with Cloudflare Workers AI REST API for text embeddings."""

    def __init__(self):
        self.account_id = config.cloudflare_account_id
        self.api_token = config.cloudflare_api_token
        self.model = config.cloudflare_embed_model
        self.daily_limit = int(config.settings.get("ai", {}).get("cloudflare_daily_call_limit", 5000))

    def is_available(self) -> bool:
        if not self.account_id or not self.api_token:
            return False
        calls_today = db.get_ai_calls_today("cloudflare")
        if calls_today >= self.daily_limit:
            logger.warning("Cloudflare Workers AI daily free-tier limit reached", extra={"calls_today": calls_today, "limit": self.daily_limit})
            return False
        return True

    async def generate_embedding(self, text: str) -> Tuple[Optional[List[float]], Optional[str]]:
        """Generates embedding vector for text using Cloudflare Workers AI."""
        if not self.is_available():
            return None, "CLOUDFLARE_UNAVAILABLE_OR_QUOTA_EXCEEDED"

        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{self.model}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

        # Truncate input to model limit
        truncated_text = text[:2000]
        payload = {"text": [truncated_text]}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    return None, "CLOUDFLARE_RATE_LIMITED"
                resp.raise_for_status()
                data = resp.json()

                if not data.get("success", False):
                    err = data.get("errors", [{}])[0].get("message", "Unknown error")
                    return None, f"CLOUDFLARE_ERROR: {err}"

                result = data.get("result", {})
                embedding = result.get("data", [[]])[0]

                # Record usage in database
                db.record_ai_usage("cloudflare", self.model, len(truncated_text) // 4, 0)
                return embedding, None
        except Exception as e:
            logger.warning(f"Cloudflare embedding generation skipped/failed: {e}")
            return None, str(e)
