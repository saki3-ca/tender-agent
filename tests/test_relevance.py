import pytest

from app.classification.relevance import IFRS9_LABEL, RelevanceClassifier

rc = RelevanceClassifier()


# --- Examples from the requirements -------------------------------------------------
def test_example_A_office_furniture_is_not_priority():
    r = rc.classify("Supply of Office Furniture")
    assert not r.is_priority and not r.is_ifrs9


def test_example_B_internal_audit_review_is_priority_not_ifrs9():
    r = rc.classify("Consultancy for Internal Audit Review")
    assert r.is_priority and not r.is_ifrs9
    assert "Audit & Assurance" in r.categories


def test_example_C_ifrs9_ecl_model_validation():
    r = rc.classify("IFRS 9 ECL Model Validation Consultancy")
    assert r.is_priority and r.is_ifrs9
    assert r.categories[0] == IFRS9_LABEL


def test_example_D_ngo_external_audit_of_donor_project():
    r = rc.classify("External Audit of Donor-Funded Project")
    assert r.is_priority


def test_example_E_motor_vehicles_is_not_priority():
    assert not rc.classify("Supply of Motor Vehicles").is_priority


# --- IFRS 9 detection ---------------------------------------------------------------
@pytest.mark.parametrize("title", [
    "IFRS 9 implementation consultancy", "IFRS-9 gap assessment", "IFRS9 advisory services",
    "Expected Credit Loss model development", "ECL modelling support", "Review of ECL methodology",
    "Financial instrument impairment review", "Expected Credit Loss Model validation",
    "আইএফআরএস ৯ বাস্তবায়নে পরামর্শক নিয়োগ",
])
def test_ifrs9_variants(title):
    r = rc.classify(title)
    assert r.is_ifrs9 and r.is_priority


def test_ifrs9_found_in_description_not_title():
    r = rc.classify("Consultancy Services",
                    description="Review and validate the bank's Expected Credit Loss model under IFRS 9.")
    assert r.is_priority and r.is_ifrs9


def test_ifrs9_found_in_tender_document_text():
    r = rc.classify("Request for Proposal", document_text="Scope: development of an ECL model and staging criteria.")
    assert r.is_ifrs9


@pytest.mark.parametrize("title", [
    "Credit Officer Recruitment",
    "Loan Collection Services",
    "Procurement of Credit Card Embossing Machine",
    "Office of the Project Director (PD): quotation for vehicles",
    "Provisioning of network bandwidth",
])
def test_generic_credit_terms_are_not_ifrs9(title):
    assert not rc.classify(title).is_ifrs9


def test_ecl_needs_context():
    assert not rc.classify("ECL Bangladesh office rent").is_ifrs9
    assert rc.classify("Validation of ECL under IFRS framework").is_ifrs9


# --- Conservative but useful Priority ------------------------------------------------
@pytest.mark.parametrize("title", [
    "Consultancy for Office Interior Design",
    "Hiring of consultancy firm for architectural design",
    "Supply of IT Equipment",
    "Recruitment of Internal Auditor (Officer)",
    "Tender for Sale of Old Vehicles",
    "Energy audit of head office building",
    "Internal construction works for Internal Control & Compliance Division",
    "Supply of Oracle Database Audit Vault licences",
])
def test_not_priority(title):
    assert not rc.classify(title).is_priority


@pytest.mark.parametrize("title,category", [
    ("Consultancy for Internal Control Assessment", "Risk & Internal Control"),
    ("Selection of Chartered Accountant Firm for Audit of Accounts", "Audit & Assurance"),
    ("Appointment of Statutory Auditor for FY 2026", "Audit & Assurance"),
    ("Hiring of Tax Consultant for income tax return filing", "Tax & VAT"),
    ("VAT Advisory Services", "Tax & VAT"),
    ("Enterprise Risk Management framework consultancy", "Risk & Internal Control"),
    ("Financial due diligence of partner organizations", "Financial & Management Advisory"),
    ("Business process re-engineering consultancy", "Financial & Management Advisory"),
    ("Tender for Swift CSP Assessor", "IT / IS Audit"),
    ("Information Systems Audit of core banking", "IT / IS Audit"),
    ("Preparation of financial statements under IFRS", "Accounting & Financial Reporting"),
    ("আয়কর উপদেষ্টা ফার্ম নিয়োগের বিজ্ঞপ্তি", "Tax & VAT"),
])
def test_priority_categories(title, category):
    r = rc.classify(title)
    assert r.is_priority and category in r.categories


def test_document_boilerplate_does_not_make_goods_tender_priority():
    boiler = ("Bidders must submit audited financial statements for the last 3 years, "
              "VAT registration certificate, TIN, and tax return acknowledgement.")
    assert not rc.classify("Supply of Desktop Computers", document_text=boiler).is_priority


def test_specific_document_phrase_makes_generic_title_priority():
    r = rc.classify("Request for Proposal",
                    document_text="The Foundation invites proposals for the selection of an external audit firm.")
    assert r.is_priority and "Audit & Assurance" in r.categories
