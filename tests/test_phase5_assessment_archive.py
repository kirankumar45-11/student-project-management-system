import re
import uuid
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
from app.services.duplicate_detector import check_topic_duplicate


# ============================================================================
# HELPER FACTORIES
# ============================================================================
def create_test_student(db: Session, suffix: str) -> Student:
    dept = db.query(Department).first()
    sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    user = User(
        username=f"STU_P5_{suffix}",
        email=f"stu_p5_{suffix}@spms.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.APPROVED,
        session_version=1
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        department_id=dept.id,
        session_id=sess.id,
        usn=f"1SP23CS{suffix[:10]}",
        full_name=f"Student P5 {suffix}",
        semester=8,
        academic_year=sess.name,
        phone="9876543210"
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def create_test_supervisor(db: Session, suffix: str) -> Supervisor:
    dept = db.query(Department).first()
    user = User(
        username=f"SUP_P5_{suffix}",
        email=f"sup_p5_{suffix}@spms.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED,
        session_version=1
    )
    db.add(user)
    db.flush()
    supervisor = Supervisor(
        user_id=user.id,
        department_id=dept.id,
        full_name=f"Prof P5 {suffix}",
        designation="Associate Professor",
        max_slots=4
    )
    db.add(supervisor)
    db.commit()
    db.refresh(supervisor)
    return supervisor


def create_test_coordinator(db: Session, suffix: str) -> User:
    user = User(
        username=f"COORD_P5_{suffix}",
        email=f"coord_p5_{suffix}@spms.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.ADMIN,
        status=AccountStatusEnum.APPROVED,
        session_version=1
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_assigned_project(db: Session, student: Student, supervisor: Supervisor, suffix: str) -> TopicAssignment:
    topic = Topic(
        title=f"Quantum AI Cryptography {suffix}",
        normalized_title=f"quantum ai cryptography {suffix}",
        description="Exploration of post-quantum cryptographic primitives.",
        domain="Cybersecurity",
        department_id=student.department_id,
        session_id=student.session_id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=supervisor.user_id,
        status=TopicStatusEnum.ASSIGNED
    )
    db.add(topic)
    db.flush()

    assign = TopicAssignment(
        topic_id=topic.id,
        student_id=student.id,
        supervisor_id=supervisor.id,
        session_id=student.session_id,
        status=AssignmentStatusEnum.ACTIVE,
        github_url="https://github.com/alice/quantum-crypto",
        github_url_locked=False
    )
    db.add(assign)
    db.commit()
    db.refresh(assign)
    return assign


def approve_all_chapters_up_to_final_report(db: Session, assignment: TopicAssignment, supervisor: Supervisor):
    """Creates approved submissions for Synopsis, SRS, Implementation, and Final Report."""
    chapters = [
        ChapterEnum.SYNOPSIS,
        ChapterEnum.SRS_DESIGN,
        ChapterEnum.IMPLEMENTATION,
        ChapterEnum.FINAL_REPORT
    ]
    for ch in chapters:
        sub = Submission(
            assignment_id=assignment.id,
            chapter=ch,
            version=1,
            file_path="storage/submissions/dummy_report.pdf",
            original_filename=f"{ch.value.lower()}_v1.pdf",
            file_size=1024,
            submitted_at=utc_now()
        )
        db.add(sub)
        db.flush()
        fb = Feedback(
            submission_id=sub.id,
            supervisor_id=supervisor.id,
            status=FeedbackStatusEnum.APPROVED,
            comments=f"Excellent {ch.value} document.",
            created_at=utc_now()
        )
        db.add(fb)
    assignment.github_url_locked = True
    db.commit()


def login_client(client: TestClient, username: str, password: str = "Pass123!"):
    client.cookies.clear()
    login_page = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    res = client.post("/auth/login", data={"username": username, "password": password, "csrf_token": csrf})
    assert res.status_code in (200, 303)


# ============================================================================
# TESTS
# ============================================================================

def test_scoring_blocked_before_final_report_approval(client: TestClient, db_session: Session):
    """Scoring is strictly blocked until the Final Report chapter is in status APPROVED."""
    suffix = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix)
    supervisor = create_test_supervisor(db_session, suffix)
    assign = create_assigned_project(db_session, student, supervisor, suffix)

    # Approve only Synopsis and SRS
    for ch in [ChapterEnum.SYNOPSIS, ChapterEnum.SRS_DESIGN]:
        sub = Submission(
            assignment_id=assign.id,
            chapter=ch,
            version=1,
            file_path="storage/dummy.pdf",
            original_filename="dummy.pdf",
            file_size=500
        )
        db_session.add(sub)
        db_session.flush()
        fb = Feedback(
            submission_id=sub.id,
            supervisor_id=supervisor.id,
            status=FeedbackStatusEnum.APPROVED,
            comments="Approved"
        )
        db_session.add(fb)
    db_session.commit()

    login_client(client, supervisor.user.username)

    # GET grading form before final report approval -> 400
    res_get = client.get(f"/assessments/{assign.id}/grade")
    assert res_get.status_code == 400
    assert "Final Report has not been approved" in res_get.text

    # POST grading marks before final report approval -> 400
    form_page = client.get("/assessments")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', form_page.text).group(1)
    res_post = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 25.0,
            "report_score": 25.0,
            "implementation_score": 35.0,
            "supervisor_remarks": "Premature grading attempt",
            "csrf_token": csrf
        }
    )
    assert res_post.status_code == 400
    assert "Final Report has not been approved" in res_post.text


def test_non_owner_supervisor_id_tampering_gets_403(client: TestClient, db_session: Session):
    """Only the student's assigned supervisor may score the assignment (ID tampering -> 403)."""
    suffix1 = uuid.uuid4().hex[:8]
    suffix2 = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix1)
    sup_owner = create_test_supervisor(db_session, suffix1)
    sup_attacker = create_test_supervisor(db_session, suffix2)

    assign = create_assigned_project(db_session, student, sup_owner, suffix1)
    approve_all_chapters_up_to_final_report(db_session, assign, sup_owner)

    # Attacker supervisor logs in
    login_client(client, sup_attacker.user.username)

    # Attacker tries to access grading form for assign -> 403
    res_get = client.get(f"/assessments/{assign.id}/grade")
    assert res_get.status_code == 403
    assert "Forbidden" in res_get.text or "not the assigned supervisor" in res_get.text

    # Attacker tries to POST marks -> 403
    assess_page = client.get("/assessments")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', assess_page.text).group(1)
    res_post = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 20.0,
            "report_score": 20.0,
            "implementation_score": 30.0,
            "supervisor_remarks": "Malicious score injection",
            "csrf_token": csrf
        }
    )
    assert res_post.status_code == 403


def test_score_range_validation_and_server_side_total(client: TestClient, db_session: Session):
    """Validates score ranges (0-30, 0-30, 0-40) and verifies server computes total score."""
    suffix = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix)
    supervisor = create_test_supervisor(db_session, suffix)
    assign = create_assigned_project(db_session, student, supervisor, suffix)
    approve_all_chapters_up_to_final_report(db_session, assign, supervisor)

    login_client(client, supervisor.user.username)
    grade_page = client.get(f"/assessments/{assign.id}/grade")
    assert grade_page.status_code == 200
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', grade_page.text).group(1)

    # Test 1: Presentation score > 30 -> 400
    res1 = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 35.0,
            "report_score": 25.0,
            "implementation_score": 35.0,
            "csrf_token": csrf
        }
    )
    assert res1.status_code == 400
    assert "Presentation score must be between 0.0 and 30.0" in res1.text

    # Test 2: Report score < 0 -> 400
    res2 = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 25.0,
            "report_score": -5.0,
            "implementation_score": 35.0,
            "csrf_token": csrf
        }
    )
    assert res2.status_code == 400
    assert "Report score must be between 0.0 and 30.0" in res2.text

    # Test 3: Implementation score > 40 -> 400
    res3 = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 25.0,
            "report_score": 25.0,
            "implementation_score": 45.0,
            "csrf_token": csrf
        }
    )
    assert res3.status_code == 400
    assert "Implementation score must be between 0.0 and 40.0" in res3.text

    # Test 4: Valid scores -> Server computes total_score = 25.5 + 28.0 + 36.5 = 90.0
    res4 = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 25.5,
            "report_score": 28.0,
            "implementation_score": 36.5,
            "supervisor_remarks": "Outstanding demonstration and thorough testing.",
            "csrf_token": csrf
        },
        follow_redirects=True
    )
    assert res4.status_code == 200

    # Verify database persistence & server total
    db_session.commit()
    assessment = db_session.query(Assessment).filter(Assessment.assignment_id == assign.id).first()
    assert assessment is not None
    assert float(assessment.presentation_score) == 25.5
    assert float(assessment.report_score) == 28.0
    assert float(assessment.implementation_score) == 36.5
    assert float(assessment.total_score) == 90.0
    assert assessment.supervisor_remarks == "Outstanding demonstration and thorough testing."


def test_coordinator_finalization_immutability_and_archive(client: TestClient, db_session: Session):
    """Coordinator finalizes grade: marks assignment COMPLETED, topic ARCHIVED, and locks edits."""
    suffix = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix)
    supervisor = create_test_supervisor(db_session, suffix)
    assign = create_assigned_project(db_session, student, supervisor, suffix)
    approve_all_chapters_up_to_final_report(db_session, assign, supervisor)

    # Supervisor scores
    assessment = Assessment(
        assignment_id=assign.id,
        supervisor_id=supervisor.id,
        presentation_score=27.0,
        report_score=28.0,
        implementation_score=38.0,
        total_score=93.0,
        supervisor_remarks="Exceptional defense."
    )
    db_session.add(assessment)
    db_session.commit()
    db_session.refresh(assessment)

    # Coordinator logs in
    admin = create_test_coordinator(db_session, suffix)
    login_client(client, admin.username)

    finalize_page = client.get(f"/coordinator/assessments/{assessment.id}/finalize")
    assert finalize_page.status_code == 200
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', finalize_page.text).group(1)

    # Finalize grade as A+
    res_finalize = client.post(
        f"/coordinator/assessments/{assessment.id}/finalize",
        data={
            "coordinator_final_grade": "A+",
            "csrf_token": csrf
        },
        follow_redirects=True
    )
    assert res_finalize.status_code == 200

    # Verify Database state
    db_session.commit()
    updated_assessment = db_session.query(Assessment).filter(Assessment.id == assessment.id).first()
    assert updated_assessment.coordinator_final_grade == "A+"
    assert updated_assessment.finalized_by_user_id == admin.id
    assert updated_assessment.finalized_at is not None

    updated_assign = db_session.query(TopicAssignment).filter(TopicAssignment.id == assign.id).first()
    assert updated_assign.status == AssignmentStatusEnum.COMPLETED
    assert updated_assign.completed_at is not None

    updated_topic = db_session.query(Topic).filter(Topic.id == assign.topic_id).first()
    assert updated_topic.status == TopicStatusEnum.ARCHIVED

    # IMMUTABILITY TEST: Attempting to re-finalize or edit finalized assessment -> 400 Bad Request
    res_refinalize = client.post(
        f"/coordinator/assessments/{assessment.id}/finalize",
        data={
            "coordinator_final_grade": "B",
            "csrf_token": csrf
        }
    )
    assert res_refinalize.status_code == 400
    assert "Assessment has already been finalized and cannot be modified" in res_refinalize.text

    # Supervisor attempting to modify finalized assessment marks -> 400 Bad Request
    login_client(client, supervisor.user.username)
    assess_page = client.get("/assessments")
    sup_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', assess_page.text).group(1)
    res_sup_edit = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 10.0,
            "report_score": 10.0,
            "implementation_score": 10.0,
            "csrf_token": sup_csrf
        }
    )
    assert res_sup_edit.status_code == 400
    assert "Assessment has already been finalized" in res_sup_edit.text


def test_archive_search_filtering_and_privacy_boundaries(client: TestClient, db_session: Session):
    """Archived projects are searchable/filterable; student personal data is NEVER exposed."""
    suffix = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix)
    supervisor = create_test_supervisor(db_session, suffix)
    assign = create_assigned_project(db_session, student, supervisor, suffix)
    approve_all_chapters_up_to_final_report(db_session, assign, supervisor)

    admin = db_session.query(User).filter(User.role == RoleEnum.ADMIN).first()
    now = utc_now()

    # Complete and archive project
    assign.status = AssignmentStatusEnum.COMPLETED
    assign.completed_at = now
    assign.topic.status = TopicStatusEnum.ARCHIVED
    assessment = Assessment(
        assignment_id=assign.id,
        supervisor_id=supervisor.id,
        presentation_score=26.0,
        report_score=27.0,
        implementation_score=36.0,
        total_score=89.0,
        coordinator_final_grade="A",
        finalized_by_user_id=admin.id,
        finalized_at=now
    )
    db_session.add(assessment)
    db_session.commit()

    # Log in as a student (viewing archive)
    another_student = create_test_student(db_session, uuid.uuid4().hex[:8])
    login_client(client, another_student.user.username)

    # Search keyword
    res = client.get(f"/archive?q=Cryptography+{suffix}")
    assert res.status_code == 200
    body = res.text

    # Topic title and metadata present
    assert assign.topic.title in body
    assert supervisor.full_name in body
    assert "Grade: A" in body
    assert "View Code Repository" in body or assign.github_url in body

    # STRICT PRIVACY BOUNDARY ASSERTIONS:
    # Student's USN, phone, email, and password must NEVER appear in the public archive HTML
    assert student.usn not in body
    assert student.phone not in body
    assert student.user.email not in body
    assert student.user.password_hash not in body

    # Detail view test & strict privacy boundary
    res_detail = client.get(f"/archive/{assign.topic.id}")
    assert res_detail.status_code == 200
    detail_body = res_detail.text
    assert assign.topic.title in detail_body
    assert supervisor.full_name in detail_body
    assert "Grade: A" in detail_body
    assert student.usn not in detail_body
    assert student.phone not in detail_body
    assert student.user.email not in detail_body


def test_duplicate_detector_flags_archived_topic(client: TestClient, db_session: Session):
    """A new topic matching an ARCHIVED topic is detected and flagged by duplicate detector."""
    suffix = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix)
    supervisor = create_test_supervisor(db_session, suffix)
    assign = create_assigned_project(db_session, student, supervisor, suffix)

    # Set status to ARCHIVED
    assign.topic.status = TopicStatusEnum.ARCHIVED
    db_session.commit()

    # Check duplicate detection on exact and reworded title
    is_dup, score, conflict = check_topic_duplicate(db_session, assign.topic.title)
    assert is_dup is True
    assert score >= 0.75
    assert conflict == assign.topic.title

    # Minor reword
    reworded = f"A Study of Quantum AI Cryptography {suffix}"
    is_dup2, score2, conflict2 = check_topic_duplicate(db_session, reworded)
    assert is_dup2 is True
    assert score2 >= 0.70
    assert conflict2 == assign.topic.title


def test_dashboard_rendering_per_role(client: TestClient, db_session: Session):
    """All 3 role dashboards render the new milestone stepper, slot gauge, and compliance cards."""
    suffix = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix)
    supervisor = create_test_supervisor(db_session, suffix)
    assign = create_assigned_project(db_session, student, supervisor, suffix)
    admin = create_test_coordinator(db_session, suffix)

    # 1. Student Dashboard
    login_client(client, student.user.username)
    res_student = client.get("/dashboard")
    assert res_student.status_code == 200
    assert "Project Milestone Progress" in res_student.text
    assert "1. Synopsis" in res_student.text
    assert "2. SRS and Design" in res_student.text
    assert "3. Implementation" in res_student.text
    assert "4. Final Report" in res_student.text
    assert supervisor.full_name in res_student.text
    assert "Current Project Status" in res_student.text

    # 2. Supervisor Dashboard
    login_client(client, supervisor.user.username)
    res_sup = client.get("/dashboard")
    assert res_sup.status_code == 200
    assert "Supervisory Slot Gauge" in res_sup.text
    assert "progress-bar" in res_sup.text
    assert "Assigned Students" in res_sup.text
    assert student.full_name in res_sup.text
    assert "Review Submissions" in res_sup.text

    # 3. Coordinator Dashboard
    login_client(client, admin.username)
    res_admin = client.get("/dashboard")
    assert res_admin.status_code == 200
    assert "Coordinator Control Center" in res_admin.text
    assert "Assessments to Finalize" in res_admin.text
    assert "Deadline Compliance" in res_admin.text
    assert "System Capacity" in res_admin.text
    assert "Academic Metrics" in res_admin.text


def test_csrf_protection_on_phase5_post_routes(client: TestClient, db_session: Session):
    """POST routes in Phase 5 reject requests missing a valid CSRF token with 403 Forbidden."""
    suffix = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix)
    supervisor = create_test_supervisor(db_session, suffix)
    assign = create_assigned_project(db_session, student, supervisor, suffix)
    approve_all_chapters_up_to_final_report(db_session, assign, supervisor)

    assessment = Assessment(
        assignment_id=assign.id,
        supervisor_id=supervisor.id,
        presentation_score=25.0,
        report_score=25.0,
        implementation_score=35.0,
        total_score=85.0
    )
    db_session.add(assessment)
    db_session.commit()
    db_session.refresh(assessment)

    # 1. Supervisor grading without CSRF -> 403
    login_client(client, supervisor.user.username)
    res1 = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 25.0,
            "report_score": 25.0,
            "implementation_score": 35.0
        }
    )
    assert res1.status_code == 403
    assert "Invalid CSRF token" in res1.text

    # 2. Coordinator finalization without CSRF -> 403
    admin = create_test_coordinator(db_session, suffix)
    login_client(client, admin.username)
    res2 = client.post(
        f"/coordinator/assessments/{assessment.id}/finalize",
        data={
            "coordinator_final_grade": "A"
        }
    )
    assert res2.status_code == 403
    assert "Invalid CSRF token" in res2.text


def test_xss_sanitization_in_remarks_and_archive(client: TestClient, db_session: Session):
    """XSS payloads in supervisor remarks and archive queries are safely escaped."""
    suffix = uuid.uuid4().hex[:8]
    student = create_test_student(db_session, suffix)
    supervisor = create_test_supervisor(db_session, suffix)
    assign = create_assigned_project(db_session, student, supervisor, suffix)
    approve_all_chapters_up_to_final_report(db_session, assign, supervisor)

    login_client(client, supervisor.user.username)
    grade_page = client.get(f"/assessments/{assign.id}/grade")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', grade_page.text).group(1)

    xss_payload = "<script>alert('XSS_REMARKS')</script><b>BoldRemarks</b>"
    res = client.post(
        f"/assessments/{assign.id}/grade",
        data={
            "presentation_score": 25.0,
            "report_score": 25.0,
            "implementation_score": 35.0,
            "supervisor_remarks": xss_payload,
            "csrf_token": csrf
        },
        follow_redirects=True
    )
    assert res.status_code == 200

    # View as student -> Verify XSS is escaped
    login_client(client, student.user.username)
    student_view = client.get("/assessments")
    assert student_view.status_code == 200
    assert "<script>alert('XSS_REMARKS')</script>" not in student_view.text
    assert "&lt;script&gt;alert(&#39;XSS_REMARKS&#39;)&lt;/script&gt;" in student_view.text or "&lt;script&gt;" in student_view.text

    # Archive search XSS query
    archive_xss = client.get("/archive?q=<script>alert('ARCHIVE_XSS')</script>")
    assert archive_xss.status_code == 200
    assert "<script>alert('ARCHIVE_XSS')</script>" not in archive_xss.text
    assert "&lt;script&gt;" in archive_xss.text
