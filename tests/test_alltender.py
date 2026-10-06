from datetime import datetime, timedelta, timezone

from app.crawler.alltender import AlltenderItem, organization_name, parse_list_page, sector
from app.pipeline import Monitor


def card(tid, fields):
    rows = "".join(
        f'<div class="tender_infoo"><div class="row"><div class="col-md-4"><p class="tender_des_title">{k}</p></div>'
        f'<div class="col-md-8"><p class="tender_des">: {v}</p></div></div></div>' for k, v in fields.items())
    return (f'<div class="col-md-12"><div class="tender_info"><div class="row"><div class="tender_id">'
            f'<p><span class="tender_no">1.</span> Tender ID {tid}<span class="tender_types">(Local)</span></p>'
            f'</div></div><div class="tender_description">{rows}</div></div></div>')


PAGE = ('<html><body><p>Total (2)</p><input type="hidden" id="preference_id" value="31979">'
        + card("1647318", {"Name of Work": "RFP for Consultancy Services for the Appointment of an External Auditor",
                           "Procurement Nature": "Service,non-e-GP", "Ministry/Division": "NGO", "Department": "BRAC",
                           "Tender Caller": "Senior Manager, Procurement, BRAC, BRAC Center, 75 Mohakhali, Dhaka",
                           "Published in": "Web Source on Oct 05, 2026", "Closing date": "Oct 18, 2026"})
        + card("1645656", {"Name of Work": "Appointment of Audit Firm.", "Ministry/Division": "Ministry of Health & Family Welfare",
                           "Department": "Medical College/Hospital/Clinic/Institute",
                           "Published in": "Web Source on Sep 30, 2026", "Closing date": "Oct 10, 2026"})
        + "</body></html>")


def test_parse_list_page():
    items, total, pref = parse_list_page(PAGE)
    assert (total, pref) == (2, "31979")
    assert [i.tender_id for i in items] == ["1647318", "1645656"]
    assert items[0].fields["Department"] == "BRAC"
    assert items[0].fields["Closing date"] == "Oct 18, 2026"
    assert items[0].link == "https://www.alltender.com/user/tender_detail/1647318"


def item(dept, caller, ministry="International Organization"):
    return AlltenderItem("1", {"Department": dept, "Tender Caller": caller, "Ministry/Division": ministry})


def test_organization_from_department_or_caller():
    assert organization_name(item("BRAC", "Manager, BRAC, Dhaka", "NGO")) == "BRAC"
    assert organization_name(item("Others NGO", "Executive Director, Association for Land Reform and Development "
                                  "(ALRD), House # 6/6, Block-F, Lalmatia, Dhaka")) == \
        "Association for Land Reform and Development (ALRD)"
    assert organization_name(item("Other International Organization", "Sheikh Khalquzzaman, Lead- Humanitarian "
                                  "Response, HELVETAS, Gulshan-2, Dhaka")) == "HELVETAS"
    assert organization_name(item("Private Bank", "Imrul Hasan, AVP, General Services Division, "
                                  "Bangladesh Commerce Bank Limited, Dhaka", "Bank/Insurance/Finance Company")) == \
        "Bangladesh Commerce Bank Limited"


def test_sector_scope():
    assert sector(item("BRAC", "", "NGO")) == "NGO"
    assert sector(item("Other International Organization", "Authority, ActionAid Bangladesh, Dhaka")) == "NGO"
    assert sector(item("Rupali Bank Limited", "", "Bank/Insurance/Finance Company")) == "BANK"
    assert sector(item("Sadharan Bima Corporation", "", "Financial Institutions Division")) == "BANK"
    assert sector(item("Bangladesh Petroleum Corporation (BPC)", "", "Energy & Mineral Resources Division")) is None


def test_min_interval_hours():
    m = Monitor.__new__(Monitor)
    src = {"id": "s", "min_interval_hours": 6}
    recent = {"ok": True, "last_ok": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}
    old = {"ok": True, "last_ok": (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()}
    failed = {"ok": False, "last_ok": recent["last_ok"]}
    assert m._too_soon(src, recent)
    assert not m._too_soon(src, old)
    assert not m._too_soon(src, failed)          # retry after a failure
    assert not m._too_soon(src, None)
    assert not m._too_soon({"id": "x"}, recent)  # sources without the option run every time


class TwinStore:
    def __init__(self, rows):
        self.rows, self.deleted = rows, set()

    def open_tenders_for_orgs(self, org_ids):
        return [dict(r) for r in self.rows if r["organization_id"] in org_ids]

    def delete_tenders(self, ids):
        self.deleted |= set(ids)


def test_aggregator_copy_of_stored_official_notice_is_dropped_and_deleted():
    from app.parsers.date_cleaner import DHAKA_TZ
    deadline = datetime(2026, 10, 18, 23, 59, 59, tzinfo=DHAKA_TZ)
    store = TwinStore([
        {"id": "official", "organization_id": "ngo_01_brac", "source_id": "src_ngo_01_brac",
         "title": "Request for Proposal for Appointment of External Auditor RFP-2658", "deadline": "2026-10-18T17:59:59+00:00"},
        {"id": "agg_old", "organization_id": "ngo_02", "source_id": "src_agg_bdjobs",
         "title": "Selection of audit firm for annual audit", "deadline": "2026-10-20T17:59:59+00:00"},
    ])
    m = Monitor.__new__(Monitor)
    m.store = store
    agg = {"id": "agg_new", "organization_id": "ngo_01_brac", "_aggregator": True, "deadline": deadline,
           "title": "RFP for Consultancy Services for the Appointment of an External Auditor"}
    official = {"id": "o2", "organization_id": "ngo_02", "_aggregator": False,
                "deadline": datetime(2026, 10, 20, 23, 59, 59, tzinfo=DHAKA_TZ),
                "title": "Selection of Audit Firm for Annual Audit FY 2025-26"}
    kept = m._drop_stored_twins([agg, official])
    assert [t["id"] for t in kept] == ["o2"]
    assert store.deleted == {"agg_old"}
