import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

client = create_client(url, key)

print("--- Supabase Live Status ---")
runs = client.table("runs").select("*").order("id", desc=True).limit(3).execute()
print(f"Total Runs logged: {len(runs.data)}")
for r in runs.data:
    print(f"  Run #{r.get('id')} - {r.get('run_type')} - Status: {r.get('status')} - Sources: {r.get('sources_checked')}")

checks = client.table("source_checks").select("*").order("id", desc=True).limit(5).execute()
print(f"\nRecent Source Checks logged: {len(checks.data)}")
for c in checks.data:
    print(f"  Source: {c.get('source_id')} - Status: {c.get('http_status')} - Found: {c.get('items_found')}")

opps = client.table("opportunities").select("id, title, category, priority, score").execute()
print(f"\nOpportunities in DB: {len(opps.data)}")
for op in opps.data:
    print(f"  [{op.get('priority')}] Score: {op.get('score')} - {op.get('category')}: {op.get('title')[:60]}")
