import sqlalchemy
from sqlalchemy import create_engine
import sys

# DEBUG: Database URL with password Grafik2026!
db_url = "postgresql://postgres.oxzlfmaotsosxzvivjrt:Grafik2026!@aws-1-eu-west-1.pooler.supabase.com:6543/postgres"

print("--- DB Connection Test ---")
try:
    print(f"Connecting to: {db_url.split('@')[1]}...")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        print("SUCCESS: Connected to database!")
except Exception as e:
    print("ERROR: Connection failed.")
    print(f"Details: {e}")
