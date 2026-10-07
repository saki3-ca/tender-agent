"""
Groq Multimodal Vision parser for E-Paper tender extraction (faster alternative to Gemini).

Uses Groq's Vision API for fast inference on newspaper page images.
"""

import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.utils.config import config

logger = logging.getLogger("epaper_groq")

GROQ_MODEL = "llama-3.2-90b-vision-preview"

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


class GroqEpaperParser:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.groq_api_key
        self.base_url = "https://api.groq.com/openai/v1"

    async def extract_tenders_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> List[Dict[str, Any]]:
        """Extract tenders from page image bytes using Groq Vision API."""
        if not self.api_key:
            logger.warning("No GROQ_API_KEY configured; cannot parse newspaper image.")
            return []

        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": PROMPT
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64_image}"
                            }
                        }
                    ]
                }
            ],
            "temperature": 0.3,
            "max_tokens": 2048
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            for attempt in range(2):
                try:
                    # Polite rate limiting
                    await asyncio.sleep(1.0)

                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        text = data["choices"][0]["message"]["content"]
                        items = json.loads(text)

                        if isinstance(items, list):
                            return items
                        elif isinstance(items, dict) and "tenders" in items:
                            return items["tenders"]
                        return []

                    elif resp.status_code == 429:
                        logger.info(f"Groq API hit rate limit (429). Attempt {attempt + 1}/2...")
                        if attempt < 1:
                            await asyncio.sleep(5.0)
                        continue

                    elif resp.status_code == 401:
                        logger.error(f"Groq API authentication failed (401). Invalid API key?")
                        return []

                    else:
                        logger.warning(f"Groq API returned status {resp.status_code}: {resp.text[:200]}")

                except json.JSONDecodeError:
                    logger.warning(f"Groq returned non-JSON response: {resp.text[:200]}")
                except Exception as e:
                    logger.warning(f"Groq extraction error (attempt {attempt + 1}): {e}")
                    if attempt < 1:
                        await asyncio.sleep(2.0)
                    continue

        return []


class DualParserStrategy:
    """Use Groq when available (fast, cheap), fallback to Gemini (slower, more capable)."""

    def __init__(self):
        from app.parsers.epaper_gemini import GeminiEpaperParser
        self.groq_parser = GroqEpaperParser() if config.groq_api_key else None
        self.gemini_parser = GeminiEpaperParser()
        self.use_groq = bool(self.groq_parser)

    async def extract_tenders_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> List[Dict[str, Any]]:
        """Try Groq first, fall back to Gemini if needed or on error."""
        if self.use_groq:
            try:
                logger.info("Extracting with Groq (fast path)...")
                results = await self.groq_parser.extract_tenders_from_image(image_bytes, mime_type)
                if results:
                    return results
                logger.info("Groq returned empty; falling back to Gemini...")
            except Exception as e:
                logger.warning(f"Groq extraction failed: {e}; falling back to Gemini...")

        logger.info("Extracting with Gemini...")
        return await self.gemini_parser.extract_tenders_from_image(image_bytes, mime_type)
