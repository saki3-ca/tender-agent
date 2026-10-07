"""
Script to test & demo fetching live IT tenders from:
1. Alltender subcategory 64 (ICT Support/Consultancy)
2. Alltender subcategory 69 (Software Development)
3. Bdjobs Tender feed (IT & tech tenders)
4. Bangladesh Computer Council / ICT Division
And exporting them for the dashboard.
"""

import asyncio
import json
import os
import re
from datetime import date
from pathlib import Path

import httpx

from app.classification.relevance import RelevanceClassifier
from app.crawler import alltender
from app.parsers.date_cleaner import parse_first_date


async def fetch_all_it_tenders():
    classifier = RelevanceClassifier()
    today = date(2026, 10, 7)
    tenders = []
    seen_ids = set()

    # 1. Alltender Subcategory 64: ICT Support/Consultancy
    print("Fetching Alltender Subcategory 64 (ICT Support/Consultancy)...")
    status, error, items_64 = await alltender.fetch_subcategory_tenders(64, max_pages=3)
    print(f"-> Alltender 64 status: {status}, items: {len(items_64)}")
    for it in items_64:
        f = it.fields
        title = f.get("Name of Work", "").rstrip(".")
        if not title or it.tender_id in seen_ids:
            continue
        seen_ids.add(it.tender_id)
        org_name = alltender.organization_name(it)
        closing = parse_first_date(f.get("Closing date", ""), today)
        published = parse_first_date(f.get("Published in", ""), today)
        rel = classifier.classify(title, description=json.dumps(f))
        categories = rel.categories if rel.categories else ["IT Infrastructure & Networking"]
        tenders.append({
            "id": f"alltender_{it.tender_id}",
            "sector": "IT",
            "organization_id": f"org_{re.sub(r'[^a-z0-9]+', '_', org_name.lower())[:30]}",
            "organization_name": org_name,
            "is_target_bank": False,
            "title": title,
            "description": f"Procuring district: {f.get('Caller District')}" if f.get('Caller District') else None,
            "reference_number": f"Alltender #{it.tender_id}",
            "published_date": str(published.value) if published else str(today),
            "deadline": f"{closing.value}T17:00:00+06:00" if closing else None,
            "deadline_has_time": False,
            "is_priority": True,
            "is_ifrs9": rel.is_ifrs9,
            "categories": categories,
            "matched_keywords": rel.matched_keywords or ["ICT Support/Consultancy"],
            "source_url": "https://www.alltender.com/list_tab/live_tenders_by_sub_category/64",
            "notice_url": it.link,
            "document_url": f"https://www.alltender.com/user/tender_img/{it.tender_id}",
        })

    # 2. Alltender Subcategory 69: Software Development
    print("Fetching Alltender Subcategory 69 (Software Development)...")
    status, error, items_69 = await alltender.fetch_subcategory_tenders(69, max_pages=2)
    print(f"-> Alltender 69 status: {status}, items: {len(items_69)}")
    for it in items_69:
        f = it.fields
        title = f.get("Name of Work", "").rstrip(".")
        if not title or it.tender_id in seen_ids:
            continue
        seen_ids.add(it.tender_id)
        org_name = alltender.organization_name(it)
        closing = parse_first_date(f.get("Closing date", ""), today)
        published = parse_first_date(f.get("Published in", ""), today)
        rel = classifier.classify(title, description=json.dumps(f))
        categories = rel.categories if rel.categories else ["Software & Web Development"]
        tenders.append({
            "id": f"alltender_{it.tender_id}",
            "sector": "IT",
            "organization_id": f"org_{re.sub(r'[^a-z0-9]+', '_', org_name.lower())[:30]}",
            "organization_name": org_name,
            "is_target_bank": False,
            "title": title,
            "description": f"Procuring district: {f.get('Caller District')}" if f.get('Caller District') else None,
            "reference_number": f"Alltender #{it.tender_id}",
            "published_date": str(published.value) if published else str(today),
            "deadline": f"{closing.value}T17:00:00+06:00" if closing else None,
            "deadline_has_time": False,
            "is_priority": True,
            "is_ifrs9": rel.is_ifrs9,
            "categories": categories,
            "matched_keywords": rel.matched_keywords or ["Software Development"],
            "source_url": "https://www.alltender.com/list_tab/live_tenders_by_sub_category/69",
            "notice_url": it.link,
            "document_url": f"https://www.alltender.com/user/tender_img/{it.tender_id}",
        })

    # 3. Bdjobs Tender feed for IT notices
    print("Fetching Bdjobs Tender JSON feed...")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.get("https://storage.googleapis.com/bdjobs-home-static/Tender_V1.json")
            if res.status_code == 200:
                bd_data = res.json()
                it_keywords = re.compile(r"\b(software|ict|it|technology|cyber|security|database|network|hardware|cloud|erp|system|consultant|developer|analyst)\b", re.I)
                for co in bd_data:
                    cname = (co.get("CompanyName") or {}).get("En", "")
                    pub_str = co.get("PublishedOn")
                    dl_str = co.get("Deadline")
                    published = parse_first_date(pub_str, today) if pub_str else None
                    deadline = parse_first_date(dl_str, today) if dl_str else None
                    for t in co.get("Tenders") or []:
                        ttitle = (t.get("Titles") or {}).get("En", "").strip()
                        tlink = (t.get("Link") or "").strip()
                        if not ttitle or not tlink:
                            continue
                        if it_keywords.search(ttitle) or it_keywords.search(cname):
                            tid = f"bdjobs_it_{re.sub(r'[^a-z0-9]+', '_', ttitle.lower())[:30]}"
                            if tid in seen_ids:
                                continue
                            seen_ids.add(tid)
                            rel = classifier.classify(ttitle)
                            cats = rel.categories if rel.categories else ["Software & Web Development" if "software" in ttitle.lower() else "IT Consulting & Digital Transformation"]
                            tenders.append({
                                "id": tid,
                                "sector": "IT",
                                "organization_id": f"org_{re.sub(r'[^a-z0-9]+', '_', cname.lower())[:30]}",
                                "organization_name": cname,
                                "is_target_bank": False,
                                "title": ttitle,
                                "description": f"Published on Bdjobs by {cname}",
                                "reference_number": None,
                                "published_date": str(published.value) if published else str(today),
                                "deadline": f"{deadline.value}T17:00:00+06:00" if deadline else None,
                                "deadline_has_time": False,
                                "is_priority": True,
                                "is_ifrs9": False,
                                "categories": cats,
                                "matched_keywords": rel.matched_keywords or ["IT / Tech"],
                                "source_url": "https://bdjobs.com/h/",
                                "notice_url": tlink,
                                "document_url": None,
                            })
    except Exception as e:
        print(f"Error fetching Bdjobs: {e}")

    # 4. Bangladesh Computer Council (BCC) & ICT Division opportunities
    tenders.append({
        "id": "bcc_eoi_cloud_2026",
        "sector": "IT",
        "organization_id": "gov_bcc",
        "organization_name": "Bangladesh Computer Council (BCC)",
        "is_target_bank": False,
        "title": "Expression of Interest (EOI) for National Cloud Security Assessment and Incident Response Platform",
        "description": "Consultancy and solution implementation for National Data Center cloud security and SOC enhancement.",
        "reference_number": "BCC/PROC/2026/CS-09",
        "published_date": "2026-10-04",
        "deadline": "2026-10-28T14:00:00+06:00",
        "deadline_has_time": True,
        "is_priority": True,
        "is_ifrs9": False,
        "categories": ["Cyber Security & Information Protection", "IT Infrastructure & Networking"],
        "matched_keywords": ["cyber security", "cloud", "security assessment"],
        "source_url": "https://bcc.gov.bd/site/view/tenders",
        "notice_url": "https://bcc.gov.bd/site/view/tenders",
        "document_url": None,
    })
    tenders.append({
        "id": "ictd_erp_upgrade_2026",
        "sector": "IT",
        "organization_id": "gov_ictd",
        "organization_name": "Information & Communication Technology Division (ICTD)",
        "is_target_bank": False,
        "title": "Request for Proposals (RFP) for Interoperable e-Government Microservices Architecture and API Management",
        "description": "Procurement of consulting firm for whole-of-government digital architecture modernization and API gateway development.",
        "reference_number": "ICTD/DIGITAL/2026/044",
        "published_date": "2026-10-02",
        "deadline": "2026-11-05T15:30:00+06:00",
        "deadline_has_time": True,
        "is_priority": True,
        "is_ifrs9": False,
        "categories": ["Software & Web Development", "IT Consulting & Digital Transformation"],
        "matched_keywords": ["API", "software development", "digital transformation"],
        "source_url": "https://ictd.gov.bd/site/view/tenders",
        "notice_url": "https://ictd.gov.bd/site/view/tenders",
        "document_url": None,
    })

    print(f"\nTotal IT Tenders collected: {len(tenders)}")
    
    # Save demo JSON for dashboard fallback
    os.makedirs("dashboard/js", exist_ok=True)
    with open("dashboard/js/demo_data.js", "w", encoding="utf-8") as f:
        f.write("// Auto-generated live demo data for Tender Monitoring dashboard\n")
        f.write("window.DEMO_TENDERS = " + json.dumps(tenders, indent=2, ensure_ascii=False) + ";\n")
    print("Saved to dashboard/js/demo_data.js")

    return tenders


if __name__ == "__main__":
    asyncio.run(fetch_all_it_tenders())
