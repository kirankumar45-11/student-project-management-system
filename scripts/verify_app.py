import os
import sys
import time
import urllib.request
import json
from pathlib import Path
import uvicorn
import threading

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.database import engine
from sqlalchemy import text
from tests.e2e.test_phase1_playwright import run_playwright_e2e
from tests.e2e.test_phase2_playwright import run_phase2_playwright_e2e
from tests.e2e.test_phase3_playwright import run_phase3_playwright_e2e
from tests.e2e.test_phase4_playwright import run_phase4_playwright_e2e
from tests.e2e.test_phase5_playwright import run_phase5_playwright_e2e
from tests.e2e.capture_desktop_screenshots import capture_all_desktop_screenshots

server_thread = None
server = None

def run_server():
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, log_level="info")
    global server
    server = uvicorn.Server(config)
    server.run()

def main():
    print("=" * 64)
    print("STARTING SPMS FASTAPI SERVER ON 127.0.0.1:8000")
    print("=" * 64)

    # 1. Direct MySQL Connection & Version check
    with engine.connect() as conn:
        db_version = conn.execute(text("SELECT VERSION()")).scalar()
        db_user = conn.execute(text("SELECT CURRENT_USER()")).scalar()
        print(f"[MYSQL DIRECT] Successfully connected via SQLAlchemy 2.x engine!")
        print(f"               Database User:    {db_user}")
        print(f"               SELECT VERSION(): {db_version}")
    print("=" * 64)

    # 2. Start Uvicorn in background thread
    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    # Wait for server to come up
    healthy = False
    for attempt in range(15):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    print("[HEALTH CHECK 200 OK]")
                    print(json.dumps(data, indent=2))
                    healthy = True
                    break
        except Exception:
            continue

    if not healthy:
        print("[ERROR] Server failed to respond to /health in 15 seconds")
        sys.exit(1)

    print("=" * 64)
    print("RUNNING PLAYWRIGHT 360PX VIEWPORT SCREENSHOT CAPTURE (PHASE 1 - 5)")
    print("=" * 64)
    run_playwright_e2e()
    print("-" * 64)
    run_phase2_playwright_e2e()
    print("-" * 64)
    run_phase3_playwright_e2e()
    print("-" * 64)
    run_phase4_playwright_e2e()
    print("-" * 64)
    run_phase5_playwright_e2e()
    print("-" * 64)
    print("RUNNING 1280x720 DESKTOP SCREENSHOT CAPTURE (LIGHT MODE)")
    print("-" * 64)
    capture_all_desktop_screenshots()
    print("=" * 64)
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY")
    print("=" * 64)
    if server:
        server.should_exit = True
    time.sleep(1)

if __name__ == "__main__":
    main()
