"""
Vertical Slice Test Suite for Milestone 2.
Tests end-to-end processing pipeline: HTML/document extraction, date cleaning,
deterministic rules classification, scoring engine, deduplication, and alerting.
"""

from datetime import datetime, timezone
import pytest
from app.parsers.date_cleaner import parse_deadline, normalize_bangla_digits, calculate_days_remaining
from app.parsers.html_parser import HtmlNoticeExtractor, compute_content_hash
from app.parsers.document_parser import DocumentParser
from app.classification.rules import RulesClassifier
from app.scoring.engine import ScoringEngine
from app.alerts.telegram import TelegramAlerter
from app.ai.router import AIRouter, verify_evidence_in_text


def test_bangla_digits_and_date_parsing():
    """Verify Bangla digit normalization and DD/MM/YYYY parsing."""
    # 1. Bangla digits to ASCII
    bn_num = "১২৩৪৫৬৭৮৯০"
    assert normalize_bangla_digits(bn_num) == "1234567890"

    # 2. Standard DD/MM/YYYY
    dt, note = parse_deadline("Deadline: 25/11/2026 14:00")
    assert dt is not None
    assert dt.day == 25
    assert dt.month == 11
    assert dt.year == 2026

    # 3. Bangla digits in date (১৫/১০/২০২৬)
    dt_bn, note_bn = parse_deadline("দরপত্র দাখিলের শেষ তারিখ: ১৫/১০/২০২৬ বিকাল ৫:০০")
    assert dt_bn is not None
    assert dt_bn.day == 15
    assert dt_bn.month == 10
    assert dt_bn.year == 2026

    # 4. Bangla month name (২০ নভেম্বর ২০২৬)
    dt_m, _ = parse_deadline("শেষ সময় ২০ নভেম্বর ২০২৬")
    assert dt_m is not None
    assert dt_m.day == 20
    assert dt_m.month == 11
    assert dt_m.year == 2026


def test_html_tender_extractor():
    """Verify extraction of tender table rows and document links from sample HTML."""
    sample_html = """
    <html>
      <body>
        <h2>Tender Notices</h2>
        <table id="tenders">
          <tr>
            <th>Sl</th>
            <th>Tender Title / Description</th>
            <th>Ref Number</th>
            <th>Last Date</th>
            <th>Document</th>
          </tr>
          <tr>
            <td>1</td>
            <td>RFP for Selection of Consultant for IFRS 9 Implementation</td>
            <td>ABL/HO/CAD/2026/01</td>
            <td>30/11/2026</td>
            <td><a href="/downloads/tender_ifrs9.pdf">Download Tender Document</a></td>
          </tr>
          <tr>
            <td>2</td>
            <td>Procurement of Office Furniture and Chairs</td>
            <td>ABL/GA/2026/55</td>
            <td>15/10/2026</td>
            <td><a href="/downloads/furniture.pdf">Details</a></td>
          </tr>
        </table>
      </body>
    </html>
    """
    extractor = HtmlNoticeExtractor("https://www.agranibank.org/tender")
    candidates = extractor.extract_candidates(sample_html)

    assert len(candidates) >= 2
    cand1 = candidates[0]
    assert "IFRS 9 Implementation" in cand1["title"] or "IFRS 9 Implementation" in cand1["raw_text"]
    assert cand1["document_url"] == "https://www.agranibank.org/downloads/tender_ifrs9.pdf"


def test_deterministic_pipeline_routing():
    """Verify Section 4 deterministic pipeline routing rules."""
    classifier = RulesClassifier()

    # Case 1: Target Bank + IFRS 9 -> Pipeline A (IFRS9_TARGET)
    text1 = "Agrani Bank PLC invites RFP for Selection of Consultant for Expected Credit Loss (ECL) Model Implementation under IFRS 9. Submission deadline 30/11/2026."
    res1 = classifier.classify_candidate(text1, org_hint="Agrani Bank PLC")
    assert res1["pipeline"] == "IFRS9_TARGET"
    assert res1["record_type"] == "OPPORTUNITY"
    assert res1["category"] == "IFRS9_ECL"
    assert res1["outside_ifrs9_target"] is False

    # Case 2: Non-target NBFI + IFRS 9 -> Pipeline B (GENERAL_MARKET) with outside_ifrs9_target=True
    text2 = "IDLC Finance PLC invites RFP for IFRS 9 and ECL Gap Assessment. Last date of submission: 25/11/2026."
    res2 = classifier.classify_candidate(text2, org_hint="IDLC Finance")
    assert res2["pipeline"] == "GENERAL_MARKET"
    assert res2["category"] == "IFRS9_ECL"
    assert res2["outside_ifrs9_target"] is True

    # Case 3: Target Bank + Internal Audit -> Pipeline B (GENERAL_MARKET), category AUDIT_ASSURANCE
    text3 = "Sonali Bank PLC invites tenders for Statutory External Audit and Internal Audit Services for 2026. Bid submission deadline 10/11/2026."
    res3 = classifier.classify_candidate(text3, org_hint="Sonali Bank PLC")
    assert res3["pipeline"] == "GENERAL_MARKET"
    assert res3["category"] == "AUDIT_ASSURANCE"

    # Case 4: Irrelevant procurement (Construction / Renovation) -> Auto-rejected as IRRELEVANT
    text4 = "Civil works and building renovation of branch office. Supply of office furniture and painting."
    res4 = classifier.classify_candidate(text4, org_hint="Rupali Bank PLC")
    assert res4["record_type"] == "IRRELEVANT"
    assert res4["acnabin_relevant"] is False

    # Case 5: Acronym 'PD' meaning Project Director -> must NOT hit IFRS 9 false positive!
    text5 = "Office of the Project Director (PD). Invitation for Quotation for Local Consultant. Deadline 15/10/2026."
    res5 = classifier.classify_candidate(text5)
    assert res5["ifrs9_ecl_relevant"] is False
    assert res5["category"] != "IFRS9_ECL"


def test_deterministic_scoring_engine():
    """Verify deterministic scoring calculations and priority banding."""
    engine = ScoringEngine()

    # Test High-value IFRS 9 opportunity at target bank
    score, priority, breakdown, reasoning = engine.compute_score(
        category="IFRS9_ECL",           # base 60
        record_type="OPPORTUNITY",       # +15
        organization_type="BANK",        # +10
        is_target_bank=True,
        fit_type="DIRECT_FIT",           # +10
        source_tier=1,                   # +5
        confidence="HIGH",               # 0
        is_aqr_or_diagnostic=False
    )
    # Expected: 60 + 15 + 10 + 10 + 5 = 100
    assert score == 100
    assert priority == "VERY HIGH"
    assert breakdown["category_base"] == 60
    assert breakdown["is_opportunity"] == 15
    assert breakdown["source_tier_bonus"] == 5

    # Test general audit opportunity with Tier 1
    score2, priority2, _, _ = engine.compute_score(
        category="AUDIT_ASSURANCE",      # base 50
        record_type="OPPORTUNITY",       # +15
        organization_type="BANK",        # +10
        is_target_bank=False,
        fit_type="DIRECT_FIT",           # +10
        source_tier=1,                   # +5
        confidence="MEDIUM"              # -5
    )
    # Expected: 50 + 15 + 10 + 10 + 5 - 5 = 85 -> VERY HIGH
    assert score2 == 85
    assert priority2 == "VERY HIGH"

    # Test general audit opportunity with Tier 3 (no tier bonus)
    score3, priority3, _, _ = engine.compute_score(
        category="AUDIT_ASSURANCE",      # base 50
        record_type="OPPORTUNITY",       # +15
        organization_type="BANK",        # +10
        is_target_bank=False,
        fit_type="DIRECT_FIT",           # +10
        source_tier=3,                   # 0
        confidence="MEDIUM"              # -5
    )
    # Expected: 50 + 15 + 10 + 10 + 0 - 5 = 80 -> HIGH
    assert score3 == 80
    assert priority3 == "HIGH"


def test_evidence_verification():
    """Verify that hallucinated evidence quotes are dropped per Section 16.7."""
    source_text = "Agrani Bank PLC invites proposals for IFRS 9 Expected Credit Loss model validation by certified accounting firms."
    evidence_items = [
        {"page": 1, "text": "IFRS 9 Expected Credit Loss model validation"}, # Present in source
        {"page": 2, "text": "The firm must have 50 partners and turnover of 100 crore BDT"} # Hallucinated
    ]
    verified = verify_evidence_in_text(evidence_items, source_text)
    assert len(verified) == 1
    assert "Expected Credit Loss" in verified[0]["text"]


def test_telegram_alerter_formatting():
    """Verify alert message format conforms to Section 23 specification."""
    alerter = TelegramAlerter()
    sample_opp = {
        "id": "opp_agrani_test01",
        "organization_name": "Agrani Bank PLC",
        "pipeline": "IFRS9_TARGET",
        "outside_ifrs9_target": False,
        "title": "Selection of Consultant for IFRS 9 Implementation",
        "reference_number": "ABL/2026/01",
        "category": "IFRS9_ECL",
        "fit_type": "DIRECT_FIT",
        "priority": "VERY HIGH",
        "relevance_reason": "Core IFRS 9 advisory tender at target bank",
        "potential_acnabin_service": "IFRS 9 ECL Model Validation",
        "submission_deadline": "2026-11-30 17:00:00",
        "days_remaining": 57,
        "source_url": "https://www.agranibank.org/tender",
        "source_tier": 1,
        "ai_confidence": "HIGH",
        "evidence": [{"page": 1, "text": "Consultancy services for IFRS 9 implementation"}]
    }

    msg = alerter.format_opportunity_message(sample_opp, alert_type="NEW")
    assert "NEW ACNABIN OPPORTUNITY  [VERY HIGH]" in msg
    assert "Organization:* Agrani Bank PLC" in msg
    assert "Pipeline:* IFRS 9 TARGET" in msg
    assert "Category:* IFRS9_ECL" in msg
    assert "Dashboard:*" in msg


@pytest.mark.asyncio
async def test_ai_router_in_off_mode(monkeypatch):
    """Verify AI router functions properly in AI_MODE=off without any cloud API keys."""
    monkeypatch.setenv("AI_MODE", "off")
    router = AIRouter()
    candidate = {
        "title": "Tender for External Statutory Audit Services 2026",
        "source_url": "https://www.sonalibank.com.bd/tender.php",
        "organization_name": "Sonali Bank PLC",
        "reference_number": "SBL/AUD/2026/09"
    }
    full_text = "Sonali Bank PLC. Tender for External Statutory Audit Services 2026. Ref: SBL/AUD/2026/09. Last date: 20/11/2026."

    res = await router.process_candidate(candidate, full_text)
    assert res["category"] == "AUDIT_ASSURANCE"
    assert res["pipeline"] == "GENERAL_MARKET"
    assert res["record_type"] == "OPPORTUNITY"
    assert res["fit_type"] == "DIRECT_FIT"
