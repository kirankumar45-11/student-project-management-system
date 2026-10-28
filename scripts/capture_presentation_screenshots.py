"""
Playwright Presentation Screenshot Suite for SPMS.
Captures clean, high-resolution presentation screenshots for project presentation:
- Standard Desktop: 1280x720 in Light Mode
- Dark Mode: 1280x720 in Dark Mode (Student Dashboard)
- Mobile: 360x740 in Light Mode (Student Dashboard & Submission Pipeline)

All screenshots are stored in screenshots/ppt/ with numbered names.
"""
import os
import sys
import time
import threading
import urllib.request
from datetime import timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

import uvicorn
from app.database import SessionLocal
from app.models.user import User, RoleEnum, Department, AcademicSession
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import Topic, TopicAssignment, AssignmentStatusEnum, TopicStatusEnum
from app.models.submission import Submission, ChapterEnum, Feedback, FeedbackStatusEnum, CHAPTER_DISPLAY_NAMES
from app.models.communication import Message, ForumThread, ForumReply
from app.models.guideline import Notification
from app.core.datetime_util import utc_now

from scripts.reset_db import reset_database
from scripts.seed_demo import seed_demo_data

PPT_DIR = ROOT_DIR / "screenshots" / "ppt"
PPT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://127.0.0.1:8000"
server = None


def start_server():
    global server
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def prepare_demo_extra_data():
    """Populates messages, forum thread, and notifications to ensure presentation screenshots look authentic."""
    db = SessionLocal()
    try:
        # Find key demo users
        ada_user = db.query(User).filter(User.username == "1SP23CS001").first()
        turing_user = db.query(User).filter(User.username == "prof_turing").first()
        coord_user = db.query(User).filter(User.username == "coord_demo").first()
        dept_cse = db.query(Department).filter(Department.code == "CSE").first()
        
        # 1. Active Assignment for Ada
        a1 = db.query(TopicAssignment).filter(TopicAssignment.status == AssignmentStatusEnum.ACTIVE).first()
        if a1 and ada_user and turing_user:
            # Seed Messages between Ada and Dr. Turing
            existing_msg = db.query(Message).filter(Message.assignment_id == a1.id).first()
            if not existing_msg:
                m1 = Message(
                    assignment_id=a1.id,
                    sender_id=ada_user.id,
                    recipient_id=turing_user.id,
                    content="Good morning Dr. Turing, I have uploaded the revised SRS document with the multi-UAV obstacle avoidance diagrams. Please review when convenient.",
                    created_at=utc_now() - timedelta(hours=3),
                    is_read=True
                )
                m2 = Message(
                    assignment_id=a1.id,
                    sender_id=turing_user.id,
                    recipient_id=ada_user.id,
                    content="Hello Ada, I have reviewed the architecture section. The mesh routing and collision detection protocol look very solid. You may proceed with implementation.",
                    created_at=utc_now() - timedelta(hours=2),
                    is_read=True
                )
                m3 = Message(
                    assignment_id=a1.id,
                    sender_id=ada_user.id,
                    recipient_id=turing_user.id,
                    content="Thank you Dr. Turing! I am beginning the distributed consensus testing on hardware today.",
                    created_at=utc_now() - timedelta(minutes=45),
                    is_read=False
                )
                db.add_all([m1, m2, m3])

        # 2. Forum Thread in CSE
        if dept_cse and turing_user:
            existing_th = db.query(ForumThread).filter(ForumThread.department_id == dept_cse.id).first()
            if not existing_th:
                th = ForumThread(
                    department_id=dept_cse.id,
                    user_id=turing_user.id,
                    title="8th Semester Project Report Conventions & IEEE Formatting Guidelines",
                    content="Welcome everyone to the final year project milestone phase. Please ensure that all submissions adhere strictly to the departmental IEEE two-column template. Project source code must be maintained on GitHub.",
                    is_pinned=True,
                    created_at=utc_now() - timedelta(days=2)
                )
                db.add(th)
                db.flush()
                
                if ada_user:
                    rep = ForumReply(
                        thread_id=th.id,
                        user_id=ada_user.id,
                        content="Thank you Dr. Turing! Is the official LaTeX template available directly in the guidelines section?",
                        created_at=utc_now() - timedelta(days=1)
                    )
                    db.add(rep)

        # 3. Notifications for Ada
        if ada_user:
            existing_notif = db.query(Notification).filter(Notification.user_id == ada_user.id).first()
            if not existing_notif:
                notifs = [
                    Notification(
                        user_id=ada_user.id,
                        title="Student Account Approved",
                        message="Your student registration has been approved by the Department Coordinator. Welcome to SPMS!",
                        link="/dashboard",
                        created_at=utc_now() - timedelta(days=25)
                    ),
                    Notification(
                        user_id=ada_user.id,
                        title="Project Topic Assigned",
                        message="Your topic 'Autonomous Drone Navigation Network' has been assigned with Dr. Alan Turing as Supervisor.",
                        link="/submissions",
                        created_at=utc_now() - timedelta(days=20)
                    ),
                    Notification(
                        user_id=ada_user.id,
                        title="Synopsis Submission Approved",
                        message="Supervisor Dr. Alan Turing approved your Synopsis submission: 'Solid project scope and problem statement clearly formulated.'",
                        link="/submissions",
                        created_at=utc_now() - timedelta(days=15)
                    ),
                    Notification(
                        user_id=ada_user.id,
                        title="New Message from Supervisor",
                        message="Dr. Alan Turing sent a message: 'Hello Ada, I have reviewed the architecture section...'",
                        link="/messaging",
                        created_at=utc_now() - timedelta(hours=2)
                    )
                ]
                db.add_all(notifs)

        db.commit()
    finally:
        db.close()


def capture_all():
    print("=" * 75)
    print("SPMS PRESENTATION SCREENSHOT CAPTURE SUITE")
    print(f"Output Directory: {PPT_DIR}")
    print("=" * 75)

    captured_files = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        def take_shot(page, filename, description):
            page.wait_for_load_state("domcontentloaded")
            time.sleep(0.4)
            out_path = PPT_DIR / filename
            page.screenshot(path=str(out_path), full_page=False)
            size_kb = round(out_path.stat().st_size / 1024, 1)
            print(f"  [SAVED] {filename:<45} ({size_kb:>6} KB) - {description}")
            captured_files.append((filename, size_kb, description))

        def make_context(width=1280, height=720, mode="light"):
            ctx = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
                color_scheme=mode
            )
            return ctx

        def login(page, username, password="Demo123456!"):
            page.goto(f"{BASE_URL}/auth/login", wait_until="domcontentloaded")
            page.fill("#username", username)
            page.fill("#password", password)
            page.click("form[action='/auth/login'] button[type=submit]")
            page.wait_for_url(f"{BASE_URL}/dashboard", timeout=8000)
            time.sleep(0.3)

        # --------------------------------------------------------------------
        # 1. Login Page
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        pg.goto(f"{BASE_URL}/auth/login", wait_until="domcontentloaded")
        take_shot(pg, "01_login_page.png", "Login page with authentication form")
        ctx.close()

        # --------------------------------------------------------------------
        # 2. Student Registration Form
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        pg.goto(f"{BASE_URL}/auth/register", wait_until="domcontentloaded")
        pg.fill("#usn", "1SP23CS004")
        pg.fill("#full_name", "Claude Shannon")
        pg.select_option("#department_id", index=1)
        pg.select_option("#session_id", index=0)
        pg.select_option("#semester", value="8")
        pg.fill("#email", "claude.shannon@spms.local")
        pg.fill("#phone", "9876543204")
        pg.fill("#skills", "Information Theory, Cryptography, Data Compression")
        # Keep password fields unmasked / empty or clean during screenshot
        take_shot(pg, "02_student_registration_form.png", "Student registration form with populated student details")
        
        # Submit to register Claude Shannon as PENDING for coordinator approval demo
        pg.fill("#password", "Demo123456!")
        pg.click("form[action='/auth/register'] button[type=submit]")
        time.sleep(0.5)
        ctx.close()

        # --------------------------------------------------------------------
        # 3. Coordinator Approvals List
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "coord_demo")
        pg.goto(f"{BASE_URL}/coordinator/approvals", wait_until="domcontentloaded")
        take_shot(pg, "03_coordinator_approvals_list.png", "Coordinator pending student account approvals list")

        # --------------------------------------------------------------------
        # 4. Coordinator Supervisors Page (with slot counters)
        # --------------------------------------------------------------------
        pg.goto(f"{BASE_URL}/coordinator/supervisors", wait_until="domcontentloaded")
        take_shot(pg, "04_coordinator_supervisors_page.png", "Coordinator supervisors page with slot gauges and capacity trackers")

        # --------------------------------------------------------------------
        # 7. Coordinator Topic Requests & Supervisor Assignment
        # --------------------------------------------------------------------
        pg.goto(f"{BASE_URL}/coordinator/topics", wait_until="domcontentloaded")
        take_shot(pg, "07_coordinator_topic_requests_assignment.png", "Coordinator topic review and supervisor assignment interface")
        ctx.close()

        # --------------------------------------------------------------------
        # 5. Student Topic Proposal Form
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "1SP23CS002") # Charles Babbage (no active assignment)
        pg.goto(f"{BASE_URL}/topics/propose", wait_until="domcontentloaded")
        pg.fill("#title", "Autonomous Distributed Swarm Robotics Framework")
        pg.fill("#domain", "Robotics & Swarm Intelligence")
        pg.fill("#description", "Decentralized consensus algorithms and obstacle avoidance for autonomous UAV swarms operating under communication-constrained environments.")
        take_shot(pg, "05_student_topic_proposal_form.png", "Student topic proposal form with domain and project description")

        # --------------------------------------------------------------------
        # 6. Duplicate Topic Rejection
        # --------------------------------------------------------------------
        # Submit a title that matches Ada's active topic (Autonomous Drone Navigation Network)
        pg.fill("#title", "Autonomous Drone Navigation Network")
        pg.click("form[action='/topics/propose'] button[type=submit]")
        pg.wait_for_load_state("domcontentloaded")
        time.sleep(0.3)
        take_shot(pg, "06_duplicate_topic_rejection.png", "Duplicate topic rejection showing matching title and 100% similarity score")
        ctx.close()

        # --------------------------------------------------------------------
        # 8. Student Submission Pipeline
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "1SP23CS001") # Ada Lovelace
        pg.goto(f"{BASE_URL}/submissions", wait_until="domcontentloaded")
        take_shot(pg, "08_student_submission_pipeline.png", "Student submission pipeline stepper showing 4 milestone chapters and statuses")
        ctx.close()

        # --------------------------------------------------------------------
        # 9. Supervisor Review of a Submission
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "prof_turing")
        # Review detail for Ada's SRS submission (ID 2)
        pg.goto(f"{BASE_URL}/submissions/2/review", wait_until="domcontentloaded")
        take_shot(pg, "09_supervisor_submission_review.png", "Supervisor submission review with document download and feedback evaluation form")
        ctx.close()

        # --------------------------------------------------------------------
        # 10. Messaging Between Student and Supervisor
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "1SP23CS001")
        pg.goto(f"{BASE_URL}/messaging", wait_until="domcontentloaded")
        take_shot(pg, "10_messaging_student_supervisor.png", "Messaging interface between student and supervisor with project chat history")

        # --------------------------------------------------------------------
        # 11. Department Forum
        # --------------------------------------------------------------------
        pg.goto(f"{BASE_URL}/forum", wait_until="domcontentloaded")
        take_shot(pg, "11_department_forum.png", "Department discussion forum with pinned guidelines and replies")

        # --------------------------------------------------------------------
        # 12. Guidelines Page
        # --------------------------------------------------------------------
        pg.goto(f"{BASE_URL}/guidelines", wait_until="domcontentloaded")
        take_shot(pg, "12_guidelines_page.png", "Guidelines repository with official handbook download")

        # --------------------------------------------------------------------
        # 13. Notifications Page
        # --------------------------------------------------------------------
        pg.goto(f"{BASE_URL}/notifications", wait_until="domcontentloaded")
        take_shot(pg, "13_notifications_page.png", "Student notifications center showing milestone and system alerts")
        ctx.close()

        # --------------------------------------------------------------------
        # 14. Supervisor Grading Form
        # --------------------------------------------------------------------
        # To access the grading form, all 4 chapters must have approved feedback!
        # Let's approve SRS, add & approve Implementation, and add & approve Final Report for Ada:
        db = SessionLocal()
        a1 = db.query(TopicAssignment).filter(TopicAssignment.id == 1).first()
        turing_sup = db.query(Supervisor).filter(Supervisor.full_name.like("%Turing%")).first()
        sample_pdf = ROOT_DIR / "storage" / "submissions" / "demo_document.pdf"
        
        # Approve SRS
        sub_srs = db.query(Submission).filter(Submission.assignment_id == 1, Submission.chapter == ChapterEnum.SRS_DESIGN).first()
        if sub_srs and not sub_srs.feedback:
            db.add(Feedback(
                submission_id=sub_srs.id,
                supervisor_id=turing_sup.id,
                status=FeedbackStatusEnum.APPROVED,
                comments="SRS and architectural diagrams meet all department technical requirements."
            ))
        
        # Add Implementation
        sub_imp = db.query(Submission).filter(Submission.assignment_id == 1, Submission.chapter == ChapterEnum.IMPLEMENTATION).first()
        if not sub_imp:
            sub_imp = Submission(
                assignment_id=1,
                chapter=ChapterEnum.IMPLEMENTATION,
                version=1,
                original_filename="Implementation_Drone_Nav.pdf",
                file_path=str(sample_pdf),
                file_size=len(sample_pdf.read_bytes()),
                is_late=False
            )
            db.add(sub_imp)
            db.flush()
            db.add(Feedback(
                submission_id=sub_imp.id,
                supervisor_id=turing_sup.id,
                status=FeedbackStatusEnum.APPROVED,
                comments="Unit and integration tests pass with 94% coverage. ROS2 node execution verified."
            ))

        # Add Final Report
        sub_fin = db.query(Submission).filter(Submission.assignment_id == 1, Submission.chapter == ChapterEnum.FINAL_REPORT).first()
        if not sub_fin:
            sub_fin = Submission(
                assignment_id=1,
                chapter=ChapterEnum.FINAL_REPORT,
                version=1,
                original_filename="Final_Report_Drone_Nav.pdf",
                file_path=str(sample_pdf),
                file_size=len(sample_pdf.read_bytes()),
                is_late=False
            )
            db.add(sub_fin)
            db.flush()
            db.add(Feedback(
                submission_id=sub_fin.id,
                supervisor_id=turing_sup.id,
                status=FeedbackStatusEnum.APPROVED,
                comments="Comprehensive final dissertation with formal proofs and empirical validation."
            ))
        db.commit()
        db.close()

        # Now as Dr. Turing, open the grading form for Assignment 1
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "prof_turing")
        pg.goto(f"{BASE_URL}/assessments/1/grade", wait_until="domcontentloaded")
        # Fill in marks to showcase live computed score
        pg.fill("#presentation_score", "28.5")
        pg.fill("#report_score", "28.0")
        pg.fill("#implementation_score", "38.5")
        pg.fill("#supervisor_remarks", "Outstanding research depth, rigorous empirical evaluation, and exemplary code modularity on autonomous flight controller.")
        pg.evaluate("document.getElementById('report_score').dispatchEvent(new Event('input'))")
        time.sleep(0.3)
        take_shot(pg, "14_supervisor_grading_form.png", "Supervisor grading form with rubric marks and computed total score")
        
        # Submit the marks
        pg.click("form[action='/assessments/1/grade'] button[type=submit]")
        time.sleep(0.5)
        ctx.close()

        # --------------------------------------------------------------------
        # 15. Coordinator Grade Finalization
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "coord_demo")
        # Find newly created assessment for Assignment 1
        db = SessionLocal()
        assess1 = db.query(TopicAssignment).filter(TopicAssignment.id == 1).first().assessment
        assess_id = assess1.id if assess1 else 2
        db.close()
        
        pg.goto(f"{BASE_URL}/coordinator/assessments/{assess_id}/finalize", wait_until="domcontentloaded")
        pg.select_option("#coordinator_final_grade", value="A+")
        take_shot(pg, "15_coordinator_grade_finalization.png", "Coordinator grade finalization form with grade assignment and audit confirmation")
        
        # Finalize the grade
        pg.click("form[action*='/finalize'] button[type=submit]")
        time.sleep(0.5)
        ctx.close()

        # --------------------------------------------------------------------
        # 16. Archive Search Results
        # --------------------------------------------------------------------
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "1SP23CS001")
        pg.goto(f"{BASE_URL}/archive", wait_until="domcontentloaded")
        take_shot(pg, "16_archive_search_results.png", "Public project archive search results with department, year filters and cards")

        # --------------------------------------------------------------------
        # 17. Archive Project Detail Page
        # --------------------------------------------------------------------
        db = SessionLocal()
        arch_topic = db.query(Topic).filter(Topic.status == TopicStatusEnum.ARCHIVED).first()
        arch_id = arch_topic.id if arch_topic else 3
        db.close()
        pg.goto(f"{BASE_URL}/archive/{arch_id}", wait_until="domcontentloaded")
        take_shot(pg, "17_archive_project_detail.png", "Archive project detail page showing abstract, locked GitHub repo and approved final report download")

        # --------------------------------------------------------------------
        # 18. Dashboards (Student, Supervisor, Coordinator)
        # --------------------------------------------------------------------
        # 18a. Student Dashboard
        pg.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded")
        take_shot(pg, "18a_student_dashboard.png", "Student dashboard with final grade card, milestone stepper, and quick action cards")
        ctx.close()

        # 18b. Supervisor Dashboard
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "prof_turing")
        pg.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded")
        take_shot(pg, "18b_supervisor_dashboard.png", "Supervisor dashboard with slot capacity gauge, supervised students and review actions")
        ctx.close()

        # 18c. Coordinator Dashboard
        ctx = make_context()
        pg = ctx.new_page()
        login(pg, "coord_demo")
        pg.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded")
        take_shot(pg, "18c_coordinator_dashboard.png", "Coordinator dashboard with KPI stat cards, pending reviews, and department overview")
        ctx.close()

        # --------------------------------------------------------------------
        # 19. Dark Mode Student Dashboard
        # --------------------------------------------------------------------
        ctx = make_context(mode="dark")
        pg = ctx.new_page()
        login(pg, "1SP23CS001")
        pg.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded")
        pg.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")
        time.sleep(0.3)
        take_shot(pg, "19_student_dashboard_dark.png", "Student dashboard in dark mode showing theme styling and accessibility contrast")
        ctx.close()

        # --------------------------------------------------------------------
        # 20. 360px Mobile Screenshots (Student Dashboard & Submission Pipeline)
        # --------------------------------------------------------------------
        ctx = make_context(width=360, height=740, mode="light")
        pg = ctx.new_page()
        login(pg, "1SP23CS001")
        
        # 20a. Mobile Student Dashboard
        pg.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded")
        take_shot(pg, "20a_mobile_student_dashboard_360px.png", "Mobile 360px view of student dashboard with responsive card stack")

        # 20b. Mobile Submission Pipeline
        pg.goto(f"{BASE_URL}/submissions", wait_until="domcontentloaded")
        take_shot(pg, "20b_mobile_submission_pipeline_360px.png", "Mobile 360px view of submission pipeline stepper and chapter cards")
        ctx.close()

        browser.close()

    print("=" * 75)
    print(f"[SUCCESS] All {len(captured_files)} presentation screenshots captured successfully!")
    print("=" * 75)
    return captured_files


def main():
    print("[1/3] Resetting database and seeding pristine demo baseline...")
    reset_database()
    seed_demo_data()
    prepare_demo_extra_data()

    print("[2/3] Starting background FastAPI development server...")
    t = threading.Thread(target=start_server, daemon=True)
    t.start()

    # Wait for server health
    for i in range(15):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as r:
                if r.status == 200:
                    print(f"      Server is healthy and ready on port 8000 (attempt {i+1})")
                    break
        except Exception:
            continue

    print("[3/3] Running Playwright capture suite...")
    try:
        files = capture_all()
    finally:
        if server:
            server.should_exit = True
        time.sleep(1)

    print("\nSUMMARY OF CAPTURED SCREENSHOTS:")
    for fn, sz, desc in files:
        print(f"  - {fn} ({sz} KB): {desc}")


if __name__ == "__main__":
    main()
