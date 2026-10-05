import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

res = client.table("sources").select("id, url, last_status, last_checked").execute()
print(f"Total Monitored Sources in Database: {len(res.data)}")
for s in res.data[:10]:
    print(f"- {s.get('id')}: {s.get('url')} [Status: {s.get('last_status')}]")
