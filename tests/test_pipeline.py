"""End-to-end pipeline tests with a stub crawler (no network)."""

import asyncio
from datetime import date, datetime

import pytest

from app.classification.dedupe import dedupe, tender_id
from app.crawler.crawler import FetchResult
from app.db.supabase import Store
from app.parsers.date_cleaner import DHAKA_TZ
from app.pipeline import Monitor, derive_title
from app.utils.config import config

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=DHAKA_TZ)

TARGET_BANK_PAGE = """<table>
<tr><th>SL</th><th>Title</th><th>Publish Date</th><th>Closing Date</th><th>File</th></tr>
<tr><td>1</td><td>Supply of Office Furniture</td><td>01/10/2026</td><td>20/10/2026</td><td><a href="/t/furniture.pdf">PDF</a></td></tr>
<tr><td>2</td><td>Consultancy for Internal Audit Review</td><td>01/10/2026</td><td>20/10/2026</td><td><a href="/t/ia.pdf">PDF</a></td></tr>
<tr><td>3</td><td>IFRS 9 ECL Model Validation Consultancy</td><td>01/10/2026</td><td>20/10/2026</td><td><a href="/t/ifrs9.pdf">PDF</a></td></tr>
<tr><td>4</td><td>Consultancy Services</td><td>02/10/2026</td><td>22/10/2026</td><td><a href="/t/cs.pdf">PDF</a></td></tr>
<tr><td>5</td><td>Annual Maintenance of Generators</td><td>01/09/2026</td><td>15/09/2026</td><td><a href="/t/old.pdf">PDF</a></td></tr>
<tr><td>6</td><td>Supply of Printers (Cancelled)</td><td>01/10/2026</td><td>20/10/2026</td><td><a href="/t/cxl.pdf">PDF</a></td></tr>
</table>"""

DOCS = {
    "cs.pdf": b"%PDF- placeholder",
}
DOC_TEXT = {
    "cs.pdf": "Scope of work: Review and validate the bank's Expected Credit Loss model under IFRS 9.",
}


class StubCrawler:
    def __init__(self, pages):
        self.pages = pages

    async def fetch_page(self, source):
        if source["url"] not in self.pages:
            return FetchResult(url=source["url"], status=404, error="HTTP_404")
        return FetchResult(url=source["url"], final_url=source["url"], status=200, text=self.pages[source["url"]])

    async def fetch(self, url, verify_ssl=True, binary=False):
        name = url.rsplit("/", 1)[-1]
        if name in DOCS:
            return FetchResult(url=url, final_url=url, status=200, content=DOCS[name], content_type="application/pdf")
        return FetchResult(url=url, status=404, error="HTTP_404")

    async def close(self):
        pass


@pytest.fixture
def monitor(monkeypatch):
    target = next(s for s in config.sources if s["organization_id"] == "bank_13_city")
    failing = next(s for s in config.sources if s["organization_id"] == "bank_01_agrani")
    m = Monitor(Store(), now=NOW)
    m.store.client = None
    m.alerter.enabled = False
    m.crawler = StubCrawler({target["url"]: TARGET_BANK_PAGE})
    monkeypatch.setattr("app.pipeline.extract_document_text",
                        lambda content, url, ct, max_chars=0: DOC_TEXT.get(url.rsplit("/", 1)[-1], ""))
    m._ids = [target["id"], failing["id"]]
    return m


def run(monitor):
    asyncio.run(monitor.run(monitor._ids))
    return {t["title"]: t for t in monitor.results}


def test_general_priority_and_ifrs9_flags(monitor):
    results = run(monitor)
    active = {title for title, t in results.items() if t["_active"]}
    priority = {title for title, t in results.items() if t["_active"] and t["is_priority"]}
    ifrs9 = {title for title, t in results.items() if t["_active"] and t["is_ifrs9"]}

    # General: every active tender, relevant or not
    assert active == {"Supply of Office Furniture", "Consultancy for Internal Audit Review",
                      "IFRS 9 ECL Model Validation Consultancy", "Consultancy Services"}
    # Priority: only ACNABIN-relevant ones (IFRS 9 found in the document of "Consultancy Services")
    assert priority == {"Consultancy for Internal Audit Review", "IFRS 9 ECL Model Validation Consultancy",
                        "Consultancy Services"}
    assert ifrs9 == {"IFRS 9 ECL Model Validation Consultancy", "Consultancy Services"}
    # Expired and cancelled notices are never active
    assert not results["Annual Maintenance of Generators"]["_active"]
    assert results["Supply of Printers (Cancelled)"]["status"] == "CANCELLED"


def test_tender_record_has_source_and_organization(monitor):
    results = run(monitor)
    t = results["Consultancy for Internal Audit Review"]
    assert t["organization_name"] == "City Bank PLC"
    assert t["sector"] == "BANK" and t["is_target_bank"] is True
    assert t["source_url"].startswith("http") and t["document_url"].endswith("/t/ia.pdf")
    assert t["published_date"] == date(2026, 10, 1)


def test_failed_source_is_reported_and_does_not_stop_the_run(monitor):
    run(monitor)
    states = {s["source_id"]: s for s in monitor.source_results}
    failing = [s for s in states.values() if not s["ok"]]
    assert len(failing) == 1 and failing[0]["error"] == "HTTP_404"
    assert monitor.stats["sources_ok"] == 1 and monitor.stats["sources_failed"] == 1
    assert monitor.stats["active_general"] == 4


def test_dedupe_same_notice_from_two_pages():
    dl = datetime(2026, 10, 20, 23, 59, tzinfo=DHAKA_TZ)
    a = {"id": tender_id("org1", "RFP for External Audit", dl, "https://x/a.pdf"), "organization_id": "org1",
         "title": "RFP for External Audit", "deadline": dl, "published_date": None}
    b = {"id": tender_id("org1", "RFP for external audit.", dl, "https://x/notice-copy.pdf"), "organization_id": "org1",
         "title": "RFP for external audit.", "deadline": dl, "published_date": date(2026, 10, 1)}
    c = {"id": tender_id("org2", "RFP for External Audit", dl, "https://y/a.pdf"), "organization_id": "org2",
         "title": "RFP for External Audit", "deadline": dl, "published_date": None}
    merged = dedupe([a, b, c])
    assert len(merged) == 2                       # same org + title + deadline merged; other org kept
    assert merged[0]["published_date"] == date(2026, 10, 1)


def test_dedupe_keeps_different_notices_with_same_generic_title():
    a = {"id": tender_id("org1", "Invitation for Tender", None, "https://x/1.pdf"), "organization_id": "org1",
         "title": "Invitation for Tender", "deadline": None, "title_is_weak": True}
    b = {"id": tender_id("org1", "Invitation for Tender", None, "https://x/2.pdf"), "organization_id": "org1",
         "title": "Invitation for Tender", "deadline": None, "title_is_weak": True}
    assert len(dedupe([a, b])) == 2


def test_derive_title_from_egp_notice():
    text = ("Tender/Proposal SBPLC/GMO/CUM/26-27/LTM/2276\n"
            "Package No. and 3 KVA Online UPS for ATM Booth at Sonali Bank PLC, Brahmanbaria\n"
            "Description : Corporate Branch, Brahmanbaria.\n"
            "Category : Office and computing machinery")
    assert derive_title(text) == "3 KVA Online UPS for ATM Booth at Sonali Bank PLC, Brahmanbaria Corporate Branch, Brahmanbaria"
    assert derive_title("Subject: Appointment of external auditor for FY 2025-26") == \
        "Appointment of external auditor for FY 2025-26"
    assert derive_title("random text without a subject") is None


def test_configuration_keeps_the_30_target_banks():
    assert len(config.ifrs9_banks) == 30
    bank_sources = {s["organization_id"] for s in config.sources}
    assert all(b["id"] in bank_sources for b in config.ifrs9_banks)


def test_garbled_pdf_text_is_not_used_as_description():
    from app.pipeline import is_readable
    assert not is_readable("t;.1;+ :i'::;i .il li ';',11 .l i, 'e&s€fu ffir|{rr& iL 50 1f!}&ti. !(ALBELE.CrJft")
    assert is_readable("Eco-Social Development Organization (ESDO) House-748, Road-08, Adabor, Dhaka-1207.")
    assert is_readable("আয়কর উপদেষ্টা ফার্ম নিয়োগের বিজ্ঞপ্তি এবং অন্যান্য তথ্য")


def test_admin_url_replaces_configured_source_and_adds_new_ones():
    from app.pipeline import merge_admin_sources, source_org
    base = [{"id": "src_13_city_tender", "url": "https://old.example/tender", "organization_id": "bank_13_city",
             "enabled": True}]
    rows = [
        {"source_id": "src_13_city_tender", "url": "https://www.citybankplc.com/procurement", "enabled": True},
        {"source_id": "src_admin_abc", "url": "https://ngo.example/tenders", "organization_name": "Example Foundation",
         "sector": "NGO", "verify_ssl": False},
        {"source_id": "src_admin_bank", "url": "https://dhakabank.com.bd/notice", "organization_id": "bank_16_dhaka",
         "organization_name": "Dhaka Bank PLC", "sector": "BANK"},
        {"source_id": "src_admin_bad", "url": "not a url", "organization_name": "X", "sector": "NGO"},
    ]
    merged = {s["id"]: s for s in merge_admin_sources(base, rows)}
    assert merged["src_13_city_tender"]["url"] == "https://www.citybankplc.com/procurement"
    assert source_org(merged["src_13_city_tender"])["is_target_bank"] is True
    new = merged["src_admin_abc"]
    assert source_org(new) == {"organization_id": "admin_example_foundation", "name": "Example Foundation",
                               "type": None, "sector": "NGO", "is_target_bank": False}
    assert new["verify_ssl"] is False
    assert source_org(merged["src_admin_bank"])["is_target_bank"] is True   # existing target bank keeps its flag
    assert "src_admin_bad" not in merged


def test_aggregator_copy_of_official_notice_is_dropped():
    dl = datetime(2026, 10, 12, 23, 59, tzinfo=DHAKA_TZ)
    official = {"id": "a", "organization_id": "ngo_09", "title": "Engagement of an agency to provide digital media "
                "buying, motion graphic content creation and campaign strategy", "deadline": dl, "published_date": None}
    copy = {"id": "b", "organization_id": "ngo_09", "title": "Request for Proposal (RFP) - Hiring Media Buying & "
            "Motion Graphic Content Creation Agency", "deadline": dl, "published_date": date(2026, 10, 4),
            "_aggregator": True}
    other = {"id": "c", "organization_id": "ngo_09", "title": "Hiring a Consultant for Dengue Risk Analysis",
             "deadline": dl, "_aggregator": True}
    result = dedupe([official, copy, other])
    assert [t["id"] for t in result] == ["a", "c"]
    assert result[0]["published_date"] == date(2026, 10, 4)


def test_bdjobs_organizations_are_matched_to_configured_ones():
    from app.pipeline import organization_for_name
    assert organization_for_name("Eco Social Development Organization (ESDO)")["organization_id"] == "ngo_07_eco_social_development"
    assert organization_for_name("Bangladesh Red Crescent Society (BDRCS)")["sector"] == "NGO"
    new = organization_for_name("Helen Keller Intl")
    assert new["organization_id"] == "ext_helen_keller_intl" and new["sector"] == "NGO"
    assert organization_for_name("People's Leasing and Financial Services Ltd (PLFS)")["sector"] == "BANK"
