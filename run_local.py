import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables from .env (must exist)
env_path = Path(__file__).parent / ".env"
if not env_path.is_file():
    print(f"Warning: .env file not found at {env_path}. Using placeholder environment variables.")
else:
    load_dotenv(dotenv_path=env_path)

# load_dotenv called conditionally above

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not all([SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY]):
    print("Error: One or more Supabase environment variables are missing. Please ensure SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY are set in .env.")
    sys.exit(1)

# Initialize Supabase client (using service role for admin tasks)
# Initialize Supabase client (service role) only if credentials are provided
if all([SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY]) and not any("your-" in val for val in [SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY]):
    client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    try:
        response = client.table("organizations").select("organization_id, canonical_name").limit(5).execute()
        print(f"Successfully connected to Supabase! Found {len(response.data)} organizations:")
        for row in response.data:
            print(f"- {row.get('organization_id')}: {row.get('canonical_name')}")
    except Exception as e:
        print(f"Exception while querying Supabase: {e}")
else:
    print("Supabase credentials not configured. Skipping database connection.")
