"""
Configuration loader and validator for ACNABIN Tender Agent.
Loads settings, 30 target banks, organizations, sources, keywords, categories, and scoring weights.
Enforces startup assertions per project specifications.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"

REQUIRED_CATEGORIES = {
    "IFRS9_ECL",
    "AUDIT_ASSURANCE",
    "RISK_CONTROL",
    "ACCOUNTING_REPORTING",
    "PROCESS_ADVISORY",
    "TAX_VAT",
    "FINANCIAL_ADVISORY",
    "TRAINING",
    "OTHER_PROFESSIONAL"
}


class ConfigError(Exception):
    """Raised when configuration validation fails."""
    pass


class AppConfig:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or CONFIG_DIR
        self.settings: Dict[str, Any] = self._load_yaml("settings.yaml")
        self.keywords: Dict[str, Any] = self._load_json("keywords.json")
        self.categories: List[Dict[str, Any]] = self._load_json("categories.json")
        self.scoring: Dict[str, Any] = self._load_yaml("scoring.yaml")
        self.ifrs9_banks: List[Dict[str, Any]] = self._load_json("ifrs9_banks.json")
        self.organizations: List[Dict[str, Any]] = self._load_json("organizations.json")
        self.sources: List[Dict[str, Any]] = self._load_json("sources.json")

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

    def validate(self) -> None:
        """Startup assertion checks."""
        # 1. Assert exactly 30 unique target banks
        if len(self.ifrs9_banks) != 30:
            raise ConfigError(
                f"Startup validation failed: Expected exactly 30 IFRS 9 target banks, found {len(self.ifrs9_banks)}."
            )
        
        bank_ids = [b["id"] for b in self.ifrs9_banks]
        if len(set(bank_ids)) != 30:
            raise ConfigError("Startup validation failed: Duplicate bank id found in config/ifrs9_banks.json")

        # 2. Assert categories match enum
        loaded_category_codes = {c["code"] for c in self.categories}
        if loaded_category_codes != REQUIRED_CATEGORIES:
            missing = REQUIRED_CATEGORIES - loaded_category_codes
            extra = loaded_category_codes - REQUIRED_CATEGORIES
            raise ConfigError(
                f"Startup validation failed for categories. Missing: {missing}, Extra: {extra}"
            )

        # 3. Assert keywords structure
        if "ifrs9_ecl" not in self.keywords or "strong_terms" not in self.keywords["ifrs9_ecl"]:
            raise ConfigError("Missing strong terms in config/keywords.json")
        if "procurement_terms" not in self.keywords:
            raise ConfigError("Missing procurement terms in config/keywords.json")

        # 4. Assert scoring weights
        if "category_base_scores" not in self.scoring or "modifiers" not in self.scoring:
            raise ConfigError("Invalid scoring structure in config/scoring.yaml")

    # Environment Secrets Accessors
    @property
    def supabase_url(self) -> str:
        return os.getenv("SUPABASE_URL", "")

    @property
    def supabase_service_role_key(self) -> str:
        return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    @property
    def ai_mode(self) -> str:
        mode = os.getenv("AI_MODE", self.settings.get("ai", {}).get("mode", "full")).lower()
        if mode not in {"off", "triage_only", "full"}:
            return "full"
        return mode

    @property
    def groq_api_key(self) -> str:
        return os.getenv("GROQ_API_KEY", "")

    @property
    def groq_triage_model(self) -> str:
        return os.getenv("GROQ_TRIAGE_MODEL", "llama-3.3-70b-versatile")

    @property
    def groq_review_model(self) -> str:
        return os.getenv("GROQ_REVIEW_MODEL", "mixtral-8x7b-32768")

    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "")

    @property
    def gemini_model(self) -> str:
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    @property
    def cloudflare_account_id(self) -> str:
        return os.getenv("CLOUDFLARE_ACCOUNT_ID", "")

    @property
    def cloudflare_api_token(self) -> str:
        return os.getenv("CLOUDFLARE_API_TOKEN", "")

    @property
    def cloudflare_embed_model(self) -> str:
        return os.getenv("CLOUDFLARE_EMBED_MODEL", "@cf/baai/bge-m3")

    @property
    def telegram_bot_token(self) -> str:
        return os.getenv("TELEGRAM_BOT_TOKEN", "")

    @property
    def telegram_chat_id(self) -> str:
        return os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def crawler_contact_email(self) -> str:
        return os.getenv("CRAWLER_CONTACT_EMAIL", "tenders@acnabin.com")

    @property
    def run_time_budget_minutes(self) -> float:
        val = os.getenv("RUN_TIME_BUDGET_MINUTES")
        if val:
            try:
                return float(val)
            except ValueError:
                pass
        return float(self.settings.get("free_tier_caps", {}).get("github_actions_run_budget_minutes", 14))


# Global configuration singleton
config = AppConfig()
