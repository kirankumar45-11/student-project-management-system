import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))

from app.database import SessionLocal
from app.models.user import User, Department, AcademicSession, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import (
    Topic, TopicAssignment, TopicRequest, TopicStatusEnum, TopicProposedRoleEnum,
    AssignmentStatusEnum, TopicRequestStatusEnum
)
from app.models.submission import (
    Submission, Feedback, Deadline, ChapterEnum, FeedbackStatusEnum
)
from app.models.communication import Message, ForumThread, ForumReply
from app.models.guideline import Guideline, Notification
from app.core.security import hash_password
from app.core.datetime_util import utc_now

DESKTOP_DIR = ROOT_DIR / "screenshots" / "desktop"
DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
BASE_URL = "http://127.0.0.1:8000"


def setup_desktop_test_data():
    db = SessionLocal()
    uid = uuid.uuid4().hex[:6]

    # Department & Session
    dept = db.query(Department).first()
    if not dept:
        dept = Department(code="CSE", name="Computer Science and Engineering")
        db.add(dept)
        db.commit()

    sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    if not sess:
        sess = AcademicSession(
            name=f"2026-DESK-{uid}",
            start_date=utc_now().date(),
            end_date=(utc_now() + timedelta(days=365)).date(),
            is_active=True
        )
        db.add(sess)
        db.commit()

    dept_id = dept.id
    sess_id = sess.id

    # 1. Coordinator user
    coord_user = db.query(User).filter(User.username == "desk_coord").first()
    if not coord_user:
        coord_user = User(
            username="desk_coord",
            email=f"desk_coord_{uid}@test.local",
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

    # 2. Supervisor user
    sup_user = db.query(User).filter(User.username == "desk_sup").first()
    if not sup_user:
        sup_user = User(
            username="desk_sup",
            email=f"desk_sup_{uid}@test.local",
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
            full_name="Prof. David Hilbert",
            designation="Professor & Research Chair",
            max_slots=6
        )
        db.add(sup)
        db.commit()
    else:
        sup_user.password_hash = hash_password("Password123!")
        sup_user.must_change_password = False
        sup = db.query(Supervisor).filter(Supervisor.user_id == sup_user.id).first()
        if sup:
            sup.max_slots = 6
        db.commit()

    sup_id = sup.id
    sup_user_id = sup_user.id

    # 3. Student user with ACTIVE assignment
    stu_user = db.query(User).filter(User.username == "desk_stu").first()
    if not stu_user:
        stu_user = User(
            username="desk_stu",
            email=f"desk_stu_{uid}@test.local",
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
            department_id=dept_id,
            session_id=sess_id,
            usn="1SP23CS888",
            full_name="Grace Brewster Hopper",
            semester=8,
            academic_year=sess.name,
            phone="9876543210"
        )
        db.add(stu)
        db.commit()
    else:
        stu_user.password_hash = hash_password("Password123!")
        stu_user.must_change_password = False
        stu = db.query(Student).filter(Student.user_id == stu_user.id).first()
        db.commit()

    stu_id = stu.id
    stu_user_id = stu_user.id

    # Pending Student for Approvals page screenshot
    pending_user = db.query(User).filter(User.username == "desk_pending").first()
    if not pending_user:
        pending_user = User(
            username="desk_pending",
            email=f"pending_{uid}@test.local",
            password_hash=hash_password("Password123!"),
            role=RoleEnum.STUDENT,
            status=AccountStatusEnum.PENDING,
            must_change_password=False,
            session_version=1
        )
        db.add(pending_user)
        db.flush()
        p_stu = Student(
            user_id=pending_user.id,
            department_id=dept_id,
            session_id=sess_id,
            usn="1SP23CS777",
            full_name="Claude Elwood Shannon",
            semester=8,
            academic_year=sess.name,
            phone="9123456789"
        )
        db.add(p_stu)
        db.commit()

    # Student user WITHOUT active assignment for Topic Proposal & Duplicate Check
    prop_user = db.query(User).filter(User.username == "desk_prop").first()
    if not prop_user:
        prop_user = User(
            username="desk_prop",
            email=f"desk_prop_{uid}@test.local",
            password_hash=hash_password("Password123!"),
            role=RoleEnum.STUDENT,
            status=AccountStatusEnum.APPROVED,
            must_change_password=False,
            session_version=1
        )
        db.add(prop_user)
        db.flush()
        prop_stu = Student(
            user_id=prop_user.id,
            department_id=dept_id,
            session_id=sess_id,
            usn="1SP23CS999",
            full_name="Nikola Tesla",
            semester=8,
            academic_year=sess.name,
            phone="9876543299"
        )
        db.add(prop_stu)
        db.commit()
    else:
        prop_user.password_hash = hash_password("Password123!")
        prop_user.must_change_password = False
        db.commit()

    # Topic and Active Assignment for Student
    topic_title = f"Autonomous Multi-Agent Swarm Robotic Systems {uid}"
    topic = db.query(Topic).filter(Topic.title == topic_title).first()
    if not topic:
        topic = Topic(
            title=topic_title,
            normalized_title=f"autonomous multi agent swarm robotic systems {uid}",
            description="Decentralized coordination and consensus mechanisms for heterogeneous unmanned autonomous ground vehicles.",
            domain="Robotics & AI",
            department_id=dept_id,
            session_id=sess_id,
            proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
            proposed_by_user_id=sup_user_id,
            status=TopicStatusEnum.ASSIGNED
        )
        db.add(topic)
        db.flush()

    # Check for active assignment
    assign = db.query(TopicAssignment).filter(
        TopicAssignment.student_id == stu_id,
        TopicAssignment.status == AssignmentStatusEnum.ACTIVE
    ).first()
    if not assign:
        assign = TopicAssignment(
            topic_id=topic.id,
            student_id=stu_id,
            supervisor_id=sup_id,
            session_id=sess_id,
            status=AssignmentStatusEnum.ACTIVE,
            github_url="https://github.com/ghopper/swarm-robotics-core",
            github_url_locked=False
        )
        db.add(assign)
        db.commit()

    assign_id = assign.id

    # Seed Deadlines
    existing_dls = db.query(Deadline).filter(Deadline.session_id == sess_id).all()
    if not existing_dls:
        dl1 = Deadline(session_id=sess_id, chapter=ChapterEnum.SYNOPSIS, title="Project Synopsis Milestone", description="Problem formulation and objectives.", due_date=utc_now() + timedelta(days=14), allow_late=True)
        dl2 = Deadline(session_id=sess_id, chapter=ChapterEnum.SRS_DESIGN, title="Software Requirements & Architecture", description="SRS and UML design.", due_date=utc_now() + timedelta(days=45), allow_late=False)
        dl3 = Deadline(session_id=sess_id, chapter=ChapterEnum.IMPLEMENTATION, title="Prototype Implementation & Testing", description="Working software.", due_date=utc_now() + timedelta(days=90), allow_late=True)
        dl4 = Deadline(session_id=sess_id, chapter=ChapterEnum.FINAL_REPORT, title="Final Project Dissertation", description="Comprehensive thesis report.", due_date=utc_now() + timedelta(days=120), allow_late=False)
        db.add_all([dl1, dl2, dl3, dl4])
        db.commit()

    # Seed Submissions & Review
    sub1 = db.query(Submission).filter(Submission.assignment_id == assign_id, Submission.chapter == ChapterEnum.SYNOPSIS).first()
    if not sub1:
        sub1 = Submission(
            assignment_id=assign_id,
            chapter=ChapterEnum.SYNOPSIS,
            version=1,
            file_path="storage/submissions/sample_synopsis.pdf",
            original_filename="Synopsis_Swarm_Robotics.pdf",
            file_size=245000,
            submitted_at=utc_now()
        )
        db.add(sub1)
        db.flush()
        fb1 = Feedback(
            submission_id=sub1.id,
            supervisor_id=sup_id,
            status=FeedbackStatusEnum.NEEDS_REVISION,
            comments="Please expand the algorithmic complexity section and compare with Voronoi partitioning.",
            created_at=utc_now()
        )
        db.add(fb1)
        db.commit()

    # Seed Topic for Request
    avail_topic = db.query(Topic).filter(Topic.status == TopicStatusEnum.AVAILABLE).first()
    if not avail_topic:
        avail_topic = Topic(
            title=f"Zero-Trust Cloud Identity Verification {uid}",
            normalized_title=f"zero trust cloud identity verification {uid}",
            description="Continuous posture evaluation and cryptographic token attestation in microservice meshes.",
            domain="Cybersecurity",
            department_id=dept_id,
            session_id=sess_id,
            proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
            proposed_by_user_id=sup_user_id,
            status=TopicStatusEnum.AVAILABLE
        )
        db.add(avail_topic)
        db.commit()

    # Seed Topic Request for topic requests view
    treq = db.query(TopicRequest).filter(TopicRequest.status == TopicRequestStatusEnum.PENDING).first()
    if not treq:
        treq = TopicRequest(
            topic_id=avail_topic.id,
            student_id=p_stu.id,
            status=TopicRequestStatusEnum.PENDING,
            student_remarks="I have completed advanced coursework in distributed cryptography and would like to build this system."
        )
        db.add(treq)
        db.commit()

    # Seed Messaging
    existing_msg = db.query(Message).filter(Message.assignment_id == assign_id).first()
    if not existing_msg:
        m1 = Message(
            assignment_id=assign_id,
            sender_id=stu_user_id,
            recipient_id=sup_user_id,
            content="Professor, I have updated the swarm collision-avoidance protocol according to your recommendations.",
            created_at=utc_now() - timedelta(hours=2)
        )
        m2 = Message(
            assignment_id=assign_id,
            sender_id=sup_user_id,
            recipient_id=stu_user_id,
            content="Excellent progress. Let us review the test harness results during our weekly sync.",
            created_at=utc_now() - timedelta(minutes=45)
        )
        db.add_all([m1, m2])
        db.commit()

    # Seed Forum Thread & Reply
    existing_thread = db.query(ForumThread).filter(ForumThread.department_id == dept_id).first()
    if not existing_thread:
        thread = ForumThread(
            department_id=dept_id,
            user_id=sup_user_id,
            title="Best Practices for Final Year Project Deliverables and Benchmarking",
            content="Welcome everyone. When writing your SRS and Implementation reports, please ensure all simulation benchmarks are reproducible with specified seed numbers.",
            created_at=utc_now() - timedelta(days=3)
        )
        db.add(thread)
        db.flush()
        reply = ForumReply(
            thread_id=thread.id,
            user_id=stu_user_id,
            content="Thank you Professor. Will Docker compose specifications be accepted for environment reproduction?",
            created_at=utc_now() - timedelta(days=2)
        )
        db.add(reply)
        db.commit()

    # Seed Guidelines Document
    existing_doc = db.query(Guideline).first()
    if not existing_doc:
        doc = Guideline(
            coordinator_id=coord_user.id,
            title="SPMS Project Guidelines & Template 2026",
            description="Official thesis formatting guide, LaTeX templates, and milestone evaluation criteria.",
            file_path="storage/guidelines/official_guidelines_2026.pdf",
            original_filename="SPMS_Guidelines_2026.pdf",
            file_size=512000,
            created_at=utc_now()
        )
        db.add(doc)
        db.commit()

    # Seed Notifications for users
    notif1 = db.query(Notification).filter(Notification.user_id == stu_user_id).first()
    if not notif1:
        n1 = Notification(
            user_id=stu_user_id,
            title="Revision Requested: Synopsis Milestone",
            message="Your supervisor submitted feedback on your Synopsis submission: 'Please expand the algorithmic complexity section...'",
            link="/submissions",
            is_read=False,
            created_at=utc_now()
        )
        db.add(n1)
        db.commit()

    db.close()
    return {
        "assign_id": assign_id,
        "existing_topic_title": topic_title
    }


def capture_all_desktop_screenshots():
    print("[DESKTOP] Initializing test data for 1280x720 desktop screenshots...")
    data = setup_desktop_test_data()
    assign_id = data["assign_id"]
    existing_topic = data["existing_topic_title"]

    captured_files = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Desktop 1280x720 Viewport in Light Mode
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
        # 1. LOGIN
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        path = DESKTOP_DIR / "01_login_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 1. Captured {path.name}")

        # --------------------------------------------------------------------
        # 2. REGISTER
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/register")
        path = DESKTOP_DIR / "02_register_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 2. Captured {path.name}")

        # --------------------------------------------------------------------
        # 3. COORDINATOR APPROVALS & SUPERVISORS & TOPIC REQUESTS & DASHBOARD
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "desk_coord")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        # Coordinator Dashboard
        path = DESKTOP_DIR / "16_dashboard_coordinator_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 16. Captured {path.name}")

        # Coordinator Approvals
        nav(f"{BASE_URL}/coordinator/approvals")
        page.wait_for_selector("h3:has-text('Account Approvals')")
        path = DESKTOP_DIR / "03_coordinator_approvals_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 3. Captured {path.name}")

        # Supervisors
        nav(f"{BASE_URL}/coordinator/supervisors")
        page.wait_for_selector("h3:has-text('Supervisors & Slots')")
        path = DESKTOP_DIR / "04_supervisors_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 4. Captured {path.name}")

        # Topic Requests
        nav(f"{BASE_URL}/coordinator/topic-requests")
        page.wait_for_selector("h3:has-text('Topic Allocation Requests')")
        path = DESKTOP_DIR / "07_topic_requests_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 7. Captured {path.name}")

        logout()

        # --------------------------------------------------------------------
        # 4. STUDENT TOPIC PROPOSAL & DUPLICATE CHECK (No Active Assignment)
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "desk_prop")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        # Topic Propose Form
        nav(f"{BASE_URL}/topics/propose")
        page.wait_for_selector("h3:has-text('Propose Project Topic')")
        path = DESKTOP_DIR / "05_topic_propose_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 5. Captured {path.name}")

        # Duplicate Rejection Screen
        # Submit existing topic title
        page.fill("#title", existing_topic)
        page.fill("#description", "Autonomous decentralized coordination across multi-agent swarms with Byzantine fault tolerance.")
        page.fill("#domain", "Robotics")
        page.click("form[action='/topics/propose'] button[type=submit]")
        page.wait_for_selector(".alert-danger:has-text('Duplicate topic detected')")
        path = DESKTOP_DIR / "06_duplicate_rejection_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 6. Captured {path.name}")

        logout()

        # --------------------------------------------------------------------
        # 4.1 STUDENT WORKFLOW: DASHBOARD, SUBMISSIONS PIPELINE, MESSAGING, FORUM, GUIDELINES, NOTIFICATIONS
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "desk_stu")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        # Student Dashboard
        path = DESKTOP_DIR / "14_dashboard_student_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 14. Captured {path.name}")

        # Submissions Pipeline
        nav(f"{BASE_URL}/submissions")
        page.wait_for_selector(".badge:has-text('ACTIVE PROJECT')")
        path = DESKTOP_DIR / "08_submissions_pipeline_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 8. Captured {path.name}")

        # Messaging Conversation View
        nav(f"{BASE_URL}/messaging/{assign_id}")
        page.wait_for_selector("#chatBox")
        path = DESKTOP_DIR / "10_messaging_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 10. Captured {path.name}")

        # Forum
        nav(f"{BASE_URL}/forum")
        page.wait_for_selector("h3:has-text('Department Forum')")
        path = DESKTOP_DIR / "11_forum_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 11. Captured {path.name}")

        # Guidelines
        nav(f"{BASE_URL}/guidelines")
        page.wait_for_selector("h3:has-text('Project Guidelines')")
        path = DESKTOP_DIR / "12_guidelines_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 12. Captured {path.name}")

        # Notifications
        nav(f"{BASE_URL}/notifications")
        page.wait_for_selector("h3:has-text('Notifications')")
        path = DESKTOP_DIR / "13_notifications_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 13. Captured {path.name}")

        logout()

        # --------------------------------------------------------------------
        # 5. SUPERVISOR WORKFLOW: DASHBOARD, SUPERVISOR REVIEW
        # --------------------------------------------------------------------
        nav(f"{BASE_URL}/auth/login")
        page.fill("#username", "desk_sup")
        page.fill("#password", "Password123!")
        page.click("form[action='/auth/login'] button[type=submit]")
        page.wait_for_url(f"{BASE_URL}/dashboard")

        # Supervisor Dashboard
        path = DESKTOP_DIR / "15_dashboard_supervisor_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 15. Captured {path.name}")

        # Supervisor Review
        nav(f"{BASE_URL}/submissions/reviews")
        page.wait_for_selector("h3:has-text('Review Chapter Submissions')")
        path = DESKTOP_DIR / "09_supervisor_review_desktop.png"
        page.screenshot(path=str(path), full_page=True)
        captured_files.append(path.name)
        print(f"  [OK] 9. Captured {path.name}")

        logout()
        browser.close()

    print("=" * 64)
    print(f"SUCCESSFULLY CAPTURED {len(captured_files)} DESKTOP SCREENSHOTS (1280x720) IN LIGHT MODE:")
    for f in captured_files:
        print(f"  - screenshots/desktop/{f}")
    print("=" * 64)


if __name__ == "__main__":
    capture_all_desktop_screenshots()
