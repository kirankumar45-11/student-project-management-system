"""
Playwright multi-viewport responsive screenshot suite for SPMS Phase 6.
Captures key application pages across 3 responsive breakpoints:
- Mobile:  360x740
- Tablet:  768x1024
- Desktop: 1280x720
In both LIGHT mode and DARK mode.
"""
import os
import sys
import time
import threading
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

import uvicorn
from app.database import SessionLocal
from app.models.user import User, RoleEnum
from app.models.topic import Topic, TopicAssignment, TopicStatusEnum, AssignmentStatusEnum
from app.models.assessment import Assessment

SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
MOBILE_DIR = SCREENSHOTS_DIR / "mobile"
TABLET_DIR = SCREENSHOTS_DIR / "tablet"
DESKTOP_DIR = SCREENSHOTS_DIR / "desktop"

for d in [SCREENSHOTS_DIR, MOBILE_DIR, TABLET_DIR, DESKTOP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://127.0.0.1:8000"
server = None


def start_server():
    global server
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def capture_all_viewports():
    print("[VIEWPORTS] Launching Playwright multi-viewport responsive capture...")

    # Discover demo or test records in DB
    db = SessionLocal()
    # Users
    coord_user = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
    sup_user = db.query(User).filter(User.role == RoleEnum.SUPERVISOR).first()
    stu_user = db.query(User).filter(User.role == RoleEnum.STUDENT).first()

    # Active assignment for grading/submissions
    active_assign = db.query(TopicAssignment).filter(TopicAssignment.status == AssignmentStatusEnum.ACTIVE).first()
    active_assign_id = active_assign.id if active_assign else 1

    # Assessment for finalization
    assess = db.query(Assessment).first()
    assess_id = assess.id if assess else 1

    # Archived topic for archive search & detail
    arch_topic = db.query(Topic).filter(Topic.status == TopicStatusEnum.ARCHIVED).first()
    arch_topic_id = arch_topic.id if arch_topic else 1

    coord_username = coord_user.username if coord_user else "admin"
    sup_username = sup_user.username if sup_user else "supervisor1"
    stu_username = stu_user.username if stu_user else "1SP23CS001"

    db.close()

    viewports = [
        ("mobile", {"width": 360, "height": 740}, MOBILE_DIR),
        ("tablet", {"width": 768, "height": 1024}, TABLET_DIR),
        ("desktop", {"width": 1280, "height": 720}, DESKTOP_DIR),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for vp_name, vp_dims, out_dir in viewports:
            print(f"\n--- Capturing Breakpoint: {vp_name.upper()} ({vp_dims['width']}x{vp_dims['height']}) ---")

            for mode in ["light", "dark"]:
                def render_session(user, pwd, pages_to_capture):
                    context = browser.new_context(
                        viewport=vp_dims,
                        device_scale_factor=1,
                        color_scheme=mode
                    )
                    page = context.new_page()

                    def nav(url):
                        page.goto(url, wait_until="domcontentloaded", timeout=15000)
                        page.evaluate(f"document.documentElement.setAttribute('data-bs-theme', '{mode}')")
                        time.sleep(0.3)

                    if user and pwd:
                        nav(f"{BASE_URL}/auth/login")
                        page.fill("#username", user)
                        page.fill("#password", pwd)
                        page.click("form[action='/auth/login'] button[type=submit]")
                        try:
                            page.wait_for_url(f"{BASE_URL}/dashboard", timeout=5000)
                        except Exception:
                            # Try fallback password
                            nav(f"{BASE_URL}/auth/login")
                            page.fill("#username", user)
                            page.fill("#password", "Password123!")
                            page.click("form[action='/auth/login'] button[type=submit]")
                            page.wait_for_url(f"{BASE_URL}/dashboard", timeout=5000)

                    for url, filename in pages_to_capture:
                        nav(url)
                        img_path = out_dir / f"{filename}_{vp_name}_{mode}.png"
                        page.screenshot(path=str(img_path), full_page=True)
                        print(f"  [Saved] {img_path.name}")

                        if vp_name == "mobile":
                            # Also copy to root screenshots/ with _360px_ suffix for user requirements
                            root_path = SCREENSHOTS_DIR / f"{filename}_360px_{mode}.png"
                            root_path.write_bytes(img_path.read_bytes())

                    context.close()

                # 1. Public Pages (Login)
                render_session(None, None, [
                    (f"{BASE_URL}/auth/login", "login")
                ])

                # 2. Student Session
                render_session(stu_username, "Demo123456!", [
                    (f"{BASE_URL}/dashboard", "student_dashboard"),
                    (f"{BASE_URL}/submissions", "submissions_pipeline"),
                    (f"{BASE_URL}/archive", "archive_search"),
                    (f"{BASE_URL}/archive/{arch_topic_id}", "archive_detail")
                ])

                # 3. Supervisor Session
                render_session(sup_username, "Demo123456!", [
                    (f"{BASE_URL}/dashboard", "supervisor_dashboard"),
                    (f"{BASE_URL}/assessments/{active_assign_id}/grade", "grading_form")
                ])

                # 4. Coordinator Session
                render_session(coord_username, "Demo123456!", [
                    (f"{BASE_URL}/dashboard", "coordinator_dashboard"),
                    (f"{BASE_URL}/coordinator/assessments/{assess_id}/finalize", "finalization_screen")
                ])

        browser.close()
    print("\n[VIEWPORTS SUCCESS] All multi-viewport responsive screenshots captured!")


def main():
    t = threading.Thread(target=start_server, daemon=True)
    t.start()

    # Wait for server
    for _ in range(15):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as r:
                if r.status == 200:
                    break
        except Exception:
            continue

    try:
        capture_all_viewports()
    finally:
        if server:
            server.should_exit = True
        time.sleep(1)


if __name__ == "__main__":
    main()
