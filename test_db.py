
import db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def test_db():
    try:
        drafts = db.get_all_schedules_with_status("DRAFT")
        print(f"Found {len(drafts)} drafts.")
        for yr, mo, loc_id, loc_name in drafts:
            print(f"Draft: {loc_name}, {mo}/{yr} (ID: {loc_id})")
        
        all_s_count = 0
        with db.SessionLocal() as session:
            all_s_count = session.query(db.Schedule).count()
        print(f"Total schedules in DB: {all_s_count}")
        
        drafts_direct = []
        with db.SessionLocal() as session:
            drafts_direct = session.query(db.Schedule.year, db.Schedule.month, db.Location.id, db.Location.name).join(db.Location).filter(
                db.Schedule.status == "DRAFT"
            ).distinct().all()
        print(f"Direct query found {len(drafts_direct)} drafts.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_db()
