"""
Gemini Multimodal Vision parser for E-Paper tender extraction.

Ingests high-resolution scanned newspaper pages, extracts tender/EOI/RFP notices,
and returns structured data.
"""

import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional
import httpx


from app.utils.config import config

logger = logging.getLogger("epaper_gemini")

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-flash-latest"
]

PROMPT = """You are an expert procurement and tender analyst in Bangladesh.
Carefully examine the entire newspaper page image.
Detect and extract all Tender Notices, Expression of Interest (EOI), Request for Proposals (RFP), and Procurement Notices published on this page (in English or Bengali).

For each notice, extract a JSON object with:
- organization: Full name of the issuing organization / department (e.g. Dhaka South City Corporation, Bangladesh Bank, UCEP Bangladesh, etc.)
- organization_type: Bank, NGO/INGO, Government, Autonomous, or Private
- title: Complete and descriptive title of the procurement or tender
- ref_no: Reference number, Tender ID, or Memo Number (or null if none)
- publication_date: Publication date in DD/MM/YYYY or YYYY-MM-DD format (or null)
- deadline: Submission deadline date and time if stated (or null)
- category: Category such as IT, Works, Goods, Consulting, Medical, Services, Banking
- details: Brief summary of scope, items, and submission instructions
- contact: Contact email, phone, or office address

Return a valid JSON array of objects. If no tenders are found on this page, return an empty array []."""


class GeminiEpaperParser:
    def __init__(self, api_keys: Optional[List[str]] = None, api_key: Optional[str] = None):
        if api_keys:
            self.api_keys = api_keys
        elif api_key:
            self.api_keys = [api_key]
        else:
            self.api_keys = config.gemini_api_keys

    async def extract_tenders_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> List[Dict[str, Any]]:
        """Extract tenders from page image bytes using Gemini Multimodal API with multi-key failover."""
        if not self.api_keys:
            logger.warning("No GEMINI_API_KEY configured; cannot parse newspaper image.")
            return []

        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_image
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(3):
                for key_idx, key in enumerate(self.api_keys):
                    for model in GEMINI_MODELS:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                        try:
                            # Polite rate limiting between page queries
                            await asyncio.sleep(2.0)
                            resp = await client.post(url, json=payload)
                            if resp.status_code == 200:
                                data = resp.json()
                                text = data["candidates"][0]["content"]["parts"][0]["text"]
                                items = json.loads(text)
                                if isinstance(items, list):
                                    return items
                                elif isinstance(items, dict) and "tenders" in items:
                                    return items["tenders"]
                                return []
                            elif resp.status_code == 429:
                                logger.info(
                                    f"Gemini API key #{key_idx + 1} hit rate limit (429). "
                                    f"Attempt {attempt + 1}/3..."
                                )
                                if len(self.api_keys) > 1:
                                    break  # Try next key
                                else:
                                    # Wait and retry for single key
                                    await asyncio.sleep(8.0)
                                    break
                            elif resp.status_code == 403:
                                logger.warning(f"Gemini API key #{key_idx + 1} returned 403. Switching key...")
                                break
                            elif resp.status_code in (404, 503):
                                logger.info(f"Gemini model {model} status {resp.status_code}, trying fallback model...")
                                continue
                            else:
                                logger.warning(f"Gemini API ({model}) returned status {resp.status_code}: {resp.text[:200]}")
                        except Exception as e:
                            logger.warning(f"Gemini extraction error with {model} (key #{key_idx + 1}): {e}")
                            continue

                if attempt < 2:
                    await asyncio.sleep(5.0)

        return []


