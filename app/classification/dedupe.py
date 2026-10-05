"""
Duplicate detection.

The same notice can appear on a tender page, a notice page and as a PDF. A tender's
identity is scoped to its organization (tenders from different organizations are never merged):

  - if it has a document URL: organization + document URL
  - else if it links to a notice page: organization + notice URL
  - otherwise: organization + normalized title + deadline date

Within a run, notices from the same organization with the same normalized title and the
same deadline date are also merged (same tender published on two pages with different files).
"""

import hashlib
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tender_id(organization_id: str, title: str, deadline: Optional[datetime],
              document_url: Optional[str] = None, link: Optional[str] = None) -> str:
    """Stable id from what the listing itself shows (so it does not change when enrichment adds data)."""
    if document_url:
        basis = f"{organization_id}|doc|{document_url.strip().lower()}"
    elif link:
        basis = f"{organization_id}|link|{link.strip().lower()}"
    else:
        basis = f"{organization_id}|{normalize_title(title)}|{deadline.date().isoformat() if deadline else ''}"
    return "t_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


def dedupe(tenders: List[dict]) -> List[dict]:
    """Removes duplicates within one run, keeping the first and filling its missing fields."""
    by_id: Dict[str, dict] = {}
    by_title: Dict[Tuple[str, str, str], str] = {}
    for t in tenders:
        existing = by_id.get(t["id"])
        if existing is None and t.get("deadline") and not t.get("title_is_weak"):
            key = (t["organization_id"], normalize_title(t["title"]), str(t["deadline"])[:10])
            if key in by_title:
                existing = by_id[by_title[key]]
            else:
                by_title[key] = t["id"]
        if existing is None:
            by_id[t["id"]] = t
            continue
        for field, value in t.items():
            if existing.get(field) in (None, "", []) and value not in (None, "", []):
                existing[field] = value
    return list(by_id.values())
