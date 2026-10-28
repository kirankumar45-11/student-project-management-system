import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))

from app.database import SessionLocal
from app.models.user import User, RoleEnum, AccountStatusEnum, Department, AcademicSession
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import (
    Topic, TopicStatusEnum, TopicAssignment, AssignmentStatusEnum, TopicProposedRoleEnum
)
from app.models.submission import (
    Submission, Feedback, Deadline, ChapterEnum, FeedbackStatusEnum, CHAPTER_DISPLAY_NAMES
)
from app.models.assessment import Assessment
from app.core.security import hash_password
from app.core.datetime_util import utc_now

SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP_DIR = ROOT_DIR / "screenshots" / "desktop"
DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_SUBMISSIONS_DIR = ROOT_DIR / "storage" / "submissions"
STORAGE_SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://127.0.0.1:8000"


def seed_archive_pagination_data(db, dept_id, sess_id, sup_id):
    """Seed >20 archived projects to thoroughly test pagination in Playwright."""
    existing_archived_count = db.query(Topic).filter(Topic.status == TopicStatusEnum.ARCHIVED).count()
    needed = max(0, 25 - existing_archived_count)
    if needed > 0:
        print(f"  [Seeding] Adding {needed} archived test projects for pagination verification...")
        admin = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
        for i in range(needed):
            code = uuid.uuid4().hex[:6]
            arch_top = Topic(
                title=f"Archived Research Project {code.upper()} #{i+1}",
                normalized_title=f"archived research project {code} #{i+1}",
                description=f"Automated benchmark study of distributed consensus protocol #{i+1}.",
                domain="Distributed Systems",
                department_id=dept_id,
                session_id=sess_id,
                proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
                proposed_by_user_id=admin.id if admin else 1,
                status=TopicStatusEnum.ARCHIVED
            )
            db.add(arch_top)
        db.commit()


def run_phase5_playwright_e2e():
    print("[E2E Phase 5] Initializing Full Lifecycle Playwright Verification against http://127.0.0.1:8000...")
    db = SessionLocal()
    uid = uuid.uuid4().hex[:6]

    # Create dummy PDF for submissions
    sample_pdf_path = STORAGE_SUBMISSIONS_DIR / f"report_{uid}.pdf"
    sample_pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Title (SPMS Lifecycle Document) >>\nendobj\ntrailer\n<< >>\n%%EOF\n")

    # 1. Fetch Department & Active Session
    dept = db.query(Department).first()
    if not dept:
        dept = Department(code="CSE", name="Computer Science and Engineering")
        db.add(dept)
        db.commit()

    sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    if not sess:
        sess = AcademicSession(
            name=f"2026-P5-{uid}",
            start_date=utc_now().date(),
            end_date=(utc_now() + timedelta(days=365)).date(),
            is_active=True
        )
        db.add(sess)
        db.commit()

    dept_id = dept.id
    sess_id = sess.id

    # 2. Coordinator user
    coord_user = db.query(User).filter(User.username == "E2E_COORD_P5").first()
    if not coord_user:
        coord_user = User(
            username="E2E_COORD_P5",
            email=f"coord_p5_{uid}@spms.local",
            password_hash=hash_password("Password123!"),
            role=RoleEnum.ADMIN,
            status=AccountStatusEnum.APPROVED,
            must_change_password=False,
            session_version=1
        )
        db.add(coord_user)
        db.commit()
    else:
        coord_user.password_hash = hash_password("Password123!")
        coord_user.must_change_password = False
        db.commit()

    coord_user_id = coord_user.id

    # 3. Supervisor user
    sup_user = db.query(User).filter(User.username == "E2E_SUP_P5").first()
    if not sup_user:
        sup_user = User(
            username="E2E_SUP_P5",
            email=f"sup_p5_{uid}@spms.local",
            password_hash=hash_password("Password123!"),
            role=RoleEnum.SUPERVISOR,
            status=AccountStatusEnum.APPROVED,
            must_change_password=False,
            session_version=1
        )
        db.add(sup_user)
        db.flush()
        sup = Supervisor(
            user_id=sup_user.id,
            department_id=dept_id,
            full_name=f"Dr. Alan Turing ({uid})",
            designation="Professor & Research Lead",
            max_slots=10
        )
        db.add(sup)
        db.commit()
    else:
        sup_user.password_hash = hash_password("Password123!")
        sup_user.must_change_password = False
        sup = db.query(Supervisor).filter(Supervisor.user_id == sup_user.id).first()
        if sup:
            sup.max_slots = 10
        db.commit()

    sup_user_id = sup_user.id
    sup_id = sup.id

    # Seed Deadlines for the active session (all 4 chapters)
    for ch in [ChapterEnum.SYNOPSIS, ChapterEnum.SRS_DESIGN, ChapterEnum.IMPLEMENTATION, ChapterEnum.FINAL_REPORT]:
        dl = db.query(Deadline).filter(Deadline.session_id == sess_id, Deadline.chapter == ch).first()
        if not dl:
            dl = Deadline(
                session_id=sess_id,
                chapter=ch,
                title=f"{CHAPTER_DISPLAY_NAMES[ch]} Submission",
                description=f"Submission milestone for {CHAPTER_DISPLAY_NAMES[ch]}.",
                due_date=utc_now() + timedelta(days=90),
                allow_late=True
            )
            db.add(dl)
    db.commit()

    # Seed >20 archived projects to verify pagination
    seed_archive_pagination_data(db, dept_id, sess_id, sup_id)

    db.close()

    # 4. Student parameters for registration
    stu_usn = f"1SP23CS{uid.upper()[:6]}"
    proj_code = uuid.uuid4().hex[:8]
    topic_title = f"Hyperion Mesh Protocol {proj_code}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Context configured for 1280x720 desktop resolution
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
            color_scheme="light"
        )
        page = context.new_page()

        def nav(url):
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")

        def logout():
            try:
                page.evaluate("() => { const f = document.querySelector('form[action=\"/auth/logout\"]'); if(f) f.submit(); }")
                page.wait_for_url(f"{BASE_URL}/auth/login", timeout=5000)
            except Exception:
                nav(f"{BASE_URL}/auth/login")

        # --------------------------------------------------------------------
        # STEP 1: STUDENT REGISTRATION VIA BROWSER
        # --------------------------------------------------------------------
        print("  [Step 1] Student registers account via /auth/register...")
        nav(f"{BASE_URL}/auth/register")
        page.fill("#usn", stu_usn)
        page.fill("#full_name", f"Ada Lovelace ({uid})")
        page.select_option("#department_id", str(dept_id))
        page.fill("#email", f"stu_p5_{uid}@spms.local")
        page.fill("#phone", "9876543210")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_selector("text=Registration submitted successfully")
        print("  [OK] Student account registration submitted successfully via UI.")

        # --------------------------------------------------------------------
        # STEP 2: COORDINATOR APPROVES STUDENT ACCOUNT
        # --------------------------------------------------------------------
        print("  [Step 2] Coordinator logs in to approve registered student...")
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "E2E_COORD_P5")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        db_app = SessionLocal()
        registered_user = db_app.query(User).filter(User.username == stu_usn).first()
        reg_uid = registered_user.id
        registered_student = registered_user.student_profile
        student_id = registered_student.id
        db_app.close()

        nav(f"{BASE_URL}/coordinator/approvals")
        page.click(f"form[action='/coordinator/approvals/{reg_uid}/approve'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/coordinator/approvals")
        page.wait_for_selector("h3:has-text('Account Approvals')")
        print("  [OK] Coordinator approved registered student via UI.")
        logout()

        # --------------------------------------------------------------------
        # STEP 3: STUDENT PROPOSES TOPIC
        # --------------------------------------------------------------------
        print("  [Step 3] Student logs in to propose project topic...")
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", stu_usn)
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/topics/propose")
        page.wait_for_selector("h3:has-text('Propose Project Topic')")
        page.fill("#title", topic_title)
        page.fill("#domain", "Quantum Networks")
        page.fill("#description", "A resilient fault-tolerant quantum key distribution protocol across multi-tenant fiber meshes.")
        page.select_option("#department_id", str(dept_id))
        page.select_option("#session_id", str(sess_id))
        page.click("form[action='/topics/propose'] button[type=submit]")
        page.wait_for_selector(".alert-success:has-text('submitted successfully')")
        print(f"  [OK] Student proposed topic: '{topic_title}'.")
        logout()

        # --------------------------------------------------------------------
        # STEP 4: COORDINATOR APPROVES TOPIC & ASSIGNS SUPERVISOR
        # --------------------------------------------------------------------
        print("  [Step 4] Coordinator logs in to approve topic & assign supervisor...")
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "E2E_COORD_P5")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        db_app = SessionLocal()
        created_topic = db_app.query(Topic).filter(Topic.title == topic_title).first()
        topic_id = created_topic.id
        db_app.close()

        nav(f"{BASE_URL}/coordinator/topics")
        page.click(f"button[data-bs-target='#assignModal{topic_id}']")
        page.wait_for_selector(f"#supervisor_id{topic_id}")
        page.select_option(f"#supervisor_id{topic_id}", str(sup_id))
        page.click(f"#assignModal{topic_id} button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/coordinator/topics")
        print("  [OK] Coordinator approved topic and assigned supervisor via UI.")
        logout()

        db_app = SessionLocal()
        assign = db_app.query(TopicAssignment).filter(TopicAssignment.topic_id == topic_id).first()
        assign_id = assign.id
        db_app.close()

        # --------------------------------------------------------------------
        # STEP 5: ALL 4 CHAPTER SUBMISSIONS & SUPERVISOR APPROVALS
        # --------------------------------------------------------------------
        print("  [Step 5] Executing sequential submission and supervisor approval for all 4 chapters...")
        chapters = [
            (ChapterEnum.SYNOPSIS, "Synopsis"),
            (ChapterEnum.SRS_DESIGN, "SRS and Design"),
            (ChapterEnum.IMPLEMENTATION, "Implementation"),
            (ChapterEnum.FINAL_REPORT, "Final Report")
        ]

        for ch_enum, ch_name in chapters:
            # Student uploads
            nav(f"{BASE_URL}/auth/login")
            page.fill("#username", stu_usn)
            page.fill("#password", "Password123!")
            page.click("form[action='/auth/login'] button[type=submit]")
            page.wait_for_url(f"{BASE_URL}/dashboard")

            nav(f"{BASE_URL}/submissions")
            page.wait_for_selector(".badge:has-text('ACTIVE PROJECT')")

            if ch_enum == ChapterEnum.FINAL_REPORT:
                page.fill("#github_url", f"https://github.com/adalovelace/quantum-mesh-{uid}")
                page.click("form[action='/submissions/github-url'] button[type=submit]")
                page.wait_for_url(f"{BASE_URL}/submissions")

            page.set_input_files(f"#file_{ch_enum.value}", str(sample_pdf_path))
            page.click(f"form[action='/submissions/{ch_enum.value}/upload'] button[type=submit]")
            page.wait_for_url(f"{BASE_URL}/submissions")
            page.wait_for_selector(".badge:has-text('Under Review')")
            print(f"    - Student submitted {ch_name}.")
            logout()

            # Supervisor approves
            nav(f"{BASE_URL}/auth/login")
            page.fill("#username", "E2E_SUP_P5")
            page.fill("#password", "Password123!")
            page.click("form[action='/auth/login'] button[type=submit]")
            page.wait_for_url(f"{BASE_URL}/dashboard")

            nav(f"{BASE_URL}/submissions/reviews")
            db_sub = SessionLocal()
            sub_record = db_sub.query(Submission).filter(
                Submission.assignment_id == assign_id,
                Submission.chapter == ch_enum
            ).order_by(Submission.version.desc()).first()
            sub_id = sub_record.id
            db_sub.close()

            nav(f"{BASE_URL}/submissions/{sub_id}/review")
            page.wait_for_selector("#statusApprove")
            page.check("#statusApprove")
            page.fill("#comments", f"Comprehensive evaluation verified for {ch_name}. Approved.")
            page.click("button:has-text('Submit Decision')")
            page.wait_for_url(f"{BASE_URL}/submissions/reviews")
            print(f"    - Supervisor approved {ch_name}.")
            logout()

        print("  [OK] All 4 chapters submitted and approved sequentially.")

        # --------------------------------------------------------------------
        # STEP 6: SUPERVISOR ASSESSMENT SCORING (Desktop Screenshot)
        # --------------------------------------------------------------------
        print("  [Step 6] Supervisor logs in to score project assessment...")
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "E2E_SUP_P5")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/assessments/{assign_id}/grade")
        page.wait_for_selector("#assessmentForm")

        # Desktop 1280x720 Screenshot of Grading Form
        grading_screenshot = DESKTOP_DIR / "phase5_01_grading_form.png"
        page.screenshot(path=str(grading_screenshot), full_page=True)
        print(f"  [OK] Captured Desktop Screenshot: {grading_screenshot.name}")

        # Also capture 360px mobile views
        page.set_viewport_size({"width": 360, "height": 740})
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "supervisor_assessment_grading_360px_light.png"), full_page=True)
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "supervisor_assessment_grading_360px_dark.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")

        # Submit Scores
        page.fill("#presentation_score", "28.5")
        page.fill("#report_score", "28.0")
        page.fill("#implementation_score", "38.5")
        page.fill("#supervisor_remarks", "Comprehensive quantum cryptographic implementation with rigorous formal security proofs.")
        page.click("#assessmentForm button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/assessments")
        print("  [OK] Supervisor submitted assessment marks (Total: 95.0 computed server-side).")
        logout()

        # --------------------------------------------------------------------
        # STEP 7: COORDINATOR ASSESSMENT FINALIZATION (Desktop Screenshot)
        # --------------------------------------------------------------------
        print("  [Step 7] Coordinator logs in to finalize project grade...")
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "E2E_COORD_P5")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        db_app = SessionLocal()
        assess = db_app.query(Assessment).filter(Assessment.assignment_id == assign_id).first()
        assess_id = assess.id
        db_app.close()

        nav(f"{BASE_URL}/coordinator/assessments/{assess_id}/finalize")
        page.wait_for_selector("select[name=coordinator_final_grade]")

        # Desktop 1280x720 Screenshot of Finalization Screen
        finalize_screenshot = DESKTOP_DIR / "phase5_02_finalization_screen.png"
        page.screenshot(path=str(finalize_screenshot), full_page=True)
        print(f"  [OK] Captured Desktop Screenshot: {finalize_screenshot.name}")

        # Also capture 360px mobile views
        page.set_viewport_size({"width": 360, "height": 740})
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_assessments_finalize_360px_light.png"), full_page=True)
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_assessments_finalize_360px_dark.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")

        # Select A+ and finalize
        page.select_option("select[name=coordinator_final_grade]", "A+")
        page.click("form[action*='/finalize'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/coordinator/assessments")
        print("  [OK] Coordinator finalized grade as 'A+'. Assignment is COMPLETED, Topic is ARCHIVED.")
        logout()

        # --------------------------------------------------------------------
        # STEP 8: ARCHIVE SEARCH & DETAIL PAGE (Desktop Screenshots)
        # --------------------------------------------------------------------
        print("  [Step 8] Student logs in to view project in public archive...")
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", stu_usn)
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        # Archive Search
        nav(f"{BASE_URL}/archive?q={proj_code}")
        page.wait_for_selector(f"h5:has-text('{topic_title}')")

        # Desktop 1280x720 Screenshot of Archive Search Results
        archive_search_screenshot = DESKTOP_DIR / "phase5_03_archive_search_results.png"
        page.screenshot(path=str(archive_search_screenshot), full_page=True)
        print(f"  [OK] Captured Desktop Screenshot: {archive_search_screenshot.name}")

        # Also capture 360px mobile views
        page.set_viewport_size({"width": 360, "height": 740})
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "archive_search_360px_light.png"), full_page=True)
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "archive_search_360px_dark.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")

        # Strict Privacy Boundary Verification on Archive Card
        card_content = page.locator(".card").filter(has_text=topic_title).inner_text()
        assert stu_usn not in card_content, "SECURITY VIOLATION: Student USN exposed in project archive card!"
        assert "9876543210" not in card_content, "SECURITY VIOLATION: Student phone exposed in project archive card!"
        assert f"stu_p5_{uid}@spms.local" not in card_content, "SECURITY VIOLATION: Student email exposed in project archive card!"
        print("  [OK] Privacy Boundary Verified: Student USN, phone, and email are completely omitted from archive cards.")

        # Archive Detail Page
        nav(f"{BASE_URL}/archive/{topic_id}")
        page.wait_for_selector(f"h3:has-text('{topic_title}')")

        # Desktop 1280x720 Screenshot of Archive Detail Page
        archive_detail_screenshot = DESKTOP_DIR / "phase5_04_archive_detail_page.png"
        page.screenshot(path=str(archive_detail_screenshot), full_page=True)
        print(f"  [OK] Captured Desktop Screenshot: {archive_detail_screenshot.name}")

        # Also capture 360px mobile views
        page.set_viewport_size({"width": 360, "height": 740})
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "archive_detail_360px_light.png"), full_page=True)
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "archive_detail_360px_dark.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")

        # Strict Privacy Boundary Verification on Archive Detail Page
        detail_container = page.locator("main").inner_text()
        assert stu_usn not in detail_container, "SECURITY VIOLATION: Student USN exposed in archive detail page!"
        assert "9876543210" not in detail_container, "SECURITY VIOLATION: Student phone exposed in archive detail page!"
        assert f"stu_p5_{uid}@spms.local" not in detail_container, "SECURITY VIOLATION: Student email exposed in archive detail page!"
        print("  [OK] Privacy Boundary Verified: Student PII is completely omitted from archive detail page.")

        # Authenticated Download Check
        download_url = f"{BASE_URL}/archive/{topic_id}/download"
        download_res = page.request.get(download_url)
        assert download_res.status == 200, f"Expected 200 OK from archive download, got {download_res.status}"
        assert len(download_res.body()) > 0
        print(f"  [OK] Verified archived report download endpoint returned HTTP 200 ({len(download_res.body())} bytes).")
        logout()

        # --------------------------------------------------------------------
        # STEP 9: ARCHIVED TOPIC FEEDS DUPLICATE DETECTION
        # --------------------------------------------------------------------
        print("  [Step 9] Verifying archived topic feeds duplicate detector...")
        # Register a new student without assignment
        dup_stu_usn = f"1SP23CS{uuid.uuid4().hex[:6].upper()}"
        nav(f"{BASE_URL}/auth/register")
        page.fill("#usn", dup_stu_usn)
        page.fill("#full_name", "Duplicate Test Student")
        page.select_option("#department_id", str(dept_id))
        page.fill("#email", f"dup_{uuid.uuid4().hex[:6]}@spms.local")
        page.fill("#phone", "9876543222")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_selector("text=Registration submitted successfully")

        # Coordinator approves dup student
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "E2E_COORD_P5")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")
        db_app = SessionLocal()
        dup_u = db_app.query(User).filter(User.username == dup_stu_usn).first()
        dup_uid = dup_u.id
        db_app.close()
        nav(f"{BASE_URL}/coordinator/approvals")
        page.click(f"form[action='/coordinator/approvals/{dup_uid}/approve'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/coordinator/approvals")
        logout()

        # Dup student attempts to propose conflicting title matching archived project
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", dup_stu_usn)
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/topics/propose")
        page.wait_for_selector("h3:has-text('Propose Project Topic')")
        page.fill("#title", topic_title)  # Exact match with archived project
        page.fill("#domain", "Quantum Networks")
        page.fill("#description", "Attempting to re-propose already completed and archived quantum cryptographic protocol.")
        page.select_option("#department_id", str(dept_id))
        page.select_option("#session_id", str(sess_id))
        page.click("form[action='/topics/propose'] button[type=submit]")

        page.wait_for_selector(".alert-danger:has-text('Duplicate topic detected')")
        alert_text = page.locator(".alert-danger").inner_text()
        assert "100.0% similarity" in alert_text or "% similarity" in alert_text
        assert topic_title in alert_text
        print(f"  [OK] Duplicate detector successfully flagged archived topic conflict: '{alert_text.splitlines()[0]}'.")
        logout()

        # --------------------------------------------------------------------
        # STEP 10: ARCHIVE PAGINATION CHECK (>20 SEEDED PROJECTS)
        # --------------------------------------------------------------------
        print("  [Step 10] Checking archive pagination with >20 seeded projects...")
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", stu_usn)
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/archive")
        page.wait_for_selector(".pagination")
        # Check page 2 link is present and click it
        page.click("a.page-link:has-text('2')")
        page.wait_for_url(f"{BASE_URL}/archive?page=2*")
        page.wait_for_selector(".card")
        print("  [OK] Archive pagination successfully verified: navigated to Page 2 of archived projects.")

        logout()
        browser.close()

    print("=" * 64)
    print("[E2E Phase 5] Full lifecycle Playwright tests completed successfully with all desktop screenshots captured!")
    print("=" * 64)


if __name__ == "__main__":
    run_phase5_playwright_e2e()
