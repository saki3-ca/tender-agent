"""
Gemini Multimodal Vision parser for E-Paper tender extraction.

Ingests high-resolution scanned newspaper pages, extracts tender/EOI/RFP notices,
and returns structured data.
"""

import asyncio
import base64
import itertools
import json
import logging
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
import httpx


from app.utils.config import config

logger = logging.getLogger("epaper_gemini")

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-flash-latest",
]

# Free-tier per-minute limits: several newspapers are read in parallel, so cap concurrent calls.
_GEMINI_SLOTS = asyncio.Semaphore(3)
# (key, model) pairs that hit their daily quota or are unavailable, for the rest of this run.
_UNUSABLE: set = set()
# (key, model) pairs that hit a per-minute limit: usable again after this time (time.monotonic()).
_COOLDOWN: Dict[Tuple[str, str], float] = {}
# Every page starts with the next key, so the daily quota of all keys is used evenly.
_ROTATION = itertools.count()
# Pages read per key, for the run summary.
_USAGE: Counter = Counter()

PROMPT = """You are an expert procurement and tender analyst in Bangladesh.
Carefully examine the entire newspaper page image.
Detect and extract all Tender Notices, Expression of Interest (EOI), Request for Proposals (RFP), and Procurement Notices published on this page. The notices are in English or in Bengali.

Write every field in ENGLISH, translating Bengali text (keep personal names, reference numbers and acronyms as they are printed). For each notice, extract a JSON object with:
- organization: Full official name of the issuing organization / department in English, using its well-known English name (e.g. Dhaka South City Corporation, Bangladesh Bank, Sonali Bank PLC, UCEP Bangladesh)
- organization_type: Bank, NGO/INGO, Government, Autonomous, or Private
- title: Complete and descriptive title of the procurement or tender, in English
- title_original: The same title exactly as printed in the newspaper (Bengali or English)
- ref_no: Reference number, Tender ID, or Memo Number (or null if none)
- publication_date: Publication date in DD/MM/YYYY or YYYY-MM-DD format (or null)
- deadline: Submission deadline date and time if stated (or null)
- category: Category such as IT, Works, Goods, Consulting, Audit, Medical, Services, Banking
- details: Brief summary in English of scope, items, and submission instructions
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
        self.last_error: Optional[str] = None

    async def extract_tenders_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> List[Dict[str, Any]]:
        """Tenders on one page image; failures are counted (pages_failed / last_error), not raised."""
        if not self.api_keys:
            self.pages_failed += 1
            self.last_error = "GEMINI_API_KEY not set"
            return []
        async with _GEMINI_SLOTS:
            items = await self._extract(image_bytes, mime_type)
        if items is None:
            self.pages_failed += 1
            return []
        self.pages_read += 1
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

        async with httpx.AsyncClient(timeout=120.0) as client:
            for attempt in range(3):
                start = next(_ROTATION) % len(self.api_keys)
                order = [(i, self.api_keys[i]) for i in list(range(start, len(self.api_keys))) + list(range(start))]
                for key_idx, key in order:
                    for model in GEMINI_MODELS:
                        if (key, model) in _UNUSABLE or _COOLDOWN.get((key, model), 0) > time.monotonic():
                            continue
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                        try:
                            await asyncio.sleep(2.0)
                            resp = await client.post(url, json=payload, headers={"x-goog-api-key": key})
                            if resp.status_code == 200:
                                data = resp.json()
                                text = data["candidates"][0]["content"]["parts"][0]["text"]
                                items = json.loads(text)
                                _USAGE[key] += 1
                                if isinstance(items, list):
                                    return items
                                if isinstance(items, dict) and "tenders" in items:
                                    return items["tenders"]
                                return []
                            if resp.status_code in (401, 403):
                                self.last_error = f"Gemini API key #{key_idx + 1} rejected (HTTP {resp.status_code})"
                                _UNUSABLE.update((key, m) for m in GEMINI_MODELS)
                                break
                            if resp.status_code == 404:
                                _UNUSABLE.add((key, model))
                            elif resp.status_code == 429:
                                kind, retry = quota_kind(resp)
                                if kind == "day":
                                    # the daily quota of this model is used up: retrying it wastes the run
                                    _UNUSABLE.add((key, model))
                                else:
                                    # per-minute limit: usable again shortly, other keys/models go first
                                    _COOLDOWN[(key, model)] = time.monotonic() + max(retry, 10.0) + 1.0
                            self.last_error = _describe(model, resp)
                            logger.info(f"Gemini {model} (key #{key_idx + 1}) returned {resp.status_code}; trying the next one")
                        except Exception as e:  # noqa: BLE001
                            self.last_error = f"Gemini {model}: {type(e).__name__}: {str(e)[:120]}"
                            logger.warning(self.last_error)

                if all((k, m) in _UNUSABLE for k in self.api_keys for m in GEMINI_MODELS):
                    self.last_error = self.last_error if "quota" not in (self.last_error or "") else \
                        "daily Gemini quota used up for every model (free tier: 20 requests per model per day)"
                    return None
                if attempt < 2:
                    now = time.monotonic()
                    waits = [_COOLDOWN[(k, m)] - now for k in self.api_keys for m in GEMINI_MODELS
                             if (k, m) not in _UNUSABLE and _COOLDOWN.get((k, m), 0) > now]
                    # per-minute limits: wait until the first one is open again; otherwise a short pause
                    await asyncio.sleep(min(max(min(waits), 1.0), 70.0) if waits else 20.0)

        return None


def quota_kind(resp: httpx.Response) -> Tuple[str, float]:
    """For a 429: ("day", _) when the daily quota is used up, ("minute", wait_seconds) for a per-minute limit.

    Google names the exhausted quota in the error details (…PerDay… / …PerMinute…) and says how long to wait.
    When nothing says "minute", it is treated as the daily quota (waiting would only waste the run).
    """
    retry = 0.0
    day: Optional[bool] = None
    try:
        for d in resp.json()["error"].get("details", []):
            kind = str(d.get("@type", ""))
            if kind.endswith("RetryInfo"):
                m = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
                if m:
                    retry = float(m.group(1))
            if kind.endswith("QuotaFailure"):
                for v in d.get("violations", []):
                    ident = f"{v.get('quotaId', '')} {v.get('quotaMetric', '')}"
                    if "PerDay" in ident:
                        day = True
                    elif "PerMinute" in ident and day is None:
                        day = False
    except Exception:  # noqa: BLE001
        pass
    if day is None:
        low = (resp.text or "").lower()
        if "per day" in low or "perday" in low or "daily" in low:
            day = True
        elif "per minute" in low or "perminute" in low or 0 < retry <= 90:
            day = False
        else:
            day = True
    return ("day", retry) if day else ("minute", retry)


def usage_summary(all_keys: List[str]) -> str:
    """One line for the run log: how much of the Gemini quota this run used."""
    used = sum(1 for k in all_keys if _USAGE[k] > 0)
    pairs = len(all_keys) * len(GEMINI_MODELS)
    spent = sum(1 for (k, m) in _UNUSABLE if k in all_keys and m in GEMINI_MODELS)
    return (f"Gemini: {sum(_USAGE[k] for k in all_keys)} pages read; {used} of {len(all_keys)} keys used; "
            f"daily quota used up for {spent} of {pairs} key/model pairs")


def _describe(model: str, resp: httpx.Response) -> str:
    try:
        message = resp.json()["error"]["message"]
    except Exception:  # noqa: BLE001
        message = resp.text
    if resp.status_code == 429:
        return f"Gemini {model}: quota exceeded ({message.splitlines()[0][:100]})"
    return f"Gemini {model} HTTP {resp.status_code}: {message[:120]}"


