"""
Free OCR (Tesseract, Bangla + English) for newspaper page images, used around the Gemini reader:

  1. every page/article image is read as text first (no limits, no cost);
  2. images without any tender word (দরপত্র, টেন্ডার, tender, EOI, আগ্রহপত্র, RFP, ...) are not sent to Gemini,
     which keeps the free Gemini quota for the pages that matter;
  3. when Gemini fails (quota, overload), the OCR text itself becomes the result: one item per notice-like
     block, so a Priority notice (e.g. "নগদ সহায়তার আবেদনসমূহ নিরীক্ষণের জন্য বহিঃনিরীক্ষক") still alerts;
  4. when Gemini succeeds but returns no Priority notice for an image whose OCR text has one, the OCR item is
     added as a safety net.

Without Tesseract installed, ocr_text() returns None and everything behaves as before (Gemini only).
"""

import asyncio
import logging
import os
import re
import shutil
from io import BytesIO
from typing import Any, Dict, List, Optional

logger = logging.getLogger("epaper_ocr")

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover
    pytesseract = None
    Image = None

_WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_OCR_SLOTS = asyncio.Semaphore(int(os.getenv("OCR_CONCURRENCY", "3")))
_available: Optional[bool] = None

# Words that appear in (almost) every procurement notice, English and Bangla.
TENDER_WORDS = re.compile(
    r"tender|e-?gp|expression\s+of\s+interest|\bEOI\b|request\s+for\s+(?:proposal|quotation)|\bRFP\b|\bRFQ\b|"
    r"quotation|procurement|invitation\s+for\s+bids?|bid\s+document|"
    r"দরপত্র|টেন্ডার|আগ্রহপত্র|কোটেশন|প্রস্তাব\s*আহ্বান|ক্রয়\s*বিজ্ঞপ্তি|দর\s*আহ্বান",
    re.I)
_ORG_LINE = re.compile(
    r"ব্যাংক|bank|পিএলসি|\bPLC\b|limited|লিমিটেড|মন্ত্রণালয়|ministry|corporation|কর্পোরেশন|বোর্ড|board|authority|"
    r"কর্তৃপক্ষ|directorate|অধিদপ্তর|অধিদফতর|পরিদপ্তর|কার্যালয়|office|foundation|ফাউন্ডেশন|project|প্রকল্প|"
    r"university|বিশ্ববিদ্যালয়|company|কোম্পানি|council|কাউন্সিল", re.I)
MIN_TEXT = 200          # less text than this = OCR could not read the image; do not trust a "no tender" result
WINDOW = 900            # characters around a tender word that form one notice-like block
MAX_PIXELS = 40_000_000  # images (and upscaled images) larger than this are not read
MAX_UPSCALE = 3.0
MAX_ASPECT = 12.0


def available() -> bool:
    global _available
    if _available is None:
        _available = False
        if pytesseract is not None:
            if not shutil.which("tesseract") and os.path.exists(_WINDOWS_TESSERACT):
                pytesseract.pytesseract.tesseract_cmd = _WINDOWS_TESSERACT
            try:
                pytesseract.get_tesseract_version()
                _available = True
            except Exception:  # noqa: BLE001
                logger.warning("Tesseract OCR not installed: newspapers are read by Gemini only")
    return _available


def _ocr_sync(image_bytes: bytes) -> str:
    img = Image.open(BytesIO(image_bytes))
    w, h = img.size
    if not w or not h or w * h > MAX_PIXELS or max(w / h, h / w) > MAX_ASPECT:
        return ""                              # empty, huge or strip-like image: not a newspaper page/advert
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    if w < 1400:                               # small e-paper images: upscale so small print is readable
        scale = min(1400 / w, MAX_UPSCALE, (MAX_PIXELS / (w * h)) ** 0.5)
        if scale > 1:
            img = img.resize((int(w * scale), int(h * scale)))
    try:
        return pytesseract.image_to_string(img, lang="ben+eng")
    except pytesseract.TesseractError:        # Bangla language data missing
        return pytesseract.image_to_string(img, lang="eng")


async def ocr_text(image_bytes: bytes) -> Optional[str]:
    """Text of the image, or None if OCR is not available / failed."""
    if not available():
        return None
    async with _OCR_SLOTS:
        try:
            return await asyncio.to_thread(_ocr_sync, image_bytes)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"OCR failed: {type(e).__name__}: {e}")
            return None


def has_tender_words(text: str) -> bool:
    return bool(TENDER_WORDS.search(text or ""))


def readable(text: Optional[str]) -> bool:
    return text is not None and len(re.sub(r"\s+", "", text)) >= MIN_TEXT


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" -|:;,.")


def _blocks(text: str) -> List[str]:
    """Notice-like blocks: the text around each tender word (overlapping windows merged)."""
    spans: List[List[int]] = []
    for m in TENDER_WORDS.finditer(text):
        start, end = max(0, m.start() - WINDOW), min(len(text), m.end() + WINDOW)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    return [text[a:b] for a, b in spans]


_ORG_NAME = re.compile(
    r"(?:[ঀ-৿]+\s+){0,3}(?:ব্যাংক(?:\s+পিএলসি)?|বাংলাদেশ\s+ব্যাংক)|"
    r"(?:[A-Z][\w&.-]*\s+){0,4}(?:Bank(?:\s+PLC|\s+Limited)?|PLC|Limited|Ltd\.?|Corporation|Authority|Foundation|Company)",
    re.I)


def _organization(block: str) -> str:
    """Name of the issuer: a bank/company name if one is written, else the first office-like line."""
    for m in _ORG_NAME.finditer(block):          # skip fragments such as a lone "PLC" from a garbled logo
        name = _clean(m.group(0))
        if len(name) >= 8 and " " in name:
            return name
    return next((_clean(l) for l in block.splitlines() if _ORG_LINE.search(l) and len(_clean(l)) >= 8), "")


def _title(block: str) -> str:
    """The subject line: the first line with a tender word, with the line before it (subjects run over two lines)."""
    lines = [_clean(l) for l in block.splitlines() if len(_clean(l)) >= 12]
    for i, line in enumerate(lines):
        if TENDER_WORDS.search(line):
            title = f"{lines[i - 1]} {line}" if i > 0 and len(line) < 120 else line
            return title[:220]
    return (lines[0] if lines else "Notice in newspaper")[:220]


def ocr_items(text: str, only_priority: bool = False) -> List[Dict[str, Any]]:
    """Tender items built from OCR text (Gemini's item format). only_priority: just the Priority blocks."""
    from app.classification.relevance import RelevanceClassifier  # local import: avoids a config import cycle
    classifier = RelevanceClassifier()
    items: List[Dict[str, Any]] = []
    for block in _blocks(text):
        rel = classifier.classify("", block)
        if only_priority and not rel.is_priority:
            continue
        org = _organization(block)
        items.append({
            "organization": org[:120] or "See newspaper page",
            "organization_type": "",
            "title": "[OCR] " + _title(block),
            "ref_no": None, "publication_date": None, "deadline": None,
            "category": "Read by OCR - check the page",
            "details": _clean(block)[:1500],
            "contact": "",
            "_ocr": True,
        })
    return items
