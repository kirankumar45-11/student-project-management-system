import os
import time
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.database import SessionLocal
from app.models.user import User, RoleEnum, AccountStatusEnum, Department, AcademicSession
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import Topic, TopicStatusEnum, TopicProposedRoleEnum
from app.core.security import hash_password

BASE_URL = os.getenv("TEST_SERVER_URL", "http://127.0.0.1:8000")
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

def run_phase2_playwright_e2e():
    print(f"[E2E Phase 2] Starting full flow & 360px visual capture against {BASE_URL}...")
    
    # Setup test coordinator and supervisor in DB
    db = SessionLocal()
    coord = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
    if not coord:
        coord = User(
            username="admin", email="coordinator@spms.local",
            password_hash=hash_password("Password123!"), role=RoleEnum.ADMIN,
            status=AccountStatusEnum.APPROVED, must_change_password=False
        )
        db.add(coord)
        db.commit()
    else:
        coord.password_hash = hash_password("Password123!")
        coord.must_change_password = False
        db.commit()

    dept = db.query(Department).first()
    sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # Ensure a supervisor exists with Password123!
    sup_user = db.query(User).filter(User.username == "E2E_SUPERVISOR_01").first()
    if not sup_user:
        sup_user = User(
            username="E2E_SUPERVISOR_01", email="e2e_supervisor_01@spms.local",
            password_hash=hash_password("Password123!"), role=RoleEnum.SUPERVISOR,
            status=AccountStatusEnum.APPROVED, must_change_password=False, session_version=1
        )
        db.add(sup_user)
        db.flush()
        sup = Supervisor(
            user_id=sup_user.id, department_id=dept.id,
            full_name="Dr. E2E Supervisor", designation="Professor", max_slots=50
        )
        db.add(sup)
        db.commit()
    else:
        sup_user.password_hash = hash_password("Password123!")
        sup_user.must_change_password = False
        sup = db.query(Supervisor).filter(Supervisor.user_id == sup_user.id).first()
        if sup:
            sup.max_slots = 50
        db.commit()

    # Pre-publish a topic for student request test
    unique_suffix = uuid.uuid4().hex[:6]
    test_topic = Topic(
        title=f"Cloud Edge Security Optimization {unique_suffix}",
        normalized_title=f"cloud edge security optimization {unique_suffix}",
        description="Comprehensive analysis of lightweight edge security protocols.",
        domain="Cloud",
        department_id=dept.id,
        session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=sup_user.id,
        status=TopicStatusEnum.AVAILABLE
    )
    db.add(test_topic)
    db.commit()
    db.close()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Mobile viewport: 360px width x 740px height
        context = browser.new_context(
            viewport={"width": 360, "height": 740},
            device_scale_factor=1
        )
        page = context.new_page()

        def nav(url):
            page.goto(url, wait_until="domcontentloaded")

        # Helper logout function
        def do_logout():
            page.evaluate("document.querySelector('form[action=\"/auth/logout\"]').submit()")
            page.wait_for_url(f"{BASE_URL}/auth/login")

        # ====================================================================
        # 1. COORDINATOR APPROVALS PAGE (Light & Dark)
        # ====================================================================
        # Register a pending student first
        student_uid = uuid.uuid4().hex[:5]
        nav(f"{BASE_URL}/auth/register")
        page.fill("#usn", f"1SP23CS{student_uid.upper()}")
        page.fill("#full_name", f"Playwright Student {student_uid}")
        page.select_option("#department_id", index=1)
        page.fill("#email", f"pw_stu_{student_uid}@spms.local")
        page.fill("#phone", "9876543210")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_selector("text=Registration submitted successfully")

        # Coordinator login
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "admin")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        # View Approvals
        nav(f"{BASE_URL}/coordinator/approvals")
        page.wait_for_selector("h3:has-text('Account Approvals')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_approvals_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_approvals_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_approvals_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_approvals_360px_dark.png")

        # Approve the student specifically by locating their card
        student_usn = f"1SP23CS{student_uid.upper()}"
        card = page.locator(".card").filter(has_text=student_usn)
        card.locator("button:has-text('Approve Account')").click()
        page.wait_for_selector("h3:has-text('Account Approvals')")

        # ====================================================================
        # 2. COORDINATOR DEPARTMENTS PAGE (Light & Dark)
        # ====================================================================
        nav(f"{BASE_URL}/coordinator/departments")
        page.wait_for_selector("h3:has-text('Departments')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_departments_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_departments_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_departments_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_departments_360px_dark.png")

        # ====================================================================
        # 3. COORDINATOR SUPERVISORS PAGE (Light & Dark)
        # ====================================================================
        nav(f"{BASE_URL}/coordinator/supervisors")
        page.wait_for_selector("h3:has-text('Supervisors & Slots')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_supervisors_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_supervisors_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_supervisors_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_supervisors_360px_dark.png")

        # Logout coordinator
        do_logout()

        # ====================================================================
        # 4. SUPERVISOR PUBLISH TOPIC (Light & Dark)
        # ====================================================================
        page.fill("#username", "E2E_SUPERVISOR_01")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/topics/publish")
        page.wait_for_selector("h3:has-text('Publish Available Topic')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "topics_publish_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/topics_publish_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "topics_publish_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/topics_publish_360px_dark.png")

        # Logout supervisor
        do_logout()

        # ====================================================================
        # 5. STUDENT BROWSE TOPICS & SUBMIT REQUEST (Light & Dark)
        # ====================================================================
        # Login approved student
        page.fill("#username", f"1SP23CS{student_uid.upper()}")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/topics")
        page.wait_for_selector("h3:has-text('Available Project Topics')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "topics_browse_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/topics_browse_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "topics_browse_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/topics_browse_360px_dark.png")

        # Student requests the pre-published topic
        page.click("button:has-text('Request Topic')")
        page.wait_for_selector("button:has-text('Submit Request')")
        page.click("button:has-text('Submit Request')")
        page.wait_for_url(f"{BASE_URL}/topics/my-requests")
        page.wait_for_selector("h3:has-text('My Topic Applications')")

        # Logout student
        do_logout()

        # ====================================================================
        # 6. COORDINATOR TOPIC REQUESTS & ASSIGNMENT (Light & Dark)
        # ====================================================================
        page.fill("#username", "admin")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/coordinator/topic-requests")
        page.wait_for_selector("h3:has-text('Topic Allocation Requests')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_topic_requests_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_topic_requests_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_topic_requests_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_topic_requests_360px_dark.png")

        # Approve and assign specifically for this student
        req_card = page.locator(".card").filter(has_text=student_usn)
        req_card.locator("button:has-text('Approve & Assign')").click()
        page.wait_for_selector("h3:has-text('Topic Allocation Requests')")

        # Logout
        do_logout()

        browser.close()
        print("[E2E Phase 2] Full flow from registration to supervisor assignment completed successfully!")

if __name__ == "__main__":
    run_phase2_playwright_e2e()
