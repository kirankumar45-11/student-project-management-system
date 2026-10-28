import os
import sys
import uuid
import io
import zipfile
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
    Submission, Feedback, Deadline, ChapterEnum, FeedbackStatusEnum
)
from app.core.security import hash_password
from app.core.datetime_util import utc_now

SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_SUBMISSIONS_DIR = ROOT_DIR / "storage" / "submissions"
STORAGE_SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://127.0.0.1:8000"


def run_phase4_playwright_e2e():
    print("[E2E Phase 4] Initializing Playwright tests for submissions & pipeline flow against http://127.0.0.1:8000...")
    db = SessionLocal()
    uid = uuid.uuid4().hex[:6]

    # Create dummy PDF for upload test
    sample_pdf_path = STORAGE_SUBMISSIONS_DIR / f"sample_{uid}.pdf"
    sample_pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Title (SPMS Project Document) >>\nendobj\ntrailer\n<< >>\n%%EOF\n")

    # Create dummy real .docx for upload test
    sample_docx_path = STORAGE_SUBMISSIONS_DIR / f"sample_{uid}.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>')
        z.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body></w:body></w:document>')
    sample_docx_path.write_bytes(buf.getvalue())

    # 1. Fetch or create Department and Session
    dept = db.query(Department).first()
    if not dept:
        dept = Department(code="CSE", name="Computer Science and Engineering")
        db.add(dept)
        db.flush()

    sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    if not sess:
        sess = AcademicSession(
            name=f"2026-{uid}",
            start_date=utc_now().date(),
            end_date=(utc_now() + timedelta(days=365)).date(),
            is_active=True
        )
        db.add(sess)
        db.flush()

    # 2. Coordinator user
    coord_user = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
    coord_username = coord_user.username if coord_user else "admin"

    # 3. Create Supervisor
    sup_user = User(
        username=f"SUP_P4_{uid}",
        email=f"sup_p4_{uid}@spms.local",
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
        department_id=dept.id,
        full_name=f"Dr. Alan Turing {uid.upper()}",
        designation="Professor & Research Chair",
        max_slots=25
    )
    db.add(sup)
    db.flush()

    # 4. Create Student with ACTIVE Assignment
    stu_user = User(
        username=f"STU_P4_{uid}",
        email=f"stu_p4_{uid}@spms.local",
        password_hash=hash_password("Password123!"),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    db.add(stu_user)
    db.flush()
    stu = Student(
        user_id=stu_user.id,
        department_id=dept.id,
        session_id=sess.id,
        usn=f"1SP23CS{uid.upper()[:6]}4",
        full_name=f"Katherine Johnson {uid.upper()}",
        semester=8,
        academic_year=sess.name,
        phone="9876543219"
    )
    db.add(stu)
    db.flush()

    top = Topic(
        title=f"Decentralized Swarm Robotics Navigation {uid.upper()}",
        normalized_title=f"decentralized swarm robotics navigation {uid}",
        description="Autonomous distributed mapping and target tracking in GPS-denied environments.",
        domain="Robotics & AI",
        department_id=dept.id,
        session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=sup_user.id,
        status=TopicStatusEnum.ASSIGNED
    )
    db.add(top)
    db.flush()

    assign = TopicAssignment(
        topic_id=top.id,
        student_id=stu.id,
        supervisor_id=sup.id,
        session_id=sess.id,
        status=AssignmentStatusEnum.ACTIVE,
        github_url="https://github.com/katherine/swarm-robotics",
        github_url_locked=False
    )
    db.add(assign)
    db.flush()

    # 5. Seed Deadlines for the 4 chapters (clear any pre-existing for this session)
    db.query(Deadline).filter(Deadline.session_id == sess.id).delete()
    db.flush()

    dl1 = Deadline(
        session_id=sess.id, chapter=ChapterEnum.SYNOPSIS,
        title="Project Synopsis Milestone", description="Problem formulation and objectives.",
        due_date=utc_now() + timedelta(days=14), allow_late=True
    )
    dl2 = Deadline(
        session_id=sess.id, chapter=ChapterEnum.SRS_DESIGN,
        title="Software Requirements & Architecture", description="IEEE 830 compliant SRS and UML diagrams.",
        due_date=utc_now() + timedelta(days=45), allow_late=False
    )
    dl3 = Deadline(
        session_id=sess.id, chapter=ChapterEnum.IMPLEMENTATION,
        title="Prototype Implementation & Testing", description="Working software, unit tests, and benchmarks.",
        due_date=utc_now() + timedelta(days=90), allow_late=True
    )
    dl4 = Deadline(
        session_id=sess.id, chapter=ChapterEnum.FINAL_REPORT,
        title="Final Project Dissertation", description="Comprehensive thesis report and code repository.",
        due_date=utc_now() + timedelta(days=120), allow_late=False
    )
    db.add_all([dl1, dl2, dl3, dl4])
    db.commit()

    # Save IDs to plain variables before db.close() to avoid DetachedInstanceError
    assign_id = assign.id
    sup_id = sup.id
    stu_username = stu_user.username
    sup_username = sup_user.username
    db.close()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 360, "height": 740},
            device_scale_factor=1
        )
        page = context.new_page()

        def nav(url):
            page.goto(url, wait_until="domcontentloaded", timeout=15000)

        def do_logout():
            try:
                page.evaluate("() => { const f = document.querySelector('form[action=\"/auth/logout\"]'); if(f) f.submit(); }")
                page.wait_for_url(f"{BASE_URL}/auth/login", timeout=5000)
            except Exception:
                nav(f"{BASE_URL}/auth/login")

        # --------------------------------------------------------------------
        # 1. COORDINATOR DEADLINES MANAGEMENT (360px Light & Dark)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "admin")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/coordinator/deadlines")
        page.wait_for_selector("h3:has-text('Chapter Deadlines')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_deadlines_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_deadlines_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_deadlines_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_deadlines_360px_dark.png")

        do_logout()

        # --------------------------------------------------------------------
        # 2. STUDENT PIPELINE STEPPER & INITIAL SUBMISSIONS VIEW (Light & Dark)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", stu_username)
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/submissions")
        page.wait_for_selector("h5:has-text('Student Pipeline Stepper')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "submissions_pipeline_stepper_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/submissions_pipeline_stepper_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "submissions_pipeline_stepper_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/submissions_pipeline_stepper_360px_dark.png")

        # 3. Test Upload Rejection (Attempt to upload .exe file)
        bad_exe_path = STORAGE_SUBMISSIONS_DIR / f"malicious_{uid}.exe"
        bad_exe_path.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00")

        page.set_input_files("#file_SYNOPSIS", str(bad_exe_path))
        page.click("form[action='/submissions/SYNOPSIS/upload'] button[type=submit]")
        page.wait_for_selector("#uploadErrorAlert:has-text('Only PDF, DOC, and DOCX files are permitted')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "submission_upload_rejected_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/submission_upload_rejected_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "submission_upload_rejected_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/submission_upload_rejected_360px_dark.png")

        # 4. Student uploads valid Synopsis (v1)
        page.set_input_files("#file_SYNOPSIS", str(sample_pdf_path))
        page.click("form[action='/submissions/SYNOPSIS/upload'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/submissions")
        page.wait_for_selector(".badge:has-text('Under Review')")
        print("  [OK] Student successfully uploaded Synopsis (v1) document.")

        do_logout()

        # --------------------------------------------------------------------
        # 4. SUPERVISOR REVIEWS LIST & DETAIL (Light & Dark)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", sup_username)
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/submissions/reviews")
        page.wait_for_selector("h3:has-text('Review Chapter Submissions')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "supervisor_reviews_list_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/supervisor_reviews_list_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "supervisor_reviews_list_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/supervisor_reviews_list_360px_dark.png")

        # Click Review & Grade button
        page.click("a:has-text('Review & Grade')")
        page.wait_for_selector("h5:has-text('Supervisor Evaluation')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "supervisor_review_detail_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/supervisor_review_detail_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "supervisor_review_detail_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/supervisor_review_detail_360px_dark.png")

        # 5. Supervisor requests revision (NEEDS_REVISION)
        page.check("#statusRevision")
        page.fill("#comments", "Literature review is missing recent benchmark comparisons in multi-robot exploration. Please revise and resubmit.")
        page.click("button:has-text('Submit Decision')")
        page.wait_for_url(f"{BASE_URL}/submissions/reviews")
        print("  [OK] Supervisor submitted NEEDS_REVISION feedback.")

        do_logout()

        # --------------------------------------------------------------------
        # 6. STUDENT RESUBMISSION & VERSION HISTORY (Light & Dark)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", stu_username)
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/submissions")
        page.wait_for_selector(".badge:has-text('Revision Requested')")

        # Student uploads revised Synopsis (v2) as a real .docx file
        page.set_input_files("#file_SYNOPSIS", str(sample_docx_path))
        page.click("form[action='/submissions/SYNOPSIS/upload'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/submissions")
        page.wait_for_selector("text=Version History (2 versions)")
        print("  [OK] Student successfully uploaded revised Synopsis (v2) as a real .docx file.")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "submissions_resubmission_history_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/submissions_resubmission_history_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "submissions_resubmission_history_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/submissions_resubmission_history_360px_dark.png")

        do_logout()

        # --------------------------------------------------------------------
        # 7. SUPERVISOR APPROVES & FINAL MILESTONES COMPLETION
        # --------------------------------------------------------------------
        # In the background DB, record approvals for the remaining milestones
        # to demonstrate the completed pipeline stepper and GitHub locking.
        db2 = SessionLocal()
        # Find v2 and approve it
        synopsis_v2 = db2.query(Submission).filter(
            Submission.assignment_id == assign_id,
            Submission.chapter == ChapterEnum.SYNOPSIS,
            Submission.version == 2
        ).first()
        if synopsis_v2:
            fb2 = Feedback(
                submission_id=synopsis_v2.id,
                supervisor_id=sup_id,
                status=FeedbackStatusEnum.APPROVED,
                comments="Revisions fully address the literature survey feedback. Approved!"
            )
            db2.add(fb2)

        # Seed approved SRS & Implementation
        srs_sub = Submission(
            assignment_id=assign_id, chapter=ChapterEnum.SRS_DESIGN, version=1,
            file_path="storage/submissions/srs_sample.pdf", original_filename="SRS_Design_Spec.pdf",
            file_size=2048, is_late=False
        )
        db2.add(srs_sub)
        db2.flush()
        db2.add(Feedback(submission_id=srs_sub.id, supervisor_id=sup_id, status=FeedbackStatusEnum.APPROVED, comments="Software architecture meets all IEEE specifications."))

        impl_sub = Submission(
            assignment_id=assign_id, chapter=ChapterEnum.IMPLEMENTATION, version=1,
            file_path="storage/submissions/impl_sample.pdf", original_filename="Implementation_Report.pdf",
            file_size=4096, is_late=False
        )
        db2.add(impl_sub)
        db2.flush()
        db2.add(Feedback(submission_id=impl_sub.id, supervisor_id=sup_id, status=FeedbackStatusEnum.APPROVED, comments="Code implementation and testing verified."))

        final_sub = Submission(
            assignment_id=assign_id, chapter=ChapterEnum.FINAL_REPORT, version=1,
            file_path="storage/submissions/final_sample.pdf", original_filename="Final_Thesis_Report.pdf",
            file_size=8192, is_late=False
        )
        db2.add(final_sub)
        db2.flush()
        db2.add(Feedback(submission_id=final_sub.id, supervisor_id=sup_id, status=FeedbackStatusEnum.APPROVED, comments="Outstanding dissertation work. Approved with distinction."))

        # Lock assignment GitHub URL upon Final Report approval
        assign_record = db2.query(TopicAssignment).filter(TopicAssignment.id == assign_id).first()
        assign_record.github_url_locked = True
        assign_record.completed_at = utc_now()
        db2.commit()
        db2.close()

        # --------------------------------------------------------------------
        # 8. STUDENT COMPLETED PIPELINE & LOCKED GITHUB URL (Light & Dark)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", stu_username)
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/submissions")
        page.wait_for_selector(".badge:has-text('100% Completed')")
        page.wait_for_selector("text=Locked (Final Report Approved)")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "submissions_completed_locked_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/submissions_completed_locked_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "submissions_completed_locked_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/submissions_completed_locked_360px_dark.png")

        do_logout()
        browser.close()

    print("[E2E Phase 4] Successfully completed all Playwright flows and 360px mobile screenshot captures!")


if __name__ == "__main__":
    run_phase4_playwright_e2e()
