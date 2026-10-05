"""
Build full source list for all 30 banks and regulators.
"""
import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

with open(CONFIG_DIR / "ifrs9_banks.json", "r", encoding="utf-8") as f:
    banks = json.load(f)

# Well-known tender paths by bank domain
BANK_TENDER_PATHS = {
    "agranibank.org": "/tender",
    "jb.com.bd": "/tender",
    "rupalibank.com.bd": "/tender",
    "mblbd.com": "/tender",
    "midlandbankbd.net": "/tender",
    "citizensbankbd.com": "/tender",
    "sonalibank.com.bd": "/tender.php",
    "basicbank.com.bd": "/tender",
    "bdbl.com.bd": "/tender",
    "sammilitoislamibank.com.bd": "/tender",
    "krishibank.org.bd": "/tender",
    "rakub.org.bd": "/tender",
    "thecitybank.com": "/tender",
    "ificbank.com.bd": "/tender",
    "pubalibangla.com": "/tender",
    "dhakabank.com.bd": "/tender",
    "onebank.com.bd": "/tender",
    "mutualtrustbank.com": "/tender",
    "premierbankltd.com": "/tender",
    "trustbank.com.bd": "/tender",
    "meghnabank.com.bd": "/tender",
    "modhumotibank.ltd": "/tender",
    "shimantobank.com": "/tender",
    "communitybankbd.com": "/tender",
    "bgcb.com.bd": "/tender",
    "islamibankbd.com": "/tender",
    "icbislamic-bank.com": "/tender",
    "aibl.com.bd": "/tender",
    "combankbd.com": "/tender",
    "wooribank.com/bd": "/tender"
}

sources = []

# Regulators & e-GP
sources.append({
    "id": "src_bb_tender",
    "url": "https://www.bb.org.bd/en/index.php/about/tender",
    "organization_id": "reg_bangladesh_bank",
    "tier": 1,
    "requires_js": False,
    "verify_ssl": True,
    "rate_limit_seconds": 3,
    "enabled": True
})
sources.append({
    "id": "src_bppa_egp",
    "url": "https://www.eprocure.gov.bd",
    "organization_id": "gov_bppa_egp",
    "tier": 1,
    "requires_js": False,
    "verify_ssl": True,
    "rate_limit_seconds": 3,
    "enabled": True
})
sources.append({
    "id": "src_idlc_tender",
    "url": "https://idlc.com/procurement",
    "organization_id": "nbfi_idlc",
    "tier": 1,
    "requires_js": False,
    "verify_ssl": True,
    "rate_limit_seconds": 3,
    "enabled": True
})

# Add all 30 target banks
for bank in banks:
    bank_id = bank["id"]
    domain = bank["official_domain"]
    path = BANK_TENDER_PATHS.get(domain, "/tender")
    
    if "http" in domain:
        url = domain
    else:
        url = f"https://www.{domain.rstrip('/')}{path}"
        # Clean up double www if domain already has subdomains
        if domain.startswith("www."):
            url = f"https://{domain.rstrip('/')}{path}"

    src_id = f"src_{bank_id.replace('bank_', '')}_tender"
    sources.append({
        "id": src_id,
        "url": url,
        "organization_id": bank_id,
        "tier": 1,
        "requires_js": False,
        "verify_ssl": True,
        "rate_limit_seconds": 3,
        "enabled": True
    })

with open(CONFIG_DIR / "sources.json", "w", encoding="utf-8") as f:
    json.dump(sources, f, indent=2, ensure_ascii=False)

print(f"Generated {len(sources)} procurement sources in config/sources.json!")
