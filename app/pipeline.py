"""
Tender monitoring pipeline (one run).

    SOURCE CONFIGURATION      config/sources.json (+ organizations / 30 target banks)
      → FETCH                 source page (failures recorded per source, never fatal)
      → EXTRACT               tender listings from the page
      → ENRICH                notice detail page / tender document (dates, real title, scope)
      → DATES                 publication date + deadline (parsed, never guessed)
      → STATUS / ACTIVE       open vs closed/cancelled/awarded; ACTIVE rule
      → GENERAL               every active tender
      → RELEVANCE             ACNABIN services → Priority; IFRS 9 / ECL flag
      → DEDUPLICATE
      → STORE                 tenders + source_status (dashboard reads v_active_tenders)

General is decided before relevance: relevance never removes a tender from General.
"""

import asyncio
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.alerts.email import EmailAlerter
from app.alerts.telegram import TelegramAlerter
from app.classification.dedupe import dedupe, tender_id
from app.classification.relevance import RelevanceClassifier
from app.classification.status import StatusDetector, is_active
from app.crawler.crawler import TenderCrawler
from app.db.supabase import Store
from app.parsers.date_cleaner import DHAKA_TZ, deadline_datetime, extract_dates, find_dates
from app.parsers.document_parser import extract_document_text, is_readable_document
from app.parsers.html_parser import (
    HtmlNoticeExtractor, Listing, clean_html_text, is_document_url, is_weak_title, page_document_links,
)
from app.utils.config import config
from app.utils.logging import logger

BANGLADESH = re.compile(
    r"bangladesh|dhaka|cox'?s\s*bazar|chatt?ogram|chittagong|sylhet|rajshahi|khulna|barisal|barishal|"
    r"rangpur|mymensingh|rohingya|ukhia|teknaf|বাংলাদেশ|ঢাকা", re.I)

TITLE_PATTERNS = [
    # Bangladesh e-GP notice PDF where the label and value columns are interleaved:
    #   "Package No. and <first line of description>\nDescription : <rest>\nCategory :"
    re.compile(r"Package\s+No\.?\s+and\s+(?!Description)(.{5,200}?)\n\s*Description\s*:\s*(.{0,300}?)\s*(?:\n\s*Category\s*:|\Z)",
               re.I | re.S),
    # Bangladesh e-GP notice: "Tender/Proposal Package No. and Description : <multi-line text> Category :"
    re.compile(r"No\.?\s*and\s*Description\s*:\s*(.{10,500}?)\s*(?:\n\s*Category\s*:|\n\s*Scheduled|\Z)", re.I | re.S),
    re.compile(r"(?:subject|sub|name of (?:the )?(?:work|works|services?|assignment|package|goods|procurement)|"
               r"title of (?:the )?(?:assignment|tender|work|consultancy)|description of (?:the )?(?:works?|goods|services?)|"
               r"বিষয়)\s*[:：ঃ\-–]\s*(.{10,220})", re.I),
    re.compile(r"^\s*((?:invitation for|request for|tender (?:notice )?for|procurement of|supply of|selection of|"
               r"hiring of|appointment of|expression of interest for|terms of reference for).{10,200})$", re.I | re.M),
]
DOC_TEXT_KEEP = 6000         # characters of document text stored for re-classification
STORE_EXPIRED_DAYS = 30      # expired tenders older than this are not stored


def derive_title(text: str) -> Optional[str]:
    """A descriptive title from notice/document text, e.g. the 'Subject:' line."""
    head = (text or "")[:5000]
    for pattern in TITLE_PATTERNS:
        m = pattern.search(head)
        if m:
            title = re.sub(r"\s+", " ", " ".join(g for g in m.groups() if g)).strip(" .:-–")
            title = re.split(r"\s(?:Ref|Memo|Date)\s*[:.]", title)[0]
            # drop trailing dates/times copied from a table row ("... for 14-Oct-2026 14-Oct-2026")
            title = re.split(r"\s[0-9lI]{1,2}[-/.](?:\d{1,2}|[A-Za-z]{3})[-/.]\d{2,4}", title)[0].strip(" .:-–")
            if len(title) > 200:
                title = title[:200].rsplit(" ", 1)[0] + "…"
            # a fragment starting mid-sentence ("main line with ... for") is not a usable title
            if len(title.split()) >= 3 and not title[0].islower() and not is_weak_title(title):
                return title
    return None


def is_readable(text: str) -> bool:
    """False for text extracted from PDFs with broken font encoding (e.g. 't;.1;+ :i'..')."""
    words = re.findall(r"\S+", text or "")
    if len(words) < 5:
        return False
    wordlike = sum(1 for w in words if re.fullmatch(r"\(?[^\W\d_][\wঀ-৿'’&/-]*[.,;:)।]*|\d[\d,./-]*", w))
    return wordlike / len(words) >= 0.6


def _excerpt(text: str, title: str, limit: int = 400) -> Optional[str]:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t or not is_readable(t[:limit]):
        return None
    if title and t.lower().startswith(title.lower()[:40]):
        t = t[len(title):].strip(" |:-")
    return t[:limit] or None


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("\u2019", "'")).strip()


def _norm_org(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower().replace("&", " and ")).strip()


_ORG_NAME_INDEX: Dict[str, str] = {}
_FINANCIAL_ORG = re.compile(r"\bbank\b|leasing|financ|insurance|securities|investment", re.I)


def organization_for_name(name: str) -> Dict[str, Any]:
    """Configured organization with this name (or alias); otherwise a new one, sector guessed from the name."""
    if not _ORG_NAME_INDEX:
        names = [(o["organization_id"], [o["canonical_name"], *o.get("aliases", [])]) for o in config.organizations]
        names += [(b["id"], [b["canonical_name"], *b.get("aliases", [])]) for b in config.ifrs9_banks]
        for oid, variants in names:
            for n in variants:
                for key in (_norm_org(n), _norm_org(re.sub(r"\(.*?\)", "", n))):
                    if len(key) > 4:
                        _ORG_NAME_INDEX.setdefault(key, oid)
    for key in (_norm_org(name), _norm_org(re.sub(r"\(.*?\)", "", name))):
        oid = _ORG_NAME_INDEX.get(key)
        if oid and config.organization(oid):
            return config.organization(oid)
    slug = _norm_org(name).replace(" ", "_")[:50]
    return {"organization_id": f"ext_{slug}", "name": name, "type": None,
            "sector": "BANK" if _FINANCIAL_ORG.search(name) else "NGO", "is_target_bank": False}


def source_org(source: Dict[str, Any]) -> Dict[str, Any]:
    """Organization of a source: from config, or given by the Admin page for new organizations."""
    return source.get("_org") or config.organization(source["organization_id"])


def merge_admin_sources(config_sources: List[Dict[str, Any]], admin_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Applies the dashboard Admin page entries to config/sources.json:
      - a row whose source_id exists in the config replaces that source's URL / options;
      - any other row is a new source (for an existing organization, or a new one).
    """
    by_id = {s["id"]: dict(s) for s in config_sources}
    for row in admin_rows:
        sid, url = row.get("source_id"), (row.get("url") or "").strip()
        if not sid or not re.match(r"https?://", url):
            continue
        options = {k: row[k] for k in ("requires_js", "verify_ssl", "country_filter", "enabled") if row.get(k) is not None}
        if sid in by_id:
            base = by_id[sid]
            # Special handling is kept if either the config or the admin entry asks for it
            base.update(
                url=url, admin=True,
                enabled=options.get("enabled", base.get("enabled", True)),
                requires_js=bool(base.get("requires_js") or options.get("requires_js")),
                country_filter=bool(base.get("country_filter") or options.get("country_filter")),
                verify_ssl=bool(base.get("verify_ssl", True) and options.get("verify_ssl", True)),
            )
            continue
        org = config.organization(row["organization_id"]) if row.get("organization_id") else None
        if org is None:
            slug = re.sub(r"[^a-z0-9]+", "_", (row.get("organization_name") or "org").lower()).strip("_")[:40]
            org = {"organization_id": row.get("organization_id") or f"admin_{slug}",
                   "name": row.get("organization_name") or "Unnamed organization",
                   "type": None, "sector": row.get("sector") or "NGO", "is_target_bank": False}
        by_id[sid] = {"id": sid, "url": url, "organization_id": org["organization_id"], "tier": 1,
                      "admin": True, "_org": org, **options}
    return list(by_id.values())


class Monitor:
    def __init__(self, store: Optional[Store] = None, now: Optional[datetime] = None):
        self.store = store or Store()
        self.now = now or datetime.now(DHAKA_TZ)
        self.today = self.now.astimezone(DHAKA_TZ).date()
        self.crawler = TenderCrawler()
        self.classifier = RelevanceClassifier()
        self.status_detector = StatusDetector()
        self.alerter = TelegramAlerter(self.store)
        self.emailer = EmailAlerter(self.store)
        self.max_docs = int(config.crawler_setting("max_documents_per_source", 25))
        self.doc_chars = int(config.crawler_setting("document_text_chars", 20000))
        self.concurrency = int(config.crawler_setting("concurrent_sources", 6))
        self.deadline_ts = time.monotonic() + config.run_time_budget_minutes * 60 - 30
        self.stats = {"sources_total": 0, "sources_ok": 0, "sources_failed": 0, "sources_skipped": 0,
                      "listings": 0, "documents_read": 0, "tenders_stored": 0, "active_general": 0,
                      "active_priority": 0, "active_ifrs9": 0, "new_tenders": 0, "alerts_sent": 0, "emails_sent": 0}

    # ------------------------------------------------------------------- run
    async def run(self, source_ids: Optional[List[str]] = None, sector: Optional[str] = None) -> Dict[str, Any]:
        started = time.monotonic()
        run_id = self.store.run_started()
        sources = [s for s in merge_admin_sources(config.sources, self.store.admin_sources())
                   if s.get("enabled", True)]
        if source_ids:
            sources = [s for s in sources if s["id"] in source_ids]
        if sector:
            sources = [s for s in sources if source_org(s)["sector"] == sector]
        self.stats["sources_total"] = len(sources)
        states = self.store.source_states()
        sem = asyncio.Semaphore(self.concurrency)

        async def guarded(source):
            async with sem:
                if time.monotonic() > self.deadline_ts:
                    return [], self._state_row(source, states.get(source["id"]), None, "SKIPPED_TIME_BUDGET", 0)
                try:
                    return await self.process_source(source, states.get(source["id"]))
                except Exception as e:  # noqa: BLE001 - one source must never stop the run
                    logger.error(f"Source {source['id']} failed: {e}", extra={"source_id": source["id"]})
                    return [], self._state_row(source, states.get(source["id"]), None, f"ERROR: {str(e)[:200]}", 0)

        results = await asyncio.gather(*(guarded(s) for s in sources))
        await self.crawler.close()

        all_tenders: List[Dict[str, Any]] = []
        state_rows = []
        for tenders, state in results:
            all_tenders.extend(tenders)
            state_rows.append(state)
            if state["error"] == "SKIPPED_TIME_BUDGET":
                self.stats["sources_skipped"] += 1
            elif state["ok"]:
                self.stats["sources_ok"] += 1
            else:
                self.stats["sources_failed"] += 1

        all_tenders = dedupe(all_tenders)
        known = self.store.known_tenders([t["id"] for t in all_tenders])
        for t in all_tenders:
            if t["id"] in known:
                t["first_seen"] = _to_dt(known[t["id"]].get("first_seen")) or t["first_seen"]
                # keep the first-seen baseline flag; evidence of old dates can still mark it as not new
                t["is_baseline"] = bool(known[t["id"]].get("is_baseline")) or t.get("_old_dates", False)
            t["_active"] = is_active(t["status"], t["published_date"], t["deadline"],
                                     t["first_seen"], t["is_baseline"], self.now)
        new_ids = {t["id"] for t in all_tenders} - set(known)
        self.stats["new_tenders"] = len(new_ids)

        stored = [self._row(t) for t in all_tenders]
        try:
            self.store.save_tenders(stored, known.keys())
            self.store.save_source_states(state_rows)
        except Exception as e:
            logger.error(f"Saving results failed: {e}")
            self.store.run_finished(run_id, "FAILED", self.stats, error_summary=str(e)[:500])
            raise
        self.stats["tenders_stored"] = len(stored)

        for t in all_tenders:
            if not t["_active"]:
                continue
            self.stats["active_general"] += 1
            if t["is_priority"]:
                self.stats["active_priority"] += 1
                if t["is_ifrs9"]:
                    self.stats["active_ifrs9"] += 1
                if t["id"] in new_ids and not t["is_baseline"]:
                    if await self.alerter.send_new_priority(t):
                        self.stats["alerts_sent"] += 1
                    self.emailer.add(t)
        self.stats["emails_sent"] = await self.emailer.flush()

        self.stats["duration_seconds"] = round(time.monotonic() - started, 1)
        failed = [f"{s['source_id']}: {s['error']}" for s in state_rows if not s["ok"]]
        self.store.run_finished(run_id, "COMPLETED", self.stats,
                                error_summary="; ".join(failed)[:2000] if failed else None)
        self.results = all_tenders
        self.source_results = state_rows
        return self.stats

    # ---------------------------------------------------------------- source
    async def process_source(self, source: Dict[str, Any], state: Optional[Dict[str, Any]]
                             ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if source.get("type") == "bdjobs_json":
            status_code, error, pairs = await self._bdjobs_listings(source)
        else:
            status_code, error, pairs = await self._page_listings(source)
        if error:
            logger.warning(f"{source['id']}: {error}", extra={"url": source["url"], "status": status_code})
            return [], self._state_row(source, state, status_code, error, 0)
        listings = [l for l, _ in pairs]
        self.stats["listings"] += len(listings)
        # Aggregators link to full notice pages: their text counts as notice text, not as a tender document
        notice_pages = bool(source.get("notice_pages"))
        max_docs = int(source.get("max_documents") or self.max_docs)
        # Notices found on the first successful crawl of a page are the baseline: without a date
        # we cannot tell whether they are new, so they are not treated as recently published.
        # A notice is "new" only if the same page was read successfully, with listings, in the previous run.
        baseline = not (state and state.get("first_ok") and state.get("url") == source["url"]
                        and state.get("ok") and (state.get("listings_found") or 0) > 0)

        candidate_ids = [self._listing_id(org, l) for l, org in pairs]
        known = self.store.known_tenders(candidate_ids)
        docs_budget = max_docs
        tenders: List[Dict[str, Any]] = []
        for (listing, org), tid in zip(pairs, candidate_ids):
            status = self.status_detector.status(f"{listing.title} {listing.row_text}")
            detail_text, doc_text = "", ""
            prev = known.get(tid)
            if prev and prev.get("document_checked"):
                if notice_pages:
                    detail_text = prev.get("document_text") or ""
                else:
                    doc_text = prev.get("document_text") or ""
                listing.published = listing.published or _to_date(prev.get("published_date"))
                if listing.deadline is None and prev.get("deadline"):
                    listing.deadline = _to_dt(prev["deadline"])
                    listing.deadline_has_time = bool(prev.get("deadline_has_time"))
                if listing.title_is_weak and prev.get("title") and not is_weak_title(prev["title"]):
                    listing.title, listing.title_is_weak = prev["title"], False
                document_checked = True
            elif status == "OPEN" and docs_budget > 0 and self._worth_enriching(listing):
                docs_budget -= 1
                detail_text, doc_text = await self._enrich(listing, source, follow_documents=not notice_pages)
                document_checked = True
            else:
                document_checked = False

            if source.get("country_filter") and not BANGLADESH.search(
                    " ".join([listing.title, listing.row_text, detail_text, doc_text[:4000]])):
                continue

            old_dates = self._only_old_dates(listing)
            tender = self._build(source, org, listing, tid, status, detail_text, doc_text, document_checked,
                                 baseline or old_dates)
            if tender:
                tender["_old_dates"] = old_dates
            if tender:
                tenders.append(tender)
        return tenders, self._state_row(source, state, status_code, None, len(listings))

    async def _page_listings(self, source: Dict[str, Any]):
        """Listings from an organization's own tender page; all belong to that organization."""
        page = await self.crawler.fetch_page(source)
        if not page.ok:
            return page.status, page.error, []
        org = source_org(source)
        listings = HtmlNoticeExtractor(page.final_url or source["url"], today=self.today).extract(page.text)
        return page.status, None, [(l, org) for l in listings]

    async def _bdjobs_listings(self, source: Dict[str, Any]):
        """
        Bdjobs.com "Tender/EOI" section (the JSON feed behind bdjobs.com/h/). Each notice is attributed
        to the organization that published it; the Bdjobs notice page is the link.
        """
        res = await self.crawler.fetch(source["url"], verify_ssl=source.get("verify_ssl", True), binary=True)
        if not res.ok:
            return res.status, res.error, []
        try:
            data = json.loads(res.content.decode("utf-8-sig"))
        except ValueError as e:
            return res.status, f"INVALID_JSON: {e}", []
        pairs = []
        for company in data if isinstance(data, list) else []:
            name = _clean_name((company.get("CompanyName") or {}).get("En") or "")
            if not name:
                continue
            org = organization_for_name(name)
            published = _to_date(company.get("PublishedOn"))
            deadline = _to_date(company.get("Deadline"))
            for t in company.get("Tenders") or []:
                title = re.sub(r"\s+", " ", (t.get("Titles") or {}).get("En") or "").strip()
                link = (t.get("Link") or "").strip()
                if len(title) < 5 or not link.startswith("http"):
                    continue
                listing = Listing(title=title, row_text=f"{name} {title}", source_url=source["url"], link=link)
                listing.published = published if published and published <= self.today else None
                if deadline:
                    listing.deadline, listing.deadline_has_time = deadline_datetime(deadline, None)
                listing.title_is_weak = is_weak_title(title)
                pairs.append((listing, org))
        return res.status, None, pairs

    def _only_old_dates(self, listing: Listing) -> bool:
        """The listing shows dates, all older than the recent window: it is evidently not a new notice."""
        if listing.published or listing.deadline:
            return False
        dates = [f.value for f in find_dates(f"{listing.title} {listing.row_text}", self.today)]
        cutoff = self.today - timedelta(days=config.recent_publication_days)
        return bool(dates) and all(d < cutoff for d in dates)

    def _worth_enriching(self, listing: Listing) -> bool:
        """Only potentially active notices are worth downloading."""
        if listing.deadline is not None:
            return listing.deadline >= self.now
        if listing.published is not None:
            return listing.published >= self.today - timedelta(days=45)
        return True

    async def _enrich(self, listing: Listing, source: Dict[str, Any], follow_documents: bool = True) -> Tuple[str, str]:
        """Text of the notice detail page and of the tender document, if any."""
        verify = source.get("verify_ssl", True)
        detail_text, doc_text = "", ""
        if listing.link and not is_document_url(listing.link):
            page = await self.crawler.fetch(listing.link, verify_ssl=verify)
            if page.ok and "html" in (page.content_type or "html"):
                detail_text = clean_html_text(page.text, max_chars=8000)
                if not listing.document_url and follow_documents:
                    docs = page_document_links(page.text, page.final_url or listing.link)
                    listing.document_url = docs[0] if docs else None
        if listing.document_url and is_readable_document(listing.document_url):
            doc = await self.crawler.fetch(listing.document_url, verify_ssl=verify, binary=True)
            if doc.ok:
                doc_text = extract_document_text(doc.content, listing.document_url, doc.content_type,
                                                 max_chars=self.doc_chars)
                if doc_text:
                    self.stats["documents_read"] += 1
        return detail_text, doc_text

    # ----------------------------------------------------------------- build
    @staticmethod
    def _listing_id(org: Dict[str, Any], listing: Listing) -> str:
        return tender_id(org["organization_id"], listing.title, listing.deadline, listing.document_url, listing.link)

    def _build(self, source, org, listing: Listing, tid: str, status: str, detail_text: str,
               doc_text: str, document_checked: bool, baseline: bool) -> Optional[Dict[str, Any]]:
        extra_text = "\n".join(t for t in (detail_text, doc_text) if t)
        if extra_text:
            info = extract_dates(extra_text, self.today)
            if listing.deadline is None and info.deadline:
                listing.deadline, listing.deadline_has_time = info.deadline, info.deadline_has_time
            if listing.published is None and info.published:
                listing.published = info.published
            if listing.title_is_weak:
                better = derive_title(detail_text) or derive_title(doc_text)
                if better:
                    # a memo number used as the title becomes the reference ("SBPLC/EED/ED/Godown/2026/140")
                    if not listing.reference and re.search(r"\d", listing.title) and len(listing.title.split()) <= 3:
                        listing.reference = listing.title
                    listing.title, listing.title_is_weak = better, False

        if listing.deadline and listing.deadline < self.now - timedelta(days=STORE_EXPIRED_DAYS):
            return None  # long expired: not worth storing

        description = _excerpt(detail_text, listing.title) or _excerpt(doc_text, listing.title)
        rel = self.classifier.classify(
            listing.title,
            description="\n".join([listing.row_text, detail_text[:3000]]),
            document_text=doc_text,
        )
        now_utc = datetime.now(timezone.utc)
        tender = {
            "id": tid,
            "sector": org["sector"],
            "organization_id": org["organization_id"],
            "organization_name": org["name"],
            "organization_type": org.get("type"),
            "is_target_bank": org["is_target_bank"],
            "title": listing.title[:500],
            "title_is_weak": listing.title_is_weak,
            "description": description,
            "reference_number": listing.reference,
            "published_date": listing.published,
            "deadline": listing.deadline,
            "deadline_has_time": listing.deadline_has_time,
            "status": status,
            "is_priority": rel.is_priority,
            "is_ifrs9": rel.is_ifrs9,
            "categories": rel.categories,
            "matched_keywords": rel.matched_keywords,
            "source_id": source["id"],
            "source_url": source.get("public_url") or source["url"],
            "notice_url": listing.link,
            "document_url": listing.document_url,
            "document_text": ((detail_text if source.get("notice_pages") else doc_text) or doc_text
                              or detail_text)[:DOC_TEXT_KEEP] or None,
            "document_checked": document_checked,
            "is_baseline": baseline,
            "first_seen": now_utc,
            "last_seen": now_utc,
            "_aggregator": bool(source.get("notice_pages")),
        }
        return tender

    def _state_row(self, source, state, http_status, error, listings_found) -> Dict[str, Any]:
        org = source_org(source)
        now_iso = datetime.now(timezone.utc).isoformat()
        prev = state or {}
        ok = error is None
        return {
            "source_id": source["id"],
            "organization_id": org["organization_id"],
            "organization_name": org["name"],
            "sector": org["sector"],
            "is_target_bank": org["is_target_bank"],
            "url": source["url"],
            "last_checked": now_iso if error != "SKIPPED_TIME_BUDGET" else prev.get("last_checked"),
            "first_ok": (prev.get("first_ok") if prev.get("url") == source["url"] else None) or (now_iso if ok else None),
            "last_ok": now_iso if ok else prev.get("last_ok"),
            "ok": ok,
            "http_status": http_status,
            "error": error,
            "listings_found": listings_found,
            "consecutive_failures": 0 if ok else int(prev.get("consecutive_failures") or 0) + 1,
        }

    @staticmethod
    def _row(t: Dict[str, Any]) -> Dict[str, Any]:
        row = {k: v for k, v in t.items() if not k.startswith("_") and k != "title_is_weak"}
        for k in ("published_date", "deadline", "first_seen", "last_seen"):
            if isinstance(row.get(k), (date, datetime)):
                row[k] = row[k].isoformat()
        return row


def _to_date(value) -> Optional[date]:
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _to_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
