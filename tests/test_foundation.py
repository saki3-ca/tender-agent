"""
Foundation Test Suite for Milestone 1.
Tests configuration loading, 30 target banks registry, category codes,
logging, Supabase client/mock, migrations, and workflow definitions.
"""

import json
import yaml
from pathlib import Path
import pytest
from app.utils.config import AppConfig, ConfigError, REQUIRED_CATEGORIES
from app.utils.logging import setup_logger
from app.db.supabase import InMemoryDatabaseAdapter, SupabaseDatabase

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
MIGRATIONS_DIR = ROOT_DIR / "supabase" / "migrations"
WORKFLOWS_DIR = ROOT_DIR / ".github" / "workflows"


def test_ifrs9_banks_count_and_structure():
    """Verify config/ifrs9_banks.json contains exactly 30 unique banks with required fields."""
    banks_file = CONFIG_DIR / "ifrs9_banks.json"
    assert banks_file.exists(), "config/ifrs9_banks.json does not exist"

    with open(banks_file, "r", encoding="utf-8") as f:
        banks = json.load(f)

    # Exactly 30 unique entries check
    assert len(banks) == 30, f"Expected exactly 30 banks, found {len(banks)}"
    ids = [b["id"] for b in banks]
    assert len(set(ids)) == 30, "Found duplicate bank id in ifrs9_banks.json"

    # Field validations
    for b in banks:
        assert "id" in b and b["id"].startswith("bank_")
        assert "canonical_name" in b and len(b["canonical_name"]) > 0
        assert "aliases" in b and isinstance(b["aliases"], list) and len(b["aliases"]) > 0
        assert "official_domain" in b and len(b["official_domain"]) > 0
        assert "last_verified" in b


def test_startup_validation_assertion():
    """Verify that AppConfig asserts exactly 30 unique banks and fails loudly if tampered."""
    app_config = AppConfig(CONFIG_DIR)
    assert len(app_config.ifrs9_banks) == 30

    # Test tampering triggers ConfigError
    app_config.ifrs9_banks = app_config.ifrs9_banks[:29]
    with pytest.raises(ConfigError) as exc_info:
        app_config.validate()
    assert "Expected exactly 30" in str(exc_info.value)


def test_category_codes_match_enum():
    """Verify category codes match Section 9 enum exactly."""
    categories_file = CONFIG_DIR / "categories.json"
    with open(categories_file, "r", encoding="utf-8") as f:
        categories = json.load(f)

    codes = {c["code"] for c in categories}
    assert codes == REQUIRED_CATEGORIES, f"Mismatch in category codes: {codes ^ REQUIRED_CATEGORIES}"

    for c in categories:
        assert "base_priority" in c
        assert "base_score" in c
        assert "description" in c and len(c["description"]) > 20
        assert "keywords_en" in c and len(c["keywords_en"]) > 0
        assert "keywords_bn" in c and len(c["keywords_bn"]) > 0


def test_scoring_weights_structure():
    """Verify scoring weights structure in config/scoring.yaml."""
    scoring_file = CONFIG_DIR / "scoring.yaml"
    with open(scoring_file, "r", encoding="utf-8") as f:
        scoring = yaml.safe_load(f)

    assert "category_base_scores" in scoring
    assert "modifiers" in scoring
    assert "bounds" in scoring
    assert "priority_bands" in scoring

    # Category base scores
    base_scores = scoring["category_base_scores"]
    for cat in REQUIRED_CATEGORIES:
        assert cat in base_scores

    # Modifiers
    mods = scoring["modifiers"]
    assert "is_opportunity_yes" in mods
    assert "is_financial_institution_or_regulator" in mods
    assert "fit_type" in mods
    assert "source_tier_1_or_2" in mods
    assert "confidence_penalty" in mods


def test_structured_json_logging(capsys):
    """Verify logger formats output as valid single-line JSON."""
    test_logger = setup_logger("test_foundation")
    test_logger.info("Test message", extra={"test_key": "test_value", "item_count": 42})

    captured = capsys.readouterr()
    lines = [line.strip() for line in captured.out.strip().split("\n") if line.strip()]
    assert len(lines) >= 1

    last_line = lines[-1]
    data = json.loads(last_line)
    assert data["message"] == "Test message"
    assert data["level"] == "INFO"
    assert data["test_key"] == "test_value"
    assert data["item_count"] == 42
    assert "timestamp" in data


def test_in_memory_database_adapter():
    """Verify in-memory database adapter operations."""
    adapter = InMemoryDatabaseAdapter()

    # 1. Organization upsert & get
    adapter.upsert_organization({"organization_id": "org_test", "canonical_name": "Test Bank"})
    orgs = adapter.get_organizations()
    assert len(orgs) == 1
    assert orgs[0]["canonical_name"] == "Test Bank"

    # 2. Source operations
    adapter.upsert_source({"id": "src_1", "url": "https://example.com/tenders", "enabled": True})
    sources = adapter.get_sources()
    assert len(sources) == 1

    # 3. Run recording
    run_id = adapter.record_run_start("monitor")
    assert run_id > 0
    adapter.record_run_end(run_id, "COMPLETED", {"sources_checked": 5, "new_candidates": 2})
    assert adapter.runs[run_id]["status"] == "COMPLETED"
    assert adapter.runs[run_id]["sources_checked"] == 5

    # 4. Opportunity and alert dedupe
    adapter.upsert_opportunity({"id": "opp_101", "title": "IFRS 9 Advisory", "priority": "HIGH"})
    assert adapter.get_opportunity("opp_101")["title"] == "IFRS 9 Advisory"

    assert not adapter.alert_exists("dedupe_opp_101_new")
    adapter.record_alert({"dedupe_key": "dedupe_opp_101_new", "channel": "telegram"})
    assert adapter.alert_exists("dedupe_opp_101_new")


def test_migrations_and_views_exist():
    """Verify SQL migration files exist and define required tables, views, and RLS."""
    mig1 = MIGRATIONS_DIR / "20261001000001_initial_schema.sql"
    mig2 = MIGRATIONS_DIR / "20261001000002_views_and_rls.sql"
    assert mig1.exists()
    assert mig2.exists()

    sql1 = mig1.read_text(encoding="utf-8")
    sql2 = mig2.read_text(encoding="utf-8")

    # Tables in migration 1
    for table in [
        "organizations", "sources", "source_checks", "documents",
        "opportunities", "opportunity_versions", "evidence", "alerts",
        "market_intelligence", "ai_reviews", "ai_usage", "manual_overrides",
        "notes", "runs", "app_users"
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql1

    # Views in migration 2
    for view in [
        "v_today_priority", "v_ifrs9_target", "v_general_market",
        "v_source_health", "v_run_summary", "v_kpis"
    ]:
        assert f"VIEW {view}" in sql2

    # RLS in migration 2
    assert "ENABLE ROW LEVEL SECURITY" in sql2
    assert "is_allowlisted_user" in sql2


def test_workflows_are_valid_yaml():
    """Verify all GitHub Actions workflows are syntactically valid YAML."""
    for wf in WORKFLOWS_DIR.glob("*.yml"):
        content = wf.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)
        assert "name" in parsed
        assert "jobs" in parsed or "on" in parsed
