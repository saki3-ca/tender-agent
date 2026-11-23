"""
Gemini Multimodal Vision parser for E-Paper tender extraction.

Ingests high-resolution scanned newspaper pages, extracts tender/EOI/RFP notices,
and returns structured data.
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional
import httpx


from app.parsers import epaper_ocr
from app.utils.config import config

logger = logging.getLogger("epaper_gemini")

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-flash-latest",
]

# Free-tier per-minute limits: several newspapers are read in parallel, so cap concurrent calls.
_GEMINI_SLOTS = asyncio.Semaphore(2)
# (key, model) pairs that hit their daily quota or are unavailable, for the rest of this run.
_UNUSABLE: set = set()
_TIMEOUTS: Dict[Any, int] = {}
PAGE_SECONDS = 180       # Gemini time per page before falling back to the OCR text
REQUEST_SECONDS = 90.0   # one Gemini request

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
        self.pages_read = 0
        self.pages_failed = 0
        self.pages_ocr_skipped = 0     # OCR found no tender word: Gemini not asked (saves the free quota)
        self.pages_ocr_only = 0        # Gemini failed: the OCR text was used instead
        self.last_error: Optional[str] = None

    async def extract_tenders_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> List[Dict[str, Any]]:
        """
        Tenders on one page/article image; failures are counted (pages_failed / last_error), not raised.
        Free OCR reads the image first (app/parsers/epaper_ocr.py): no tender word -> Gemini is not asked;
        Gemini fails -> the OCR text is the result; Gemini misses a Priority notice OCR sees -> it is added.
        """
        text = await epaper_ocr.ocr_text(image_bytes)
        if epaper_ocr.readable(text) and not epaper_ocr.has_tender_words(text):
            self.pages_read += 1
            self.pages_ocr_skipped += 1
            return []
        items: Optional[List[Dict[str, Any]]] = None
        if self.api_keys:
            async with _GEMINI_SLOTS:
                items = await self._extract(image_bytes, mime_type)
        else:
            self.last_error = "GEMINI_API_KEY not set"
        if items is None:
            if text and epaper_ocr.has_tender_words(text):
                self.pages_read += 1
                self.pages_ocr_only += 1
                return epaper_ocr.ocr_items(text)
            self.pages_failed += 1
            return []
        self.pages_read += 1
        if text and epaper_ocr.has_tender_words(text) and not _any_priority(items):
            items = list(items) + epaper_ocr.ocr_items(text, only_priority=True)
        return items

    async def _extract(self, image_bytes: bytes, mime_type: str) -> Optional[List[Dict[str, Any]]]:

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

        # One page gets at most PAGE_SECONDS of Gemini time; after that the OCR text is used. Without this cap a slow
        # Gemini (timeouts on every model and key, 3 rounds) took 30+ minutes per page and the run was killed.
        page_deadline = time.monotonic() + PAGE_SECONDS
        async with httpx.AsyncClient(timeout=REQUEST_SECONDS) as client:
            for attempt in range(3):
                for key_idx, key in enumerate(self.api_keys):
                    for model in GEMINI_MODELS:
                        if (key, model) in _UNUSABLE:
                            continue
                        left = page_deadline - time.monotonic()
                        if left < 15:
                            self.last_error = f"Gemini too slow: page gave up after {PAGE_SECONDS}s"
                            return None
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                        try:
                            await asyncio.sleep(2.0)
                            resp = await client.post(url, json=payload, headers={"x-goog-api-key": key},
                                                     timeout=min(REQUEST_SECONDS, left))
                            if resp.status_code == 200:
                                data = resp.json()
                                text = data["candidates"][0]["content"]["parts"][0]["text"]
                                items = json.loads(text)
                                if isinstance(items, list):
                                    return items
                                if isinstance(items, dict) and "tenders" in items:
                                    return items["tenders"]
                                return []
                            if resp.status_code in (401, 403):
                                self.last_error = f"Gemini API key #{key_idx + 1} rejected (HTTP {resp.status_code})"
                                _UNUSABLE.update((key, m) for m in GEMINI_MODELS)
                                break
                            if resp.status_code in (404, 429):
                                # 429 on the free tier is almost always the daily per-model quota:
                                # retrying the same model during this run only wastes time.
                                _UNUSABLE.add((key, model))
                            self.last_error = _describe(model, resp)
                            logger.info(f"Gemini {model} returned {resp.status_code}; trying next model")
                        except Exception as e:  # noqa: BLE001
                            self.last_error = f"Gemini {model}: {type(e).__name__}: {str(e)[:120]}"
                            logger.warning(self.last_error)
                            if isinstance(e, httpx.TimeoutException):
                                _TIMEOUTS[(key, model)] = _TIMEOUTS.get((key, model), 0) + 1
                                if _TIMEOUTS[(key, model)] >= 2:      # this model is overloaded today: stop asking it
                                    _UNUSABLE.add((key, model))

                if all((k, m) in _UNUSABLE for k in self.api_keys for m in GEMINI_MODELS):
                    self.last_error = self.last_error if "quota" not in (self.last_error or "") else \
                        "daily Gemini quota used up for every model (free tier: 20 requests per model per day)"
                    return None
                if attempt < 2:
                    await asyncio.sleep(20.0)

        return None


def _any_priority(items: List[Dict[str, Any]]) -> bool:
    from app.classification.relevance import RelevanceClassifier  # local import: avoids a config import cycle
    classifier = RelevanceClassifier()
    return any(classifier.classify(str(i.get("title") or ""), f"{i.get('details') or ''} {i.get('organization') or ''}"
                                   ).is_priority for i in items if isinstance(i, dict))


def _describe(model: str, resp: httpx.Response) -> str:
    try:
        message = resp.json()["error"]["message"]
    except Exception:  # noqa: BLE001
        message = resp.text
    if resp.status_code == 429:
        return f"Gemini {model}: quota exceeded ({message.splitlines()[0][:100]})"
    return f"Gemini {model} HTTP {resp.status_code}: {message[:120]}"


