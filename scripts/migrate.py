import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from sqlalchemy import text
from app.database import migration_engine
from app.config import settings

def run_migration():
    schema_path = ROOT_DIR / "schema.sql"
    sql_script = schema_path.read_text(encoding="utf-8")

    statements = [stmt.strip() for stmt in sql_script.split(";") if stmt.strip()]

    with migration_engine.connect() as conn:
        for idx, stmt in enumerate(statements, 1):
            clean_stmt = "\n".join(
                line for line in stmt.splitlines() 
                if not line.strip().startswith("--")
            ).strip()
            if not clean_stmt:
                continue
            first_line = clean_stmt.splitlines()[0][:60]
            try:
                conn.execute(text(clean_stmt))
                print(f"[OK {idx}] {first_line}")
            except Exception as e:
                print(f"[ERROR {idx}] {first_line}")
                print(f"       Details: {e}")
                raise
        conn.commit()

    print("[SUCCESS] All migration statements executed successfully!")

if __name__ == "__main__":
    run_migration()
