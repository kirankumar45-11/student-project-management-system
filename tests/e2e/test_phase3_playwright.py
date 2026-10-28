import os
import io
import time
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.database import SessionLocal
from app.models.user import User, RoleEnum, AccountStatusEnum, Department, AcademicSession
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import Topic, TopicAssignment, TopicStatusEnum, TopicProposedRoleEnum, AssignmentStatusEnum
from app.models.communication import Message, ForumThread, ForumReply
from app.models.guideline import Guideline, Notification
from app.core.security import hash_password, generate_resubmit_token

BASE_URL = os.getenv("TEST_SERVER_URL", "http://127.0.0.1:8000")
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

def run_phase3_playwright_e2e():
    print(f"[E2E Phase 3 & Follow-ups] Starting Playwright 360px visual capture against {BASE_URL}...")

    db = SessionLocal()
    # 1. Setup Admin Coordinator
    coord = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
    if not coord:
        coord = User(
            username="admin", email="admin@spms.local",
            password_hash=hash_password("Password123!"), role=RoleEnum.ADMIN,
            status=AccountStatusEnum.APPROVED, must_change_password=False, session_version=1
        )
        db.add(coord)
        db.commit()
    else:
        coord.password_hash = hash_password("Password123!")
        coord.must_change_password = False
        db.commit()

    dept = db.query(Department).first()
    sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # 2. Setup Supervisor
    sup_user = db.query(User).filter(User.username == "E2E_P3_SUPERVISOR").first()
    if not sup_user:
        sup_user = User(
            username="E2E_P3_SUPERVISOR", email="e2e_p3_supervisor@spms.local",
            password_hash=hash_password("Password123!"), role=RoleEnum.SUPERVISOR,
            status=AccountStatusEnum.APPROVED, must_change_password=False, session_version=1
        )
        db.add(sup_user)
        db.flush()
        sup = Supervisor(
            user_id=sup_user.id, department_id=dept.id,
            full_name="Dr. P3 Supervisor", designation="Professor", max_slots=50
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
        sup_user.must_change_password = False
        db.commit()
        sup = db.query(Supervisor).filter(Supervisor.user_id == sup_user.id).first()

    # 3. Setup Approved Student with Active Assignment for Chat
    uid = uuid.uuid4().hex[:5]
    stu_user = User(
        username=f"E2E_STU_{uid}", email=f"e2e_stu_{uid}@spms.local",
        password_hash=hash_password("Password123!"), role=RoleEnum.STUDENT,
        status=AccountStatusEnum.APPROVED, must_change_password=False, session_version=1
    )
    db.add(stu_user)
    db.flush()
    stu = Student(
        user_id=stu_user.id, department_id=dept.id, session_id=sess.id,
        usn=f"1SP23CS{uid.upper()}", full_name=f"E2E Chat Student {uid}", semester=8,
        academic_year=sess.name, phone="9876543210"
    )
    db.add(stu)
    db.flush()

    top = Topic(
        title=f"Autonomous Drone Fleet Coordination {uid}",
        normalized_title=f"autonomous drone fleet coordination {uid}",
        description="Multi-agent decentralized navigation.",
        domain="Robotics", department_id=dept.id, session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=sup_user.id, status=TopicStatusEnum.ASSIGNED
    )
    db.add(top)
    db.flush()

    assign = TopicAssignment(
        topic_id=top.id, student_id=stu.id, supervisor_id=sup.id, session_id=sess.id, status=AssignmentStatusEnum.ACTIVE
    )
    db.add(assign)
    db.flush()

    # Seed initial message in assignment
    msg1 = Message(
        assignment_id=assign.id, sender_id=sup_user.id, recipient_id=stu_user.id,
        content="Welcome to the autonomous drone fleet project! Let's schedule our initial sync."
    )
    db.add(msg1)

    # 4. Seed Proposed Student Topic for Coordinator Review
    proposed_stu_user = User(
        username=f"PROP_STU_{uid}", email=f"prop_stu_{uid}@spms.local",
        password_hash=hash_password("Password123!"), role=RoleEnum.STUDENT,
        status=AccountStatusEnum.APPROVED, must_change_password=False, session_version=1
    )
    db.add(proposed_stu_user)
    db.flush()
    proposed_stu = Student(
        user_id=proposed_stu_user.id, department_id=dept.id, session_id=sess.id,
        usn=f"1SP23CS_P{uid.upper()}", full_name="Proposer Student", semester=8,
        academic_year=sess.name, phone="9876543211"
    )
    db.add(proposed_stu)
    db.flush()

    prop_top = Topic(
        title=f"Quantum Cryptography Protocols {uid}",
        normalized_title=f"quantum cryptography protocols {uid}",
        description="Key distribution security under quantum computing.",
        domain="Security", department_id=dept.id, session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.STUDENT,
        proposed_by_user_id=proposed_stu_user.id, status=TopicStatusEnum.PROPOSED
    )
    db.add(prop_top)

    # 5. Seed Rejected Student for Resubmit Screen
    rej_user = User(
        username=f"REJ_STU_{uid}", email=f"rej_stu_{uid}@spms.local",
        password_hash=hash_password("Password123!"), role=RoleEnum.STUDENT,
        status=AccountStatusEnum.REJECTED, remarks="Invalid government ID and USN mismatch.", session_version=1
    )
    db.add(rej_user)
    db.flush()
    rej_stu = Student(
        user_id=rej_user.id, department_id=dept.id, session_id=sess.id,
        usn=f"1SP23CS_R{uid.upper()}", full_name="Rejected Student", semester=8,
        academic_year=sess.name, phone="9876543212"
    )
    db.add(rej_stu)
    db.commit()

    resubmit_token = generate_resubmit_token(rej_user.id)

    # 6. Seed Forum Thread & Replies
    thread = ForumThread(
        department_id=dept.id, user_id=sup_user.id,
        title="Project Synopsis Submission Guidelines - Spring 2026",
        content="Please adhere to IEEE formatting for all synopsis submissions. Font size 10pt Times New Roman.",
        is_pinned=True
    )
    db.add(thread)
    db.flush()
    reply = ForumReply(
        thread_id=thread.id, user_id=stu_user.id,
        content="Thank you Dr. Supervisor, does this also apply to the SRS and Design document?"
    )
    db.add(reply)

    # 7. Seed Guideline
    sample_pdf_path = Path("storage/guidelines")
    sample_pdf_path.mkdir(parents=True, exist_ok=True)
    sample_pdf_file = sample_pdf_path / "manual_sample.pdf"
    if not sample_pdf_file.exists():
        sample_pdf_file.write_bytes(b"%PDF-1.4\n1 0 obj\n<<\n>>\nendobj\ntrailer\n<<\n>>\n%%EOF\n")

    guide = Guideline(
        coordinator_id=coord.id,
        title="SPMS Project Guidelines & Assessment Criteria 2026",
        description="Official manual covering Synopsis, SRS and Design, Implementation, and Final Report rubrics.",
        file_path="storage/guidelines/manual_sample.pdf",
        original_filename="SPMS_Guidelines_2026.pdf",
        file_size=1048576
    )
    db.add(guide)

    # 8. Seed Notifications for student
    assign_id = assign.id
    thread_id = thread.id
    guide_id = guide.id
    top_title = top.title
    sup_full_name = sup.full_name

    n1 = Notification(
        user_id=stu_user.id, title="Topic Assigned Successfully",
        message=f"You have been assigned topic '{top_title}' with supervisor {sup_full_name}.",
        link=f"/messaging/{assign_id}"
    )
    n2 = Notification(
        user_id=stu_user.id, title="New Guideline Published",
        message="Coordinator published: SPMS Project Guidelines & Assessment Criteria 2026",
        link="/guidelines"
    )
    db.add_all([n1, n2])
    db.commit()
    db.close()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 360, "height": 740},
            device_scale_factor=1
        )
        page = context.new_page()

        def nav(url):
            page.goto(url, wait_until="domcontentloaded")

        def do_logout():
            page.evaluate("document.querySelector('form[action=\"/auth/logout\"]').submit()")
            page.wait_for_url(f"{BASE_URL}/auth/login")

        # --------------------------------------------------------------------
        # 1. ACADEMIC SESSIONS MANAGEMENT (/coordinator/sessions)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "admin")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/coordinator/sessions")
        page.wait_for_selector("h3:has-text('Academic Sessions')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_sessions_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_sessions_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_sessions_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_sessions_360px_dark.png")

        # --------------------------------------------------------------------
        # 2. COORDINATOR APPROVE/REJECT PROPOSED TOPICS (/coordinator/topics)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/coordinator/topics")
        page.wait_for_selector("h3:has-text('Topic Approvals')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_topics_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_topics_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_topics_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_topics_360px_dark.png")

        # --------------------------------------------------------------------
        # 3. ACCOUNT REJECTION WITH REMARKS MODAL (/coordinator/approvals)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/coordinator/approvals")
        page.wait_for_selector("h3:has-text('Account Approvals')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_account_reject_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_account_reject_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "coordinator_account_reject_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/coordinator_account_reject_360px_dark.png")

        # Logout coordinator
        do_logout()

        # --------------------------------------------------------------------
        # 4. REJECTED STUDENT RESUBMISSION (/register/resubmit)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/register/resubmit?token={resubmit_token}")
        page.wait_for_selector("text=Update & Resubmit Registration")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "rejected_student_resubmission_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/rejected_student_resubmission_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "rejected_student_resubmission_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/rejected_student_resubmission_360px_dark.png")

        # --------------------------------------------------------------------
        # 5. STUDENT TOPIC PROPOSAL & DUPLICATE REJECTION (/topics/propose)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", f"PROP_STU_{uid}")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/topics/propose")
        page.wait_for_selector("h3:has-text('Propose Project Topic')")

        # Capture Proposal Form
        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "topics_propose_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/topics_propose_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "topics_propose_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/topics_propose_360px_dark.png")

        # Propose duplicate of existing topic
        page.fill("#title", f"Autonomous Drone Fleet Coordination {uid}")
        page.fill("#domain", "Robotics")
        page.fill("#description", "Identical duplicate proposal to test detector.")
        page.select_option("#department_id", index=0)
        page.select_option("#session_id", index=0)
        page.click("form[action='/topics/propose'] button[type=submit]")

        # Wait for duplicate error message banner
        page.wait_for_selector(".alert-danger:has-text('Duplicate topic detected')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "duplicate_rejection_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/duplicate_rejection_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "duplicate_rejection_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/duplicate_rejection_360px_dark.png")

        do_logout()

        # --------------------------------------------------------------------
        # 6. MESSAGING CHAT THREAD (Light & Dark)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", f"E2E_STU_{uid}")
        page.fill("#password", "Password123!")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        nav(f"{BASE_URL}/messaging/{assign_id}")
        page.wait_for_selector("#chatBox")

        # Send a reply message in chat
        page.fill("#messageInput", "Hello Dr. Supervisor, I have finalized our project scope and will submit the Synopsis shortly.")
        page.click("#sendBtn")
        page.wait_for_selector("text=finalized our project scope")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "messaging_chat_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/messaging_chat_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "messaging_chat_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/messaging_chat_360px_dark.png")

        # --------------------------------------------------------------------
        # 7. DEPARTMENT FORUM (Index & Thread View)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/forum")
        page.wait_for_selector("h3:has-text('Department Forum')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "forum_index_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/forum_index_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "forum_index_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/forum_index_360px_dark.png")

        nav(f"{BASE_URL}/forum/{thread_id}")
        page.wait_for_selector("h4:has-text('Project Synopsis Submission Guidelines')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "forum_view_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/forum_view_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "forum_view_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/forum_view_360px_dark.png")

        # --------------------------------------------------------------------
        # 8. PROJECT GUIDELINES LISTING & DOWNLOAD
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/guidelines")
        page.wait_for_selector("h3:has-text('Project Guidelines')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "guidelines_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/guidelines_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "guidelines_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/guidelines_360px_dark.png")

        # --------------------------------------------------------------------
        # 9. FULL NOTIFICATIONS PAGE
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/notifications")
        page.wait_for_selector("h3:has-text('Notifications')")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'light')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "notifications_360px_light.png"), full_page=True)
        print("  [OK] Captured screenshots/notifications_360px_light.png")

        page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        page.screenshot(path=str(SCREENSHOTS_DIR / "notifications_360px_dark.png"), full_page=True)
        print("  [OK] Captured screenshots/notifications_360px_dark.png")

        do_logout()
        browser.close()

    print("[E2E Phase 3 & Follow-ups] Completed all Playwright visual captures successfully!")
