import os
import sys
import time
import threading
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))

import uvicorn
from app.database import SessionLocal
from app.models.user import User, RoleEnum
from app.models.topic import Topic, TopicStatusEnum

BASE_URL = "http://127.0.0.1:8000"
server = None


def start_server():
    global server
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def check_overflow():
    db = SessionLocal()
    coord_u = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
    sup_u = db.query(User).filter(User.role == RoleEnum.SUPERVISOR).first()
    stu_u = db.query(User).filter(User.role == RoleEnum.STUDENT).first()
    arch_t = db.query(Topic).filter(Topic.status == TopicStatusEnum.ARCHIVED).first()

    coord_username = coord_u.username if coord_u else "admin"
    sup_username = sup_u.username if sup_u else "prof_turing"
    stu_username = stu_u.username if stu_u else "1SP23CS001"
    arch_id = arch_t.id if arch_t else 1

    # Fetch IDs for extended pages
    from app.models.communication import ForumThread
    from app.models.topic import TopicAssignment
    from app.models.submission import Submission
    from app.models.assessment import Assessment

    th = db.query(ForumThread).first()
    thread_id = th.id if th else 1

    assign = db.query(TopicAssignment).filter(TopicAssignment.supervisor_id == sup_u.supervisor_profile.id).first() if sup_u and sup_u.supervisor_profile else None
    assign_id = assign.id if assign else 1

    # Ensure unfinalized assessment for coordinator finalization & supervisor grading
    if assign:
        if not assign.assessment:
            assign.assessment = Assessment(
                assignment_id=assign.id,
                supervisor_id=assign.supervisor_id,
                presentation_score=28.0,
                report_score=28.0,
                implementation_score=38.0,
                total_score=94.0,
                supervisor_remarks="Evaluation for responsive check"
            )
            db.commit()
        else:
            assign.assessment.finalized_at = None
            db.commit()
        assess_id = assign.assessment.id
    else:
        assess_id = 1

    sub = assign.submissions[0] if assign and assign.submissions else db.query(Submission).first()
    sub_id = sub.id if sub else 1

    db.close()

    print("=" * 70)
    print("PLAYWRIGHT 360PX HORIZONTAL OVERFLOW CHECK (LIGHT & DARK MODES)")
    print("Criterion: document.documentElement.scrollWidth <= window.innerWidth (360px)")
    print("=" * 70)

    checked_pages = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for mode in ["light", "dark"]:
            print(f"\n--- Checking Mode: {mode.upper()} ---")

            def test_pages_for_user(user, pwd, pages):
                context = browser.new_context(
                    viewport={"width": 360, "height": 740},
                    device_scale_factor=1,
                    color_scheme=mode
                )
                page = context.new_page()

                def nav(url):
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    page.evaluate(f"document.documentElement.setAttribute('data-bs-theme', '{mode}')")
                    time.sleep(0.2)

                if user and pwd:
                    nav(f"{BASE_URL}/auth/login")
                    page.fill("#username", user)
                    page.fill("#password", pwd)
                    page.click("form[action='/auth/login'] button[type=submit]")
                    try:
                        page.wait_for_url(f"{BASE_URL}/dashboard", timeout=5000)
                    except Exception:
                        nav(f"{BASE_URL}/auth/login")
                        page.fill("#username", user)
                        page.fill("#password", "Password123!")
                        page.click("form[action='/auth/login'] button[type=submit]")
                        page.wait_for_url(f"{BASE_URL}/dashboard", timeout=5000)

                for path_url, label in pages:
                    nav(f"{BASE_URL}{path_url}")
                    scroll_w = page.evaluate("() => document.documentElement.scrollWidth")
                    inner_w = page.evaluate("() => window.innerWidth")

                    entry = f"{label:30} [{path_url:25}] ({mode:5}): scrollWidth={scroll_w}px, innerWidth={inner_w}px"
                    assert scroll_w <= inner_w, f"HORIZONTAL OVERFLOW DETECTED: {entry}"
                    print(f"  [PASS] {entry}")
                    if (label, path_url) not in checked_pages:
                        checked_pages.append((label, path_url))

                context.close()

            # 1. Public Pages
            test_pages_for_user(None, None, [
                ("/auth/login", "Login Page"),
                ("/auth/register", "Registration Page"),
            ])

            # 2. Student Pages
            test_pages_for_user(stu_username, "Demo123456!", [
                ("/dashboard", "Student Dashboard"),
                ("/submissions", "Submissions Stepper"),
                ("/topics", "Topics Explorer"),
                ("/topics/propose", "Propose Topic"),
                ("/archive", "Project Archive Index"),
                (f"/archive/{arch_id}", "Archive Detail Page"),
                ("/guidelines", "Guidelines Index"),
                ("/forum", "Department Forum"),
                (f"/forum/{thread_id}", "Forum Thread View"),
                ("/notifications", "Notifications Center"),
                ("/profile/student", "Student Profile Page"),
                ("/auth/change-password", "Change Password Page"),
                (f"/messaging/{assign_id}", "Messaging Project Thread"),
            ])

            # 3. Supervisor Pages
            test_pages_for_user(sup_username, "Demo123456!", [
                ("/dashboard", "Supervisor Dashboard"),
                ("/submissions/reviews", "Supervisor Reviews"),
                ("/assessments", "Supervisor Assessments"),
                (f"/submissions/{sub_id}/review", "Submission Review Page"),
                (f"/assessments/{assign_id}/grade", "Supervisor Grading Form"),
            ])

            # 4. Coordinator Pages
            test_pages_for_user(coord_username, "Demo123456!", [
                ("/dashboard", "Coordinator Dashboard"),
                ("/coordinator/approvals", "Account Approvals"),
                ("/coordinator/supervisors", "Supervisor Slots"),
                ("/coordinator/topics", "Topic Approvals"),
                ("/coordinator/deadlines", "Milestone Deadlines"),
                ("/coordinator/assessments", "Finalization Grades"),
                (f"/coordinator/assessments/{assess_id}/finalize", "Coordinator Finalization Form"),
            ])

        browser.close()

    print("=" * 70)
    print(f"[SUCCESS] All {len(checked_pages)} distinct pages passed 360px overflow checks in both modes!")
    print("=" * 70)


def main():
    t = threading.Thread(target=start_server, daemon=True)
    t.start()

    for _ in range(15):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as r:
                if r.status == 200:
                    break
        except Exception:
            continue

    try:
        check_overflow()
    finally:
        if server:
            server.should_exit = True
        time.sleep(1)


if __name__ == "__main__":
    main()
