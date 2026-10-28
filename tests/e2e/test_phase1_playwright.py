import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("TEST_SERVER_URL", "http://127.0.0.1:8000")
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

def run_playwright_e2e():
    print(f"[E2E] Starting Playwright mobile 360px visual capture against {BASE_URL}...")
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

        # 1. Login Page (Light & Dark)
        nav(f"{BASE_URL}/auth/login")
        page.wait_for_selector("text=Sign In to SPMS")
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "login_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/login_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "login_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/login_360px_dark.png")

        # 2. Registration Page (Light & Dark)
        nav(f"{BASE_URL}/auth/register")
        page.wait_for_selector("text=Student Registration")
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "register_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/register_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "register_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/register_360px_dark.png")

        # 3. Resubmit Registration Page (Light & Dark)
        from app.core.security import generate_resubmit_token, hash_password
        from app.database import SessionLocal
        from app.models.user import User, AccountStatusEnum, RoleEnum, Department, AcademicSession
        from app.models.student import Student

        db = SessionLocal()
        rej_user = db.query(User).filter(User.status == AccountStatusEnum.REJECTED).first()
        if not rej_user:
            dept = db.query(Department).first()
            sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
            rej_user = User(
                username="E2E_REJ_01",
                email="e2e_rej_01@spms.local",
                password_hash=hash_password("Password123!"),
                role=RoleEnum.STUDENT,
                status=AccountStatusEnum.REJECTED,
                remarks="Invalid department selection and missing phone."
            )
            db.add(rej_user)
            db.flush()
            s_rej = Student(
                user_id=rej_user.id,
                department_id=dept.id,
                session_id=sess.id,
                usn="1SP23CS998",
                full_name="Rejected E2E Student",
                semester=6,
                academic_year=sess.name,
                phone="9000000000"
            )
            db.add(s_rej)
            db.commit()

        token = generate_resubmit_token(rej_user.id)
        db.close()

        nav(f"{BASE_URL}/register/resubmit?token={token}")
        page.wait_for_selector("text=Update & Resubmit Registration")
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "resubmit_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/resubmit_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "resubmit_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/resubmit_360px_dark.png")

        # 4. Student Dashboard (Light & Dark)
        db = SessionLocal()
        e2e_stu = db.query(User).filter(User.username == "E2E_STUDENT_01").first()
        if not e2e_stu:
            dept = db.query(Department).first()
            sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
            e2e_stu = User(
                username="E2E_STUDENT_01",
                email="e2e_student_01@spms.local",
                password_hash=hash_password("Password123!"),
                role=RoleEnum.STUDENT,
                status=AccountStatusEnum.APPROVED,
                must_change_password=False,
                session_version=1
            )
            db.add(e2e_stu)
            db.flush()
            s = Student(
                user_id=e2e_stu.id,
                department_id=dept.id,
                session_id=sess.id,
                usn="1SP23CS001",
                full_name="E2E Test Student",
                semester=6,
                academic_year=sess.name,
                phone="9876543210"
            )
            db.add(s)
            db.commit()
        else:
            e2e_stu.password_hash = hash_password("Password123!")
            e2e_stu.status = AccountStatusEnum.APPROVED
            e2e_stu.must_change_password = False
            db.commit()
        db.close()

        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "E2E_STUDENT_01")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")
        page.wait_for_selector("text=Project Milestone Progress")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "student_dashboard_360px_light.png"), full_page=True)
        page.screenshot(path=str(SCREENSHOTS_DIR / "dashboard_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/dashboard_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "student_dashboard_360px_dark.png"), full_page=True)
        page.screenshot(path=str(SCREENSHOTS_DIR / "dashboard_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/dashboard_360px_dark.png")

        # 5. Student Profile Page (Light & Dark)
        nav(f"{BASE_URL}/profile/student")
        page.wait_for_selector("text=Student Profile")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "profile_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/profile_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "profile_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/profile_360px_dark.png")

        # 6. Change Password Page (Light & Dark)
        nav(f"{BASE_URL}/auth/change-password")
        page.wait_for_selector("text=Update Temporary Password")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "change_password_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/change_password_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "change_password_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/change_password_360px_dark.png")

        browser.close()
        print("[E2E] All 360px mobile screenshots captured successfully!")

if __name__ == "__main__":
    run_playwright_e2e()
