"""
Fixture Verification Test Suite.
Validates synthetic fixtures against the classification pipeline.
Ensures synthetic fixtures are never mixed into production.
"""

import json
from pathlib import Path
from app.classification.rules import RulesClassifier

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "fixtures.json"


def test_synthetic_fixtures_classification():
    """Verify all synthetic fixtures classify exactly per expected values."""
    assert FIXTURES_PATH.exists()
    with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    classifier = RulesClassifier()

    for item in data.get("fixtures", []):
        assert item.get("is_synthetic_fixture") is True
        text = item["text"]
        org_hint = item.get("organization")

        res = classifier.classify_candidate(text, org_hint=org_hint)

        if "expected_record_type" in item:
            assert res["record_type"] == item["expected_record_type"], f"Failed for {item['id']}: expected {item['expected_record_type']}, got {res['record_type']}"

        if "expected_pipeline" in item:
            assert res["pipeline"] == item["expected_pipeline"], f"Failed pipeline for {item['id']}"

        if "expected_category" in item:
            assert res["category"] == item["expected_category"], f"Failed category for {item['id']}"

        if "expected_outside_target" in item:
            assert res["outside_ifrs9_target"] == item["expected_outside_target"]

        if "expected_ifrs9_relevant" in item:
            assert res["ifrs9_ecl_relevant"] == item["expected_ifrs9_relevant"]
