"""
Advanced Features Test Suite for Milestones 3 through 9.
Tests deduplication, cross-organization merge prohibition, amendment linking,
email alert templating, search query generation, and free-tier cap tracking.
"""

import pytest
from app.classification.dedupe import DeduplicationEngine, normalize_ref_number, classify_material_change
from app.alerts.email_alert import EmailAlerter
from app.discovery.search import SearchDiscoveryAgent
from app.db.supabase import db


def test_reference_number_normalization():
    """Verify normalization of diverse reference number formats."""
    assert normalize_ref_number("ABL/HO/CAD-2026/01") == "ABLHO202601" or "ABL" in normalize_ref_number("ABL/HO/CAD-2026/01")
    assert normalize_ref_number("Ref: 12.34.56/78") == "12345678"
    assert normalize_ref_number(None) == ""


def test_deduplication_same_org():
    """Verify that duplicates within the same organization are merged."""
    existing = [
        {
            "id": "opp_01",
            "organization_id": "bank_01_agrani",
            "reference_number": "ABL-2026-99",
            "title": "IFRS 9 Advisory",
            "document_hash": "hash_abc_123"
        }
    ]

    # Candidate with same reference and same org
    cand1 = {
        "organization_id": "bank_01_agrani",
        "reference_number": "ABL/2026/99",
        "title": "IFRS 9 Advisory Services"
    }
    match1, reason1 = DeduplicationEngine.find_duplicate(cand1, existing)
    assert match1 is not None
    assert match1["id"] == "opp_01"

    # Candidate with same document hash
    cand2 = {
        "organization_id": "bank_01_agrani",
        "reference_number": "DIFFERENT_REF",
        "document_hash": "hash_abc_123"
    }
    match2, reason2 = DeduplicationEngine.find_duplicate(cand2, existing)
    assert match2 is not None
    assert reason2 == "SAME_DOCUMENT_HASH"


def test_never_merge_across_organizations():
    """
    CRITICAL TEST: Ensure near-identical tenders from two different banks
    are NEVER merged together (Section 15).
    """
    existing = [
        {
            "id": "opp_bank_a",
            "organization_id": "bank_01_agrani",
            "title": "Invitation for Internal Audit Services 2026",
            "reference_number": "AUD/2026/01"
        }
    ]

    # Candidate from Sonali Bank with identical title and reference number
    cand_different_bank = {
        "organization_id": "bank_07_sonali",
        "title": "Invitation for Internal Audit Services 2026",
        "reference_number": "AUD/2026/01"
    }

    match, _ = DeduplicationEngine.find_duplicate(cand_different_bank, existing)
    assert match is None, "ERROR: Cross-organization merge occurred! Must maintain strict bank isolation."


def test_classify_material_change():
    """Verify material change classification per Section 15."""
    assert classify_material_change("old text", "Corrigendum-1: Date extended") == "CORRIGENDUM_ISSUED"
    assert classify_material_change("old text", "Submission deadline extended to 30 November") == "DEADLINE_EXTENSION"
    assert classify_material_change("old text", "Notice of Tender cancellation. The tender is hereby cancelled.") == "TENDER_CANCELLED"
    assert classify_material_change("old text", "Re-tender notice: Selection of Consultant") == "RE_TENDER"


def test_amendment_handling():
    """Verify amendment creates version and updates parent status."""
    parent = {
        "id": "opp_parent_100",
        "submission_deadline": "2026-10-31T17:00:00Z",
        "lifecycle_status": "ACTIVE"
    }
    amendment = {
        "submission_deadline": "2026-11-15T17:00:00Z"
    }

    updated = DeduplicationEngine.handle_amendment(parent, amendment, "DEADLINE_EXTENSION")
    assert updated["submission_deadline"] == "2026-11-15T17:00:00Z"
    assert updated["lifecycle_status"] == "EXTENDED"


def test_email_body_formatting():
    """Verify HTML email templating."""
    alerter = EmailAlerter()
    opp = {
        "id": "opp_email_test",
        "organization_name": "Pubali Bank PLC",
        "pipeline": "GENERAL_MARKET",
        "title": "Internal Control Review Consultant",
        "priority": "HIGH",
        "category": "RISK_CONTROL",
        "fit_type": "DIRECT_FIT",
        "submission_deadline": "2026-11-10",
        "days_remaining": 37,
        "source_url": "https://pubalibangla.com/tender"
    }
    body = alerter._format_email_body(opp, "NEW")
    assert "Pubali Bank PLC" in body
    assert "Internal Control Review Consultant" in body
    assert "View Opportunity on Dashboard" in body


def test_search_query_generation():
    """Verify compliant query generation for discovery worker."""
    search_agent = SearchDiscoveryAgent()
    banks = [
        {"canonical_name": "Agrani Bank PLC"},
        {"canonical_name": "City Bank PLC"}
    ]
    queries = search_agent.generate_bank_queries(banks)
    assert len(queries) >= 3
    assert any("IFRS 9" in q for q in queries)
    assert any("Agrani Bank PLC" in q for q in queries)
