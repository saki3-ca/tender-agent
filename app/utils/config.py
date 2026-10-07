"""
Configuration loader for the ACNABIN Tender Monitor.

Loads:
  - settings.yaml       runtime settings
  - ifrs9_banks.json    the fixed list of 30 IFRS 9 target banks
  - organizations.json  bank / NGO registry (names, types, sectors)
  - sources.json        tender pages to crawl
  - relevance.json      ACNABIN relevance rules (Priority / IFRS 9 / closed status)
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"

# organizations.json `sector` -> dashboard section
SECTOR_MAP = {
    "banking": "BANK",
    "nbfis": "BANK",
    "regulators": "BANK",
    "ngos": "NGO",
    "ingos": "NGO",
    "public_donor": "NGO",
    "development_partners": "NGO",
    "it": "IT",
    "ict": "IT",
    "software": "IT",
    "technology": "IT",
    "telecom": "IT",
}


class ConfigError(Exception):
    """Raised when configuration validation fails."""


class AppConfig:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or CONFIG_DIR
        self.settings: Dict[str, Any] = self._load_yaml("settings.yaml")
        self.ifrs9_banks: List[Dict[str, Any]] = self._load_json("ifrs9_banks.json")
        self.organizations: List[Dict[str, Any]] = self._load_json("organizations.json")
        self.sources: List[Dict[str, Any]] = self._load_json("sources.json")
        self.relevance: Dict[str, Any] = self._load_json("relevance.json")
        self._org_index = self._build_org_index()
        self.validate()

    def _load_yaml(self, filename: str) -> Dict[str, Any]:
        path = self.config_dir / filename
        if not path.exists():
            raise ConfigError(f"Missing configuration file: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_json(self, filename: str) -> Any:
        path = self.config_dir / filename
        if not path.exists():
            raise ConfigError(f"Missing configuration file: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _build_org_index(self) -> Dict[str, Dict[str, Any]]:
        """One record per organization_id with name, type, sector and target-bank flag."""
        index: Dict[str, Dict[str, Any]] = {}
        target_ids = {b["id"] for b in self.ifrs9_banks}
        for bank in self.ifrs9_banks:
            index[bank["id"]] = {
                "organization_id": bank["id"],
                "name": bank["canonical_name"],
                "type": "BANK",
                "sector": "BANK",
                "is_target_bank": True,
            }
        for org in self.organizations:
            oid = org["organization_id"]
            entry = index.get(oid, {})
            index[oid] = {
                "organization_id": oid,
                "name": entry.get("name") or org["canonical_name"],
                "type": org.get("organization_type") or entry.get("type"),
                "sector": SECTOR_MAP.get(org.get("sector", ""), entry.get("sector")),
                "is_target_bank": oid in target_ids,
            }
        return index

    def organization(self, organization_id: str) -> Optional[Dict[str, Any]]:
        return self._org_index.get(organization_id)

    def validate(self) -> None:
        if len(self.ifrs9_banks) != 30:
            raise ConfigError(f"Expected exactly 30 IFRS 9 target banks, found {len(self.ifrs9_banks)}.")
        if len({b["id"] for b in self.ifrs9_banks}) != 30:
            raise ConfigError("Duplicate bank id in config/ifrs9_banks.json")

        for key in ("ifrs9", "categories", "closed_status"):
            if key not in self.relevance:
                raise ConfigError(f"config/relevance.json is missing '{key}'")

        source_ids = [s["id"] for s in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ConfigError("Duplicate source id in config/sources.json")
        for s in self.sources:
            org = self.organization(s["organization_id"])
            if not org:
                raise ConfigError(f"Source {s['id']} references unknown organization {s['organization_id']}")
            if org["sector"] not in ("BANK", "NGO", "IT"):
                raise ConfigError(f"Organization {s['organization_id']} has no BANK/NGO/IT sector")

    # ---- settings helpers -------------------------------------------------
    def crawler_setting(self, key: str, default: Any) -> Any:
        return self.settings.get("crawler", {}).get(key, default)

    @property
    def recent_publication_days(self) -> int:
        return int(self.settings.get("active", {}).get("recent_publication_days", 7))

    @property
    def run_time_budget_minutes(self) -> float:
        val = os.getenv("RUN_TIME_BUDGET_MINUTES")
        if val:
            try:
                return float(val)
            except ValueError:
                pass
        return float(self.settings.get("run_time_budget_minutes", 14))

    # ---- secrets (environment) -------------------------------------------
    @property
    def supabase_url(self) -> str:
        return os.getenv("SUPABASE_URL", "")

    @property
    def supabase_service_role_key(self) -> str:
        return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    @property
    def telegram_bot_token(self) -> str:
        return os.getenv("TELEGRAM_BOT_TOKEN", "")

    @property
    def telegram_chat_id(self) -> str:
        return os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def smtp_host(self) -> str:
        return os.getenv("SMTP_HOST", "") or "smtp.gmail.com"

    @property
    def smtp_port(self) -> int:
        return int(os.getenv("SMTP_PORT", "") or 587)

    @property
    def smtp_user(self) -> str:
        return os.getenv("SMTP_USER", "")

    @property
    def smtp_password(self) -> str:
        return os.getenv("SMTP_PASSWORD", "")

    @property
    def alert_email_to(self) -> str:
        return os.getenv("ALERT_EMAIL_TO", "")

    @property
    def alert_email_from(self) -> str:
        return os.getenv("ALERT_EMAIL_FROM", "")

    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")

    @property
    def gemini_api_key_backup(self) -> str:
        return (
            os.getenv("GEMINI_API_KEY_BACKUP", "")
            or os.getenv("GEMINI_API_KEY_SECONDARY", "")
            or os.getenv("GEMINI_BACKUP_KEY", "")
        )

    @property
    def gemini_api_keys(self) -> List[str]:
        keys = [self.gemini_api_key, self.gemini_api_key_backup]
        return [k for k in dict.fromkeys(keys) if k]

    @property
    def groq_api_key(self) -> str:
        return os.getenv("GROQ_API_KEY", "")

    @property
    def epaper_prothomalo_user(self) -> str:
        return os.getenv("EPAPER_PROTHOMALO_USER", "")

    @property
    def epaper_prothomalo_password(self) -> str:
        return os.getenv("EPAPER_PROTHOMALO_PASSWORD", "")

    @property
    def alltender_user(self) -> str:
        return os.getenv("ALLTENDER_USER", "")

    @property
    def alltender_password(self) -> str:
        return os.getenv("ALLTENDER_PASSWORD", "")

    @property
    def crawler_contact_email(self) -> str:
        return os.getenv("CRAWLER_CONTACT_EMAIL", "tenders@acnabin.com")

    @property
    def dashboard_base_url(self) -> str:
        return os.getenv("DASHBOARD_BASE_URL", self.settings.get("dashboard_base_url", ""))


config = AppConfig()

