"""
Clean database reset script for SPMS.
Drops all existing tables in spms_db using the migration user
and re-applies schema.sql from scratch for a pristine starting point.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from sqlalchemy import text
from app.database import migration_engine
from scripts.migrate import run_migration

def reset_database():
    print("[RESET] Starting database reset for SPMS...")
    with migration_engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        
        # Fetch all tables
        result = conn.execute(text("SHOW TABLES;"))
        tables = [row[0] for row in result.fetchall()]
        
        if tables:
            print(f"[RESET] Dropping {len(tables)} existing tables...")
            for table in tables:
                conn.execute(text(f"DROP TABLE IF EXISTS `{table}`;"))
                print(f"        Dropped table `{table}`")
        else:
            print("[RESET] No existing tables found.")
            
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        conn.commit()

    print("[RESET] Applying schema.sql to recreate tables and constraints...")
    run_migration()
    print("[RESET] Database reset complete! SPMS is now clean and ready for seeding.")

if __name__ == "__main__":
    reset_database()
