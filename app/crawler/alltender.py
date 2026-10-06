"""
Alltender.com (paid subscription) — the "My Tenders" list of the ACNABIN account.

The list is filtered by the account's own preference profile on Alltender (e.g. "CA Firm"), so it
already holds the tenders Alltender matched to ACNABIN's services. The monitor signs in with
ALLTENDER_USER / ALLTENDER_PASSWORD, reads the list pages only (no detail pages, no documents)
and signs out. Tenders from this source are stored as members_only: the dashboard shows them to
signed-in users only (Alltender's terms do not allow republishing their content).
"""

import base64
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from app.crawler.crawler import USER_AGENT
from app.utils.config import config

BASE = "https://www.alltender.com"
PER_PAGE = 22          # largest page size Alltender offers
MAX_PAGES = 10


@dataclass
class AlltenderItem:
    tender_id: str
    fields: Dict[str, str] = field(default_factory=dict)

    @property
    def link(self) -> str:
        return f"{BASE}/user/tender_detail/{self.tender_id}"


def _value(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lstrip(":").strip()


def parse_list_page(html: str) -> Tuple[List[AlltenderItem], Optional[int], Optional[str]]:
    """Items on one "My Tenders" page, the total count ("Total (23)") and the preference id."""
    soup = BeautifulSoup(html, "lxml")
    items = []
    for block in soup.select("div.tender_info"):
        m = re.search(r"Tender ID\s*:?\s*(\d+)", block.get_text(" "))
        if not m:
            continue
        item = AlltenderItem(tender_id=m.group(1))
        for title in block.select("p.tender_des_title"):
            row = title.find_parent(class_="row")
            value = row.select_one("p.tender_des") if row else None
            if value:
                item.fields[_value(title.get_text())] = _value(value.get_text())
        if item.fields.get("Name of Work"):
            items.append(item)
    total = re.search(r"Total\s*\((\d+)\)", soup.get_text(" "))
    pref = soup.select_one("input#preference_id")
    return items, int(total.group(1)) if total else None, (pref.get("value") if pref else None)


async def fetch_my_tenders() -> Tuple[int, Optional[str], List[AlltenderItem]]:
    """(http status, error, items). Errors: LOGIN_NOT_CONFIGURED, LOGIN_FAILED, HTTP_xxx, TIMEOUT…"""
    user, password = config.alltender_user, config.alltender_password
    if not (user and password):
        return 0, "LOGIN_NOT_CONFIGURED", []
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
            await client.get(f"{BASE}/login")
            await client.post(f"{BASE}/user/check_user", data={
                "user_id": user, "password": password,
                "redirect_url": base64.b64encode(f"{BASE}/user/my_tenders".encode()).decode()})
            first = await client.get(f"{BASE}/user/my_tenders")
            if first.status_code >= 400:
                return first.status_code, f"HTTP_{first.status_code}", []
            if "/user/logout" not in first.text:
                return first.status_code, "LOGIN_FAILED", []
            items, total, pref = parse_list_page(first.text)
            if pref:
                items, page = [], 1
                while page <= MAX_PAGES:
                    res = await client.get(f"{BASE}/summary_tab/user_preferred_tender/{pref}/0/{PER_PAGE}/{page}")
                    if res.status_code >= 400:
                        return res.status_code, f"HTTP_{res.status_code}", []
                    page_items, _, _ = parse_list_page(res.text)
                    items += page_items
                    if not page_items or (total is not None and len(items) >= total):
                        break
                    page += 1
            await client.get(f"{BASE}/user/logout")
            seen, unique = set(), []
            for it in items:
                if it.tender_id not in seen:
                    seen.add(it.tender_id)
                    unique.append(it)
            return first.status_code, None, unique
    except httpx.TimeoutException:
        return 0, "TIMEOUT", []
    except httpx.HTTPError as e:
        return 0, f"CONNECTION_FAILED: {str(e)[:120]}", []


_GENERIC_DEPT = re.compile(r"^(?:others?|private|public)\b", re.I)
_ADDRESS = re.compile(r"\d|\b(?:house|road|block|floor|level|plot|sector|lane|avenue|holding|gulshan|banani|"
                      r"dhanmondi|mohakhali|lalmatia|shantinagar|mirpur|uttara|motijheel|baridhara|tejgaon)\b", re.I)


def organization_name(item: AlltenderItem) -> str:
    """The organization calling the tender. Alltender's "Department" names it, except for catch-all
    departments ("Others NGO", "Other International Organization", "Private Bank"), where it is read
    from "Tender Caller": "<person or designation>, …, <organization>, <address>, <city>"."""
    dept = item.fields.get("Department", "")
    if dept and not _GENERIC_DEPT.match(dept):
        return dept
    parts = [p.strip() for p in item.fields.get("Tender Caller", "").split(",") if p.strip()]
    parts = parts[1:]                                    # person's name or "Authority"
    if len(parts) > 1 and len(parts[-1].split()) == 1 and parts[-1].lower() != "bangladesh":
        parts = parts[:-1]                               # city
    for k, part in enumerate(parts):
        if _ADDRESS.search(part):
            parts = parts[:k]
            break
    if parts:
        if parts[-1].lower() == "bangladesh" and len(parts) > 1:
            return f"{parts[-2]}, {parts[-1]}"
        return parts[-1]
    return dept or item.fields.get("Ministry/Division", "")


def sector(item: AlltenderItem) -> Optional[str]:
    """BANK / NGO, or None for government and other tenders outside the monitor's scope."""
    ministry = item.fields.get("Ministry/Division", "")
    text = f"{ministry} {item.fields.get('Department', '')} {organization_name(item)}"
    if re.search(r"\bbank\b|financial institution|leasing|finance (?:plc|ltd|limited)|insurance", text, re.I):
        return "BANK"
    if re.search(r"\bNGO\b|international organi[sz]ation|development partner|UN agenc|united nations", ministry, re.I):
        return "NGO"
    return None
