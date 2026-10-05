"""
Extracts tender listings from an organization's tender / procurement page.

Two strategies, in order:
  1. Tender tables: columns are identified from the header row (title, publish date,
     closing date, reference, document link). Tables that are not tender listings
     (exchange rates, calculators, layout tables without links) are ignored.
  2. Link listings: anchors in the main content whose text or URL indicates a tender
     notice (tender, RFQ, RFP, EOI, quotation, procurement, consultancy, ToR, দরপত্র...).

Navigation, header, footer, menus and sidebars are removed before extraction so that
links such as "Download Brand Kit" or "Forgot Password?" are never treated as tenders.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, urldefrag

from bs4 import BeautifulSoup, Tag

from app.parsers.date_cleaner import (
    DateInfo, deadline_datetime, extract_dates, parse_first_date, today_dhaka,
)

DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".jpg", ".jpeg", ".png")

TENDER_WORDS = re.compile(
    r"tender|e-?tender|\brfq\b|\brfp\b|\brfi\b|\beoi\b|\breoi\b|quotation|procurement|\bbid(?:s|ding)?\b|"
    r"consultan(?:cy|t)|proposal|expression of interest|terms of reference|\btor\b|"
    r"invitation (?:for|to)|enlistment|supply of|purchase of|"
    r"দরপত্র|কোটেশন|আগ্রহপত্র|দরপ্রস্তাব|ক্রয়",
    re.I)

GENERIC_LINK_TEXT = re.compile(
    r"^(?:download(?: now| notice| file| tender| document)?|details?|view(?: details| notice)?|read more|more|"
    r"click here|here|pdf|download \[?pdf\]?|continue reading|see more|apply|open|link|\W*)$", re.I)

# Section labels inside a listing card that are not titles
LABEL_HEADINGS = re.compile(r"^(?:tender details|details|methods? of application|how to apply|documents?|attachments?)\W*$", re.I)

GENERIC_TITLES = re.compile(
    r"^(?:invitation for (?:re-?)?tenders?|tender (?:notice|invitation)|tender|notice|"
    r"request for quotations?|rfq|request for proposals?|rfp|\(?rfp\)?|invitation for quotations?|e-?tender notice|"
    r"tender schedule|corrigendum|addendum|re-?tender notice|download(?: notice| tender| file)?|"
    r"tender documents?|notice board|view notice|(?:request for proposal|rfp) \(rfp\))\.?$", re.I)


def clean_title(title: str) -> str:
    """Removes field labels and page furniture from a listing title."""
    t = _clean(title)
    t = re.sub(r"^(?:(?:description|title|subject|name|details?)\s*:\s*)+", "", t, flags=re.I)
    t = re.sub(r"\s+\d+\s+\d[\d,]*\s+downloads?$", "", t, flags=re.I)   # WordPress download counters
    # trailing "Tender Closing: 30-9-2026" / "Pre-Bid: ..." fields copied into the title cell
    t = re.sub(r"\s+(?:pre[\s-]?bid(?: meeting)?|deadline|last date|(?:tender )?closing(?: date)?)\s*:.*$", "", t, flags=re.I)
    return t.strip(" |:-–")

NOISE_SELECTOR = re.compile(r"(?:^|[-_\s])(footer|navbar|nav|menu|breadcrumbs?|sidebar|cookie|topbar|social)(?:$|[-_\s])", re.I)

HEADER_ROLES = [
    ("deadline", re.compile(r"closing|deadline|last\s*date|end\s*date|due|submission|শেষ", re.I)),
    ("published", re.compile(r"publish|publication|posted|issue|start\s*date|প্রকাশ", re.I)),
    ("reference", re.compile(r"\bref|memo|tender\s*(?:no|id|number)|notice\s*no|স্মারক", re.I)),
    ("title", re.compile(r"title|subject|description|name|details|particular|notice|tender|work|বিষয়|বিবরণ|নাম", re.I)),
    ("date", re.compile(r"\bdate\b|তারিখ", re.I)),
    ("serial", re.compile(r"^\s*(?:sl|s\.?\s*no|serial|#|no\.?|ক্রমিক)\s*\.?\s*$", re.I)),
]

NON_TENDER_TABLE = re.compile(r"currency|exchange|buying|selling rate|interest rate|profit|deposit|installment|emi", re.I)


@dataclass
class Listing:
    title: str
    row_text: str                       # full text of the listing row/block (used for dates & status)
    source_url: str
    link: Optional[str] = None          # detail page or document
    document_url: Optional[str] = None  # PDF/DOC attached to the listing
    reference: Optional[str] = None
    published: Optional[date] = None
    deadline: Optional[datetime] = None
    deadline_has_time: bool = False
    title_is_weak: bool = False         # generic title or bare memo number
    extra: Dict[str, str] = field(default_factory=dict)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def is_document_url(url: Optional[str]) -> bool:
    if not url:
        return False
    path = urlparse(url).path.lower()
    return path.endswith(DOC_EXTENSIONS) or "/download" in path


def is_weak_title(title: str) -> bool:
    t = _clean(title)
    if not t or GENERIC_TITLES.match(t):
        return True
    letters = sum(c.isalpha() for c in t)
    # Memo numbers like "SBPLC/EED/ED/Godown/2026/140", "HO/ITD (IT P&M)/purchase/1256", "SBPLC.PO-Mirpur.IT.LTM.03"
    if t.count("/") >= 2 and len(t.split()) <= 4:
        return True
    if len(t.split()) <= 2 and re.search(r"[./_-]", t) and re.search(r"\d", t):
        return True
    return letters < 6


def _is_noise_element(el: Tag) -> bool:
    if el.name in ("html", "body", "main", "article", "table", "tbody", "tr", "td"):
        return False
    if el.get("role") == "navigation":
        return True
    names = list(el.get("class") or [])
    if isinstance(el.get("id"), str):
        names.append(el["id"])
    # Modifier classes such as "has-sidebar" describe a content wrapper, not a sidebar
    names = [n for n in names if not re.match(r"(?:has|no|with|is)[-_]", n, re.I)]
    if not any(NOISE_SELECTOR.search(n) for n in names):
        return False
    return el.find("table") is None


def strip_noise(soup: BeautifulSoup) -> BeautifulSoup:
    for el in soup(["script", "style", "noscript", "iframe", "svg"]):
        el.decompose()
    total = len(soup.get_text(" ", strip=True)) or 1
    for el in soup(["nav", "footer", "header", "aside", "form"]):
        if el.decomposed:
            continue
        # Malformed pages sometimes leave <header> unclosed so it wraps the whole page:
        # keep any such element that holds a table or most of the page text.
        if el.find("table") is not None or len(el.get_text(" ", strip=True)) > 0.4 * total:
            continue
        el.decompose()
    for el in [e for e in soup.find_all(True) if _is_noise_element(e)]:
        if not el.decomposed:
            el.decompose()
    return soup


def clean_html_text(html_content: str, max_chars: int = 20000) -> str:
    """Readable main text of a page (used for tender detail pages)."""
    soup = strip_noise(BeautifulSoup(html_content, "lxml"))
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n", strip=True)
    return text[:max_chars]


def page_document_links(html_content: str, base_url: str) -> List[str]:
    """Document links in the main content of a page (for tender detail pages)."""
    soup = strip_noise(BeautifulSoup(html_content, "lxml"))
    out: List[str] = []
    for a in soup.find_all("a", href=True):
        url = _abs(base_url, a["href"])
        if url and is_document_url(url) and url not in out:
            out.append(url)
    return out


def _abs(base_url: str, href: str) -> Optional[str]:
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    url = urldefrag(urljoin(base_url, href))[0]
    return url.replace("/./", "/") if url.startswith("http") else None


class HtmlNoticeExtractor:
    """Extracts tender listings from a source page."""

    def __init__(self, base_url: str, today: Optional[date] = None):
        self.base_url = base_url
        self.today = today or today_dhaka()

    def extract(self, html_content: str) -> List[Listing]:
        soup = strip_noise(BeautifulSoup(html_content, "lxml"))
        listings = self._from_tables(soup)
        if not listings:
            listings = self._from_links(soup)
        for item in listings:
            item.title = clean_title(item.title)
            item.title_is_weak = is_weak_title(item.title)
        listings = [l for l in listings if len(l.title) >= 5]
        # De-duplicate within the page (same document/link, or same title+deadline).
        # When a link appears twice ("Tender Notice" button + full title), keep the descriptive title.
        by_key: Dict[object, Listing] = {}
        for item in listings:
            key = item.document_url or item.link or (item.title.lower(), item.deadline)
            current = by_key.get(key)
            if current is None:
                by_key[key] = item
            elif current.title_is_weak and not item.title_is_weak:
                item.published = item.published or current.published
                item.deadline = item.deadline or current.deadline
                by_key[key] = item
        return list(by_key.values())

    # ------------------------------------------------------------------ tables
    def _map_header(self, cells: List[str]) -> Dict[int, str]:
        roles: Dict[int, str] = {}
        for idx, text in enumerate(cells):
            for role, pattern in HEADER_ROLES:
                if pattern.search(text):
                    roles[idx] = role
                    break
        # A plain "Date" column is the publication date unless a published column exists
        if "published" not in roles.values():
            for idx, role in roles.items():
                if role == "date":
                    roles[idx] = "published"
                    break
        return roles

    def _header_roles(self, tr: Tag) -> Optional[Dict[int, str]]:
        """Column roles if this row is a header row, else None."""
        cells = tr.find_all(["th", "td"])
        texts = [_clean(c.get_text(" ")) for c in cells]
        if len(texts) < 2:
            return None
        looks_like_header = bool(tr.find("th")) or (
            all(len(t) <= 40 for t in texts)
            and not any(parse_first_date(t, self.today) for t in texts)
            and not tr.find("a", href=True)
        )
        if not looks_like_header:
            return None
        roles = self._map_header(texts)
        return roles if "title" in roles.values() else None

    @staticmethod
    def _is_key_value_table(rows: List[Tag]) -> bool:
        """Detail tables such as 'Tender ID: … / Closing date: …' (one tender per table)."""
        if len(rows) < 2:
            return False
        labelled = 0
        for tr in rows:
            cells = tr.find_all(["th", "td"])
            if len(cells) != 2:
                return False
            if _clean(cells[0].get_text(" ")).endswith(":"):
                labelled += 1
        return labelled >= len(rows) / 2

    def _from_key_value_table(self, table: Tag) -> Optional[Listing]:
        node, title = table, ""
        for _ in range(5):
            node = node.parent
            if node is None or node.name in ("body", "html"):
                return None
            heading = node.find(["h1", "h2", "h3", "h4", "h5", "h6"]) or node.find(class_=re.compile(r"card-header|title", re.I))
            if heading and table not in heading.parents:
                title = _clean(heading.get_text(" "))
                break
        if len(title) < 8:
            return None
        block_text = _clean(node.get_text(" "))
        item = Listing(title=title, row_text=block_text[:1500], source_url=self.base_url)
        for row in table.find_all("tr"):
            label, value = [_clean(c.get_text(" ")) for c in row.find_all(["th", "td"])]
            if re.match(r"(?:tender|ref(?:erence)?|memo)\s*(?:id|no\.?|number)", label, re.I) and value:
                item.reference = value
        links = [u for u in (_abs(self.base_url, a["href"]) for a in node.find_all("a", href=True)) if u]
        item.document_url = next((u for u in links if is_document_url(u)), None)
        item.link = next((u for u in links if not is_document_url(u) and u.rstrip("/") != self.base_url.rstrip("/")), None)
        self._fill_from_text(item, block_text, allow_unlabelled=False)
        item.title_is_weak = is_weak_title(item.title)
        return item

    def _from_tables(self, soup: BeautifulSoup) -> List[Listing]:
        out: List[Listing] = []
        carried_roles: Optional[Dict[int, str]] = None  # header given in a separate one-row table
        carried_width = 0
        for table in soup.find_all("table"):
            if table.find("table"):
                continue  # layout table wrapping other tables
            rows = table.find_all("tr")
            if not rows:
                continue
            first_texts = [_clean(c.get_text(" ")) for c in rows[0].find_all(["th", "td"])]
            if NON_TENDER_TABLE.search(" ".join(first_texts)):
                continue
            if self._is_key_value_table(rows):
                item = self._from_key_value_table(table)
                if item:
                    out.append(item)
                continue
            roles = self._header_roles(rows[0])
            if roles and len(rows) == 1:
                carried_roles, carried_width = roles, len(first_texts)
                continue
            body = rows[1:]
            if roles is None:
                body = rows
                if carried_roles and len(first_texts) == carried_width:
                    roles = carried_roles
            for tr in body:
                item = self._row_to_listing(tr, roles or {})
                if item:
                    out.append(item)
        return out

    def _row_to_listing(self, tr: Tag, roles: Dict[int, str]) -> Optional[Listing]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            return None
        texts = [_clean(c.get_text(" ")) for c in cells]
        row_text = " | ".join(t for t in texts if t)
        links = [u for u in (_abs(self.base_url, a["href"]) for a in tr.find_all("a", href=True)) if u]
        if len(row_text) < 8:
            return None

        if roles:
            title_cells = [texts[i] for i, r in roles.items() if r == "title" and i < len(texts)]
            title = max(title_cells, key=len) if title_cells else ""
            ref_cells = [texts[i] for i, r in roles.items() if r == "reference" and i < len(texts)]
        else:
            if not links:
                return None  # headerless tables without links are layout/data tables
            candidates = [t for t in texts if t and not GENERIC_LINK_TEXT.match(t)
                          and not (len(t) < 40 and parse_first_date(t, self.today))]
            title = max(candidates, key=len) if candidates else ""
            ref_cells = []
        if not title or sum(c.isalpha() for c in title) < 5:
            return None
        if not roles and not (TENDER_WORDS.search(row_text) or any(is_document_url(u) for u in links)):
            return None

        item = Listing(title=title, row_text=row_text, source_url=self.base_url)
        item.reference = ref_cells[0] if ref_cells and ref_cells[0] != title else None
        item.document_url = next((u for u in links if is_document_url(u)), None)
        item.link = next((u for u in links if not is_document_url(u) and u.rstrip("/") != self.base_url.rstrip("/")), None)

        # Dates: header-mapped columns first, then labelled text in the row
        for idx, role in roles.items():
            if idx >= len(texts) or role not in ("published", "deadline"):
                continue
            found = parse_first_date(texts[idx], self.today)
            if not found:
                continue
            if role == "published" and found.value <= self.today:
                item.published = found.value
            elif role == "deadline":
                item.deadline, item.deadline_has_time = deadline_datetime(found.value, found.time)
        self._fill_from_text(item, row_text, allow_unlabelled=not roles)
        item.title_is_weak = is_weak_title(item.title)
        return item

    # ------------------------------------------------------------------- links
    def _from_links(self, soup: BeautifulSoup) -> List[Listing]:
        out: List[Listing] = []
        base = self.base_url.rstrip("/")
        for a in soup.find_all("a", href=True):
            url = _abs(self.base_url, a["href"])
            if not url or url.rstrip("/") == base:
                continue
            text = _clean(a.get_text(" "))
            container = self._container(a)
            container_text = _clean(container.get_text(" ")) if container is not None else text
            if not text or GENERIC_LINK_TEXT.match(text):
                text = self._nearby_title(a, container)
            text = re.sub(r"^(?:continue reading|read more)\s*:?\s*", "", text, flags=re.I)
            if len(text) < 12 or sum(c.isalpha() for c in text) < 8:
                continue
            path = urlparse(url).path
            # Short labels pointing at top-level pages are menu items ("Tender/Notice", "Terms of Reference/ToR")
            if len(text) < 25 and not is_document_url(url) and len([p for p in path.split("/") if p]) <= 1:
                continue
            if not (TENDER_WORDS.search(text) or TENDER_WORDS.search(path.replace("-", " ").replace("_", " "))):
                continue
            # Skip links that only point at other listing pages / categories
            if re.search(r"/(?:category|tag|page|author)/", path) and not is_document_url(url):
                continue
            item = Listing(title=text, row_text=container_text[:1500], source_url=self.base_url)
            if is_document_url(url):
                item.document_url = url
            else:
                item.link = url
            self._fill_from_text(item, item.row_text, allow_unlabelled=True)
            item.title_is_weak = is_weak_title(item.title)
            out.append(item)
        return out

    @staticmethod
    def _nearby_title(a: Tag, container: Optional[Tag]) -> str:
        """Title for a generic link ("Download Notice"): a heading in its card, or the heading
        just before the card (e.g. an accordion header)."""
        def usable(el) -> str:
            t = _clean(el.get_text(" ")) if el is not None else ""
            return t if 12 <= len(t) <= 300 and not LABEL_HEADINGS.match(t) and not GENERIC_LINK_TEXT.match(t) else ""
        if container is not None:
            for h in container.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong"]):
                if usable(h):
                    return usable(h)
        node = a
        for _ in range(6):
            node = node.parent
            if node is None or node.name in ("body", "html", "main"):
                break
            sib = node.find_previous_sibling(True)
            # a header is a short line, not a block of "Label: value" fields
            if sib is not None and sib.find("table") is None and usable(sib) and usable(sib).count(":") <= 1 \
                    and len(usable(sib)) <= 200:
                return usable(sib)
        return ""

    @staticmethod
    def _container(a: Tag) -> Optional[Tag]:
        """Smallest enclosing block (list item, article, card) that holds this listing."""
        node = a
        for _ in range(5):
            node = node.parent
            if node is None or node.name in ("body", "html", "main"):
                return None
            if node.name in ("li", "article", "tr"):
                return node
            if node.name == "div" and len(node.get_text(" ", strip=True)) > 40:
                return node if len(node.get_text(" ", strip=True)) < 800 else None
        return None

    # ------------------------------------------------------------------- dates
    def _fill_from_text(self, item: Listing, text: str, allow_unlabelled: bool) -> None:
        info: DateInfo = extract_dates(text, self.today)
        if item.deadline is None and info.deadline:
            item.deadline, item.deadline_has_time = info.deadline, info.deadline_has_time
        if item.published is None and info.published:
            item.published = info.published
        # In a listing, a lone unlabelled past date is the posting date (never a guess about deadlines)
        if allow_unlabelled and item.published is None and item.deadline is None and len(info.unlabelled) == 1:
            d = info.unlabelled[0]
            if d <= self.today:
                item.published = d
