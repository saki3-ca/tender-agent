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


_STOP = {"the", "and", "for", "of", "to", "in", "on", "at", "a", "an", "by", "with", "from", "under", "rfp", "rfq",
         "eoi", "tor", "tender", "notice", "request", "proposal", "proposals", "quotation", "invitation", "hiring",
         "terms", "reference", "bangladesh", "project", "supply"}


def _tokens(title: str) -> set:
    return {w for w in normalize_title(title).split() if len(w) > 2 and w not in _STOP}


def same_notice(a: dict, b: dict) -> bool:
    """Same organization, same deadline date, and most significant words of the shorter title in the longer one."""
    if a["organization_id"] != b["organization_id"] or not a.get("deadline") or not b.get("deadline"):
        return False
    if str(a["deadline"])[:10] != str(b["deadline"])[:10]:
        return False
    ta, tb = _tokens(a["title"]), _tokens(b["title"])
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(short) >= 2 and len(short & long_) / len(short) >= 0.6


def drop_aggregator_copies(tenders: List[dict]) -> List[dict]:
    """A notice found on an aggregator (e.g. Bdjobs) and on the organization's own page is shown once,
    from the organization's own page."""
    official = [t for t in tenders if not t.get("_aggregator")]
    kept = []
    for t in tenders:
        if t.get("_aggregator"):
            twin = next((o for o in official if same_notice(t, o)), None)
            if twin is not None:
                for field in ("published_date", "description", "reference_number"):
                    if twin.get(field) in (None, "") and t.get(field) not in (None, ""):
                        twin[field] = t[field]
                continue
        kept.append(t)
    return kept


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
    return drop_aggregator_copies(list(by_id.values()))
