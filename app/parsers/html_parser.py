"""
HTML parser for extracting tender notices, tables, and document links from web pages.
Normalizes main text for change detection fingerprinting.
"""

import re
import hashlib
from urllib.parse import urljoin, urlparse
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from app.parsers.date_cleaner import normalize_bangla_digits, parse_deadline


def compute_content_hash(text: str) -> str:
    """Computes SHA-256 hash of normalized main text."""
    normalized = re.sub(r'\s+', ' ', text.strip().lower())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def clean_html_text(html_content: str) -> str:
    """Strips boilerplate, scripts, styles and extracts readable text."""
    soup = BeautifulSoup(html_content, "lxml")
    for el in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        el.decompose()
    return soup.get_text(separator="\n", strip=True)


class HtmlNoticeExtractor:
    """Extracts tender records and document attachments from HTML pages."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    def extract_candidates(self, html_content: str) -> List[Dict[str, Any]]:
        """Parses HTML and extracts tender rows or notices with attached document links."""
        soup = BeautifulSoup(html_content, "lxml")
        candidates: List[Dict[str, Any]] = []

        # 1. Look for tables containing tender/procurement rows
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
            
            # Check if table headers look like a tender table
            is_tender_table = any(
                term in " ".join(headers) for term in [
                    "tender", "title", "subject", "description", "memo", "ref",
                    "দরপত্র", "বিষয়", "বিজ্ঞপ্তি", "last date", "deadline"
                ]
            )

            for tr in rows[1:]:
                cells = tr.find_all(["td", "th"])
                if not cells:
                    continue

                row_text = " ".join([c.get_text(separator=" ", strip=True) for c in cells])
                if len(row_text) < 10:
                    continue

                # Find any document link in this row
                doc_link = None
                for a in tr.find_all("a", href=True):
                    href = a["href"].strip()
                    full_href = urljoin(self.base_url, href)
                    if any(full_href.lower().endswith(ext) for ext in [".pdf", ".docx", ".doc", ".xlsx", ".xls"]) or "download" in full_href.lower() or "tender" in full_href.lower():
                        doc_link = full_href
                        break

                # Extract title and possible dates from row text
                dt_utc, dt_note = parse_deadline(row_text)

                candidates.append({
                    "title": cells[1].get_text(strip=True) if len(cells) > 1 and len(cells[1].get_text(strip=True)) > 5 else cells[0].get_text(strip=True),
                    "raw_text": row_text,
                    "deadline_utc": dt_utc,
                    "deadline_raw": row_text,
                    "document_url": doc_link,
                    "source_url": self.base_url,
                    "content_hash": compute_content_hash(row_text)
                })

        # 2. If no candidate tables found, inspect list items or anchor links directly
        if not candidates:
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                href = a["href"].strip()
                full_url = urljoin(self.base_url, href)

                # If link points to PDF or has procurement keywords in anchor text
                is_doc = any(full_url.lower().endswith(ext) for ext in [".pdf", ".docx", ".doc", ".xlsx"])
                has_keywords = any(kw in text.lower() for kw in ["tender", "rfp", "eoi", "quotation", "audit", "দরপত্র", "বিজ্ঞপ্তি"])

                if is_doc or has_keywords:
                    dt_utc, dt_note = parse_deadline(text)
                    candidates.append({
                        "title": text or urlparse(full_url).path.split("/")[-1],
                        "raw_text": text,
                        "deadline_utc": dt_utc,
                        "deadline_raw": text,
                        "document_url": full_url if is_doc else None,
                        "source_url": full_url if not is_doc else self.base_url,
                        "content_hash": compute_content_hash(text + full_url)
                    })

        return candidates
