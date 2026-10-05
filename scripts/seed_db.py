"""
ACNABIN Database Seeder.
Populates Supabase with 30 Target Banks, Organizations, and Sources from config files.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
env_path = ROOT_DIR / ".env"
load_dotenv(dotenv_path=env_path)

from app.utils.config import config
from app.db.supabase import db
from app.utils.logging import logger
from app.db.supabase import db
from app.utils.logging import logger

def seed_database():
    if not db.client:
        logger.error("Supabase client not connected. Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
        sys.exit(1)

    logger.info("Seeding 30 IFRS 9 Target Banks...")
    for bank in config.ifrs9_banks:
        try:
            org_payload = {
                "organization_id": bank["id"],
                "canonical_name": bank["canonical_name"],
                "aliases": bank.get("aliases", []),
                "official_domain": bank.get("official_domain"),
                "organization_type": bank.get("organization_type", "PRIVATE_COMMERCIAL_BANK"),
                "sector": "banking",
                "is_ifrs9_target": True,
                "source_status": "OK",
                "last_verified": bank.get("last_verified", "2026-10-01"),
                "notes": bank.get("notes")
            }
            db.client.table("organizations").upsert(org_payload).execute()
        except Exception as e:
            logger.error(f"Error upserting target bank {bank['id']}: {e}")

    logger.info("Seeding other organizations...")
    orgs = config.organizations
    for org in orgs:
        try:
            db.client.table("organizations").upsert(org).execute()
            logger.info(f"Upserted organization: {org.get('organization_id')} ({org.get('canonical_name')})")
        except Exception as e:
            logger.error(f"Error upserting org {org.get('organization_id')}: {e}")

    logger.info("Seeding sources...")
    sources = config.sources
    valid_source_fields = {"id", "url", "organization_id", "tier", "requires_js", "verify_ssl", "rate_limit_seconds", "enabled"}
    for src in sources:
        try:
            payload = {k: v for k, v in src.items() if k in valid_source_fields}
            db.client.table("sources").upsert(payload).execute()
            logger.info(f"Upserted source: {src.get('id')} ({src.get('url')})")
        except Exception as e:
            logger.error(f"Error upserting source {src.get('id')}: {e}")

    # Seed default allowlisted users
    logger.info("Seeding default app users...")
    users = [
        {"email": "admin@acnabin.com", "full_name": "ACNABIN Tender Administrator", "role": "admin", "is_active": True},
        {"email": "partner.audit@acnabin.com", "full_name": "Audit Partner", "role": "reviewer", "is_active": True},
        {"email": "consulting@acnabin.com", "full_name": "Advisory Services Team", "role": "reviewer", "is_active": True}
    ]
    for user in users:
        try:
            db.client.table("app_users").upsert(user).execute()
            logger.info(f"Upserted user: {user.get('email')}")
        except Exception as e:
            logger.error(f"Error upserting user {user.get('email')}: {e}")

    logger.info("Seeding completed successfully.")

if __name__ == "__main__":
    seed_database()
