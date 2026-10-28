"""
Demo Data Seeding Script for SPMS.
Creates a pristine demonstration dataset:
- Active Academic Session & Departments
- 1 Coordinator account
- 2 Faculty Supervisors (historical figures)
- 3 Students (historical figures)
- 1 In-progress project assignment (with Synopsis approved, SRS under review)
- 1 Proposed project topic awaiting coordinator review
- 1 Completed and ARCHIVED project (all 4 chapters approved, graded A+, locked GitHub URL)
- Department guidelines
- All 4 chapter deadlines
No real personal names or hardcoded plain-text passwords appear in logs or output.
Credentials for demo logins are written to .demo_credentials (gitignored).
"""
import os
import sys
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.database import SessionLocal
from app.models.user import User, RoleEnum, AccountStatusEnum, Department, AcademicSession
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import (
    Topic, TopicStatusEnum, TopicAssignment, AssignmentStatusEnum,
    TopicProposedRoleEnum
)
from app.models.submission import (
    Submission, Feedback, Deadline, ChapterEnum, FeedbackStatusEnum, CHAPTER_DISPLAY_NAMES
)
from app.models.assessment import Assessment
from app.models.guideline import Guideline
from app.core.security import hash_password
from app.core.datetime_util import utc_now


def seed_demo_data():
    db = SessionLocal()
    print("[DEMO SEED] Starting demonstration data population...")

    # Default demo password for local development/demo
    demo_password = os.getenv("DEMO_USER_PASSWORD", "Demo123456!")
    pwd_hash = hash_password(demo_password)

    # 1. Departments
    dept_cse = db.query(Department).filter(Department.code == "CSE").first()
    if not dept_cse:
        dept_cse = Department(code="CSE", name="Computer Science and Engineering")
        db.add(dept_cse)
    dept_ise = db.query(Department).filter(Department.code == "ISE").first()
    if not dept_ise:
        dept_ise = Department(code="ISE", name="Information Science and Engineering")
        db.add(dept_ise)
    db.commit()

    # 2. Active Academic Session
    today = date.today()
    session_name = "2025-2026"
    sess = db.query(AcademicSession).filter(AcademicSession.name == session_name).first()
    if not sess:
        sess = AcademicSession(
            name=session_name,
            start_date=date(today.year, 8, 1),
            end_date=date(today.year + 1, 6, 30),
            is_active=True
        )
        db.add(sess)
        db.commit()

    # 3. Chapter Deadlines
    deadlines_config = [
        (ChapterEnum.SYNOPSIS, "Synopsis Document Milestone", 30, True),
        (ChapterEnum.SRS_DESIGN, "SRS & Architecture Design", 60, True),
        (ChapterEnum.IMPLEMENTATION, "Core Implementation & Testing", 90, True),
        (ChapterEnum.FINAL_REPORT, "Final Project Dissertation", 120, False),
    ]
    for ch, title, days, allow_late in deadlines_config:
        dl = db.query(Deadline).filter(Deadline.session_id == sess.id, Deadline.chapter == ch).first()
        if not dl:
            db.add(Deadline(
                session_id=sess.id,
                chapter=ch,
                title=title,
                description=f"Standard milestone submission for {CHAPTER_DISPLAY_NAMES[ch]}.",
                due_date=utc_now() + timedelta(days=days),
                allow_late=allow_late
            ))
    db.commit()

    # 4. Coordinator User
    coord = db.query(User).filter((User.username == "coord_demo") | (User.email == "coordinator@spms.local")).first()
    if not coord:
        coord = User(
            username="coord_demo",
            email="coordinator@spms.local",
            password_hash=pwd_hash,
            role=RoleEnum.ADMIN,
            status=AccountStatusEnum.APPROVED,
            must_change_password=False,
            session_version=1
        )
        db.add(coord)
        db.commit()

    # 5. Faculty Supervisors
    sup1_user = db.query(User).filter((User.username == "prof_turing") | (User.email == "turing@spms.local")).first()
    if not sup1_user:
        sup1_user = User(
            username="prof_turing",
            email="turing@spms.local",
            password_hash=pwd_hash,
            role=RoleEnum.SUPERVISOR,
            status=AccountStatusEnum.APPROVED,
            must_change_password=False,
            session_version=1
        )
        db.add(sup1_user)
        db.flush()
        sup1 = Supervisor(
            user_id=sup1_user.id,
            department_id=dept_cse.id,
            full_name="Dr. Alan Turing",
            designation="Professor & Research Lead",
            max_slots=5
        )
        db.add(sup1)
        db.commit()
    else:
        sup1 = sup1_user.supervisor_profile

    sup2_user = db.query(User).filter((User.username == "prof_hopper") | (User.email == "hopper@spms.local")).first()
    if not sup2_user:
        sup2_user = User(
            username="prof_hopper",
            email="hopper@spms.local",
            password_hash=pwd_hash,
            role=RoleEnum.SUPERVISOR,
            status=AccountStatusEnum.APPROVED,
            must_change_password=False,
            session_version=1
        )
        db.add(sup2_user)
        db.flush()
        sup2 = Supervisor(
            user_id=sup2_user.id,
            department_id=dept_ise.id,
            full_name="Dr. Grace Hopper",
            designation="Associate Professor",
            max_slots=5
        )
        db.add(sup2)
        db.commit()
    else:
        sup2 = sup2_user.supervisor_profile

    # 6. Students
    # Student 1: Ada Lovelace (In-progress project)
    s1 = db.query(Student).filter(Student.usn == "1SP23CS001").first()
    if not s1:
        s1_user = db.query(User).filter((User.username == "1SP23CS001") | (User.email == "ada.lovelace@spms.local")).first()
        if not s1_user:
            s1_user = User(
                username="1SP23CS001",
                email="ada.lovelace@spms.local",
                password_hash=pwd_hash,
                role=RoleEnum.STUDENT,
                status=AccountStatusEnum.APPROVED,
                must_change_password=False,
                session_version=1
            )
            db.add(s1_user)
            db.flush()
        s1 = Student(
            user_id=s1_user.id,
            department_id=dept_cse.id,
            session_id=sess.id,
            usn="1SP23CS001",
            full_name="Ada Lovelace",
            semester=8,
            academic_year="2025-2026",
            phone="9876543201"
        )
        db.add(s1)
        db.commit()
    else:
        s1_user = s1.user

    # Student 2: Charles Babbage (Proposed topic awaiting approval)
    s2 = db.query(Student).filter(Student.usn == "1SP23CS002").first()
    if not s2:
        s2_user = db.query(User).filter((User.username == "1SP23CS002") | (User.email == "charles.babbage@spms.local")).first()
        if not s2_user:
            s2_user = User(
                username="1SP23CS002",
                email="charles.babbage@spms.local",
                password_hash=pwd_hash,
                role=RoleEnum.STUDENT,
                status=AccountStatusEnum.APPROVED,
                must_change_password=False,
                session_version=1
            )
            db.add(s2_user)
            db.flush()
        s2 = Student(
            user_id=s2_user.id,
            department_id=dept_cse.id,
            session_id=sess.id,
            usn="1SP23CS002",
            full_name="Charles Babbage",
            semester=8,
            academic_year="2025-2026",
            phone="9876543202"
        )
        db.add(s2)
        db.commit()
    else:
        s2_user = s2.user

    # Student 3: Margaret Hamilton (Completed & Archived project)
    s3 = db.query(Student).filter(Student.usn == "1SP23CS003").first()
    if not s3:
        s3_user = db.query(User).filter((User.username == "1SP23CS003") | (User.email == "margaret.hamilton@spms.local")).first()
        if not s3_user:
            s3_user = User(
                username="1SP23CS003",
                email="margaret.hamilton@spms.local",
                password_hash=pwd_hash,
                role=RoleEnum.STUDENT,
                status=AccountStatusEnum.APPROVED,
                must_change_password=False,
                session_version=1
            )
            db.add(s3_user)
            db.flush()
        s3 = Student(
            user_id=s3_user.id,
            department_id=dept_ise.id,
            session_id=sess.id,
            usn="1SP23CS003",
            full_name="Margaret Hamilton",
            semester=8,
            academic_year="2025-2026",
            phone="9876543203"
        )
        db.add(s3)
        db.commit()
    else:
        s3_user = s3.user

    # 7. Topics and Project Assignments
    # Ensure sample storage directories
    storage_sub = ROOT_DIR / "storage" / "submissions"
    storage_sub.mkdir(parents=True, exist_ok=True)
    sample_pdf = storage_sub / "demo_document.pdf"
    if not sample_pdf.exists():
        sample_pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Title (SPMS Project Document) >>\nendobj\ntrailer\n<< >>\n%%EOF\n")

    # Project 1: Active In-Progress for Ada Lovelace
    t1 = db.query(Topic).filter(Topic.title == "Autonomous Drone Navigation Network").first()
    if not t1:
        t1 = Topic(
            title="Autonomous Drone Navigation Network",
            normalized_title="autonomous drone navigation network",
            description="Real-time multi-UAV obstacle detection and distributed mesh communication protocol.",
            domain="Autonomous Systems",
            department_id=dept_cse.id,
            session_id=sess.id,
            proposed_by_role=TopicProposedRoleEnum.STUDENT,
            proposed_by_user_id=s1_user.id,
            status=TopicStatusEnum.ASSIGNED
        )
        db.add(t1)
        db.flush()

        a1 = TopicAssignment(
            topic_id=t1.id,
            student_id=s1.id,
            supervisor_id=sup1.id,
            session_id=sess.id,
            status=AssignmentStatusEnum.ACTIVE,
            github_url="https://github.com/spms-demo/drone-navigation",
            github_url_locked=False,
            assigned_at=utc_now() - timedelta(days=20)
        )
        db.add(a1)
        db.flush()

        # Synopsis Approved
        sub_syn = Submission(
            assignment_id=a1.id,
            chapter=ChapterEnum.SYNOPSIS,
            version=1,
            original_filename="Synopsis_Drone_Navigation.pdf",
            file_path=str(sample_pdf),
            file_size=len(sample_pdf.read_bytes()),
            is_late=False
        )
        db.add(sub_syn)
        db.flush()
        db.add(Feedback(
            submission_id=sub_syn.id,
            supervisor_id=sup1.id,
            status=FeedbackStatusEnum.APPROVED,
            comments="Solid project scope and problem statement clearly formulated. Approved."
        ))

        # SRS & Design Submitted (Under Review)
        sub_srs = Submission(
            assignment_id=a1.id,
            chapter=ChapterEnum.SRS_DESIGN,
            version=1,
            original_filename="SRS_Design_Drone_Navigation.pdf",
            file_path=str(sample_pdf),
            file_size=len(sample_pdf.read_bytes()),
            is_late=False
        )
        db.add(sub_srs)
        db.commit()

    # Project 2: Proposed Topic by Charles Babbage (Awaiting Coordinator Review)
    t2 = db.query(Topic).filter(Topic.title == "Decentralized Microgrid Optimizer").first()
    if not t2:
        t2 = Topic(
            title="Decentralized Microgrid Optimizer",
            normalized_title="decentralized microgrid optimizer",
            description="Smart energy dispatch and demand forecasting using reinforcement learning on decentralized solar clusters.",
            domain="Renewable Energy & IoT",
            department_id=dept_cse.id,
            session_id=sess.id,
            proposed_by_role=TopicProposedRoleEnum.STUDENT,
            proposed_by_user_id=s2_user.id,
            status=TopicStatusEnum.PROPOSED
        )
        db.add(t2)
        db.commit()

    # Project 3: Completed and ARCHIVED Project for Margaret Hamilton
    t3 = db.query(Topic).filter(Topic.title == "Fault-Tolerant Spacecraft Flight Control System").first()
    if not t3:
        t3 = Topic(
            title="Fault-Tolerant Spacecraft Flight Control System",
            normalized_title="fault tolerant spacecraft flight control system",
            description="Asynchronous priority-driven executive with memory-safe concurrency for high-reliability embedded avionics.",
            domain="Embedded Systems & Aerospace",
            department_id=dept_ise.id,
            session_id=sess.id,
            proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
            proposed_by_user_id=sup2_user.id,
            status=TopicStatusEnum.ARCHIVED
        )
        db.add(t3)
        db.flush()

        a3 = TopicAssignment(
            topic_id=t3.id,
            student_id=s3.id,
            supervisor_id=sup2.id,
            session_id=sess.id,
            status=AssignmentStatusEnum.COMPLETED,
            github_url="https://github.com/spms-demo/apollo-flight-control",
            github_url_locked=True,
            assigned_at=utc_now() - timedelta(days=90),
            completed_at=utc_now() - timedelta(days=5)
        )
        db.add(a3)
        db.flush()

        # All 4 chapters submitted and approved
        for ch in [ChapterEnum.SYNOPSIS, ChapterEnum.SRS_DESIGN, ChapterEnum.IMPLEMENTATION, ChapterEnum.FINAL_REPORT]:
            sub = Submission(
                assignment_id=a3.id,
                chapter=ch,
                version=1,
                original_filename=f"{ch.value}_apollo_control.pdf",
                file_path=str(sample_pdf),
                file_size=len(sample_pdf.read_bytes()),
                is_late=False
            )
            db.add(sub)
            db.flush()
            db.add(Feedback(
                submission_id=sub.id,
                supervisor_id=sup2.id,
                status=FeedbackStatusEnum.APPROVED,
                comments=f"{CHAPTER_DISPLAY_NAMES[ch]} thoroughly tested and verified according to project milestones."
            ))

        # Assessment and Final Grade
        assess3 = Assessment(
            assignment_id=a3.id,
            supervisor_id=sup2.id,
            presentation_score=29.5,
            report_score=29.0,
            implementation_score=39.5,
            total_score=98.0,
            supervisor_remarks="Exceptional flight control architectural design with formal verification proofs.",
            coordinator_final_grade="A+",
            finalized_by_user_id=coord.id,
            finalized_at=utc_now() - timedelta(days=5)
        )
        db.add(assess3)
        db.commit()

    # 8. Department Guidelines
    guideline_dir = ROOT_DIR / "storage" / "guidelines"
    guideline_dir.mkdir(parents=True, exist_ok=True)
    g_file = guideline_dir / "sample_guideline.pdf"
    if not g_file.exists():
        g_file.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Title (SPMS Project Guidelines) >>\nendobj\ntrailer\n<< >>\n%%EOF\n")

    g1 = db.query(Guideline).filter(Guideline.title == "Final Year Project Handbook 2025-2026").first()
    if not g1:
        g1 = Guideline(
            title="Final Year Project Handbook 2025-2026",
            description="Comprehensive guide covering synopsis preparation, SRS conventions, implementation review criteria, and final dissertation format.",
            coordinator_id=coord.id,
            original_filename="SPMS_Project_Handbook_2025_2026.pdf",
            file_path=str(g_file),
            file_size=len(g_file.read_bytes())
        )
        db.add(g1)
        db.commit()

    db.close()

    # Write demo login credentials securely to local gitignored file
    creds_file = ROOT_DIR / ".demo_credentials"
    creds_content = (
        "# SPMS Demonstration Login Credentials (Local Reference Only)\n"
        f"Password for all demo accounts: {demo_password}\n\n"
        "1. Coordinator / Admin:\n"
        "   Username: coord_demo\n"
        "   Role:     ADMIN\n\n"
        "2. Faculty Supervisors:\n"
        "   Username: prof_turing   (CSE Department, 5 slots)\n"
        "   Username: prof_hopper   (ISE Department, 5 slots)\n\n"
        "3. Students:\n"
        "   Username: 1SP23CS001    (Ada Lovelace - Active project in progress)\n"
        "   Username: 1SP23CS002    (Charles Babbage - Proposed topic pending approval)\n"
        "   Username: 1SP23CS003    (Margaret Hamilton - Completed & Archived project)\n"
    )
    creds_file.write_text(creds_content, encoding="utf-8")

    print("[DEMO SEED SUCCESS] Demonstration data seeded successfully!")
    print(f"                   Pristine test credentials saved to: {creds_file.name} (gitignored)")


if __name__ == "__main__":
    seed_demo_data()
