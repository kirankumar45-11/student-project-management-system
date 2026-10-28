import io
import re
import uuid
import zipfile
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
from app.core.security import hash_password
from app.core.datetime_util import utc_now
from app.routers.submissions import validate_github_url, MAX_SUBMISSION_FILE_SIZE


# ============================================================================
# HELPER FACTORIES
# ============================================================================
def create_test_student(db: Session, suffix: str) -> Student:
    dept = db.query(Department).first()
    sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    user = User(
        username=f"STU_{suffix}",
        email=f"stu_{suffix}@spms.local",
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
        full_name=f"Student {suffix}",
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
        username=f"SUP_{suffix}",
        email=f"sup_{suffix}@spms.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED,
        session_version=1
    )
    db.add(user)
    db.flush()
    sup = Supervisor(
        user_id=user.id,
        department_id=dept.id,
        full_name=f"Dr. Supervisor {suffix}",
        designation="Associate Professor",
        max_slots=10
    )
    db.add(sup)
    db.commit()
    db.refresh(sup)
    return sup


def create_test_coordinator(db: Session, suffix: str) -> User:
    user = User(
        username=f"COORD_{suffix}",
        email=f"coord_{suffix}@spms.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.ADMIN,
        status=AccountStatusEnum.APPROVED,
        session_version=1
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_active_assignment(db: Session, student: Student, supervisor: Supervisor, suffix: str) -> TopicAssignment:
    topic = Topic(
        title=f"Autonomous Robotics {suffix}",
        normalized_title=f"autonomous robotics {suffix}",
        description="Autonomous mobile robotic exploration and SLAM.",
        domain="Robotics",
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
        github_url="https://github.com/alice/robotics-slam",
        github_url_locked=False
    )
    db.add(assign)
    db.commit()
    db.refresh(assign)
    return assign


def login_client(client: TestClient, username: str, password: str = "Pass123!"):
    client.cookies.clear()
    login_page = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    res = client.post("/auth/login", data={"username": username, "password": password, "csrf_token": csrf})
    assert res.status_code in (200, 303)


# ============================================================================
# TESTS
# ============================================================================
def test_github_url_validation_and_locking(client: TestClient, db_session: Session):
    """
    Verifies GitHub URL validation:
    1. Valid format: https://github.com/user/repo
    2. Invalid formats rejected: wrong host, extra subpaths, javascript scheme, invalid symbols.
    3. Locking prevents modifications after Final Report is approved.
    """
    # 1. Unit tests
    assert validate_github_url("https://github.com/alice/project") is True
    assert validate_github_url("https://github.com/alice/project/") is True
    assert validate_github_url("https://github.com/alice-123/my.project_repo") is True
    assert validate_github_url("https://gitlab.com/alice/project") is False  # wrong host
    assert validate_github_url("http://github.com/alice/project") is False   # http not https
    assert validate_github_url("https://github.com/alice/project/tree/main") is False  # extra path
    assert validate_github_url("javascript:alert(1)") is False  # javascript scheme
    assert validate_github_url("https://github.com/alice") is False  # missing repo

    # 2. Integration with student account
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    login_client(client, stu.user.username)

    # Valid update
    subs_page = client.get("/submissions")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page.text).group(1)
    res = client.post(
        "/submissions/github-url",
        data={"github_url": "https://github.com/bob/spms-v2", "csrf_token": csrf},
        follow_redirects=True
    )
    assert res.status_code == 200
    db_session.rollback()
    refreshed = db_session.query(TopicAssignment).filter(TopicAssignment.id == assign.id).first()
    assert refreshed.github_url == "https://github.com/bob/spms-v2"

    # Invalid update: wrong host
    res = client.post(
        "/submissions/github-url",
        data={"github_url": "https://bitbucket.org/bob/repo", "csrf_token": csrf}
    )
    assert res.status_code == 400
    assert "Invalid GitHub repository URL" in res.text

    # Lock assignment and verify modification is rejected
    refreshed.github_url_locked = True
    db_session.commit()

    res = client.post(
        "/submissions/github-url",
        data={"github_url": "https://github.com/bob/locked-repo", "csrf_token": csrf}
    )
    assert res.status_code == 400
    assert "locked after Final Report approval" in res.text


def test_file_upload_validation_and_magic_byte_rejection(client: TestClient, db_session: Session):
    """
    Verifies upload validation:
    1. Valid PDF with %PDF- header accepted.
    2. Executable .exe rejected.
    3. Renamed file (e.g. .exe renamed to .pdf) rejected by magic bytes.
    4. Over-10MB file rejected.
    """
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    login_client(client, stu.user.username)
    subs_page = client.get("/submissions")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page.text).group(1)

    # 1. Valid PDF upload
    valid_pdf = b"%PDF-1.4\n1 0 obj\n<< /Title (Synopsis Document) >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("synopsis.pdf", valid_pdf, "application/pdf")},
        data={"csrf_token": csrf},
        follow_redirects=True
    )
    assert res.status_code == 200
    db_session.rollback()
    sub = db_session.query(Submission).filter(
        Submission.assignment_id == assign.id,
        Submission.chapter == ChapterEnum.SYNOPSIS
    ).first()
    assert sub is not None
    assert sub.version == 1
    assert sub.original_filename == "synopsis.pdf"

    # 2. Reject executable (.exe)
    exe_content = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("malicious.exe", exe_content, "application/octet-stream")},
        data={"csrf_token": csrf}
    )
    assert res.status_code == 400
    assert "Only PDF, DOC, and DOCX files are permitted" in res.text

    # 3. Reject renamed executable masquerading as PDF (.pdf)
    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("sneaky.pdf", exe_content, "application/pdf")},
        data={"csrf_token": csrf}
    )
    assert res.status_code == 400
    assert "Invalid PDF file header" in res.text

    # 4. Reject over-10MB file
    oversized = b"%PDF-" + b"0" * (10 * 1024 * 1024 + 1024)
    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("huge.pdf", oversized, "application/pdf")},
        data={"csrf_token": csrf}
    )
    assert res.status_code == 400
    assert "exceeds maximum allowed size of 10 MB" in res.text


def test_sequential_chapter_blocking(client: TestClient, db_session: Session):
    """
    Verifies that Chapter 2 (SRS_DESIGN) cannot be submitted until Chapter 1 (SYNOPSIS)
    is approved.
    """
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    login_client(client, stu.user.username)
    subs_page = client.get("/submissions")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page.text).group(1)

    valid_pdf = b"%PDF-1.4\nSRS Content\n%%EOF"

    # Attempt to upload SRS_DESIGN without approved Synopsis
    res = client.post(
        "/submissions/SRS_DESIGN/upload",
        files={"file": ("srs.pdf", valid_pdf, "application/pdf")},
        data={"csrf_token": csrf}
    )
    assert res.status_code == 400
    assert "You must have an approved submission for Synopsis before submitting SRS and Design" in res.text

    # Attempt to upload FINAL_REPORT
    res = client.post(
        "/submissions/FINAL_REPORT/upload",
        files={"file": ("report.pdf", valid_pdf, "application/pdf")},
        data={"csrf_token": csrf}
    )
    assert res.status_code == 400
    assert "You must have an approved submission for Implementation before submitting Final Report" in res.text


def test_deadlines_and_late_submission_behavior(client: TestClient, db_session: Session):
    """
    Verifies deadline enforcement:
    1. Deadline in the past with allow_late=False blocks submission (HTTP 400).
    2. Deadline in the past with allow_late=True accepts submission with is_late=True.
    """
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    # 1. Past deadline with allow_late=False
    db_session.query(Deadline).filter(
        Deadline.session_id == stu.session_id,
        Deadline.chapter == ChapterEnum.SYNOPSIS
    ).delete()
    db_session.commit()

    past_due = utc_now() - timedelta(days=2)
    dl = Deadline(
        session_id=stu.session_id,
        chapter=ChapterEnum.SYNOPSIS,
        title="Synopsis Strict Deadline",
        description="No late submissions allowed",
        due_date=past_due,
        allow_late=False
    )
    db_session.add(dl)
    db_session.commit()

    login_client(client, stu.user.username)
    subs_page = client.get("/submissions")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page.text).group(1)

    valid_pdf = b"%PDF-1.4\nSynopsis\n%%EOF"
    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("synopsis.pdf", valid_pdf, "application/pdf")},
        data={"csrf_token": csrf}
    )
    assert res.status_code == 400
    assert "deadline for Synopsis passed" in res.text
    assert "late submissions are not allowed" in res.text

    # 2. Update deadline to allow_late=True
    dl.allow_late = True
    db_session.commit()

    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("synopsis.pdf", valid_pdf, "application/pdf")},
        data={"csrf_token": csrf},
        follow_redirects=True
    )
    assert res.status_code == 200

    db_session.rollback()
    sub = db_session.query(Submission).filter(
        Submission.assignment_id == assign.id,
        Submission.chapter == ChapterEnum.SYNOPSIS
    ).first()
    assert sub is not None
    assert sub.is_late is True  # Late flag set!


def test_authenticated_download_access_control(client: TestClient, db_session: Session):
    """
    Verifies that only authorized users (assigned student, assigned supervisor, coordinator)
    can download the submission file. Other students or supervisors receive HTTP 403.
    """
    uid = uuid.uuid4().hex[:6]
    stuA = create_test_student(db_session, f"{uid}A")
    supA = create_test_supervisor(db_session, f"{uid}A")
    assignA = create_active_assignment(db_session, stuA, supA, f"{uid}A")

    # Another student & supervisor
    stuB = create_test_student(db_session, f"{uid}B")
    supB = create_test_supervisor(db_session, f"{uid}B")

    # Seed submission for Student A
    sub = Submission(
        assignment_id=assignA.id,
        chapter=ChapterEnum.SYNOPSIS,
        version=1,
        file_path="storage/submissions/test_dummy.pdf",
        original_filename="Test_Doc.pdf",
        file_size=1024,
        is_late=False
    )
    db_session.add(sub)
    db_session.commit()

    # Create dummy file on filesystem
    from pathlib import Path
    Path("storage/submissions").mkdir(parents=True, exist_ok=True)
    Path("storage/submissions/test_dummy.pdf").write_bytes(b"%PDF-1.4\nTest\n%%EOF")

    # 1. Assigned Student A downloads -> 200 OK
    login_client(client, stuA.user.username)
    res = client.get(f"/submissions/{sub.id}/download")
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith('attachment; filename="Test_Doc.pdf"')

    # 2. Assigned Supervisor A downloads -> 200 OK
    login_client(client, supA.user.username)
    res = client.get(f"/submissions/{sub.id}/download")
    assert res.status_code == 200

    # 3. Unrelated Student B downloads -> 403 Forbidden
    login_client(client, stuB.user.username)
    res = client.get(f"/submissions/{sub.id}/download")
    assert res.status_code == 403
    assert "not authorized to download" in res.text

    # 4. Unrelated Supervisor B downloads -> 403 Forbidden
    login_client(client, supB.user.username)
    res = client.get(f"/submissions/{sub.id}/download")
    assert res.status_code == 403
    assert "not authorized to download" in res.text

    # 5. Coordinator (Admin) downloads -> 200 OK
    coord = create_test_coordinator(db_session, uid)
    login_client(client, coord.username)
    res = client.get(f"/submissions/{sub.id}/download")
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith('attachment; filename="Test_Doc.pdf"')


def test_supervisor_review_id_tampering_and_isolation(client: TestClient, db_session: Session):
    """
    Verifies server-side check that a supervisor can only review and provide feedback
    for their own assigned students. Tampering with submission ID returns HTTP 403.
    """
    uid = uuid.uuid4().hex[:6]
    stuA = create_test_student(db_session, f"{uid}A")
    supA = create_test_supervisor(db_session, f"{uid}A")
    assignA = create_active_assignment(db_session, stuA, supA, f"{uid}A")

    supB = create_test_supervisor(db_session, f"{uid}B")

    # Seed submission for Student A
    sub = Submission(
        assignment_id=assignA.id,
        chapter=ChapterEnum.SYNOPSIS,
        version=1,
        file_path="storage/submissions/tamper_test.pdf",
        original_filename="Synopsis.pdf",
        file_size=512,
        is_late=False
    )
    db_session.add(sub)
    db_session.commit()

    # Login as Supervisor B (unauthorized for this student)
    login_client(client, supB.user.username)

    # 1. GET Review page -> 403 Forbidden
    res = client.get(f"/submissions/{sub.id}/review")
    assert res.status_code == 403
    assert "You are not the assigned supervisor for this student" in res.text

    # 2. POST Feedback -> 403 Forbidden
    dash = client.get("/dashboard")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', dash.text).group(1)
    res = client.post(
        f"/submissions/{sub.id}/feedback",
        data={"status": "APPROVED", "comments": "Unauthorized approval attempt", "csrf_token": csrf}
    )
    assert res.status_code == 403
    assert "You are not the assigned supervisor for this student" in res.text


def test_version_history_after_resubmission_and_approval_flow(client: TestClient, db_session: Session):
    """
    Verifies full lifecycle with resubmissions and versions:
    1. Student submits Synopsis v1.
    2. Supervisor reviews and submits NEEDS_REVISION.
    3. Student resubmits Synopsis -> creates v2.
    4. Full history contains both v1 (with revision feedback) and v2.
    5. Supervisor reviews and submits APPROVED.
    6. Chapter 2 (SRS_DESIGN) is unlocked.
    """
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    # 1. Student uploads Synopsis v1
    login_client(client, stu.user.username)
    subs_page = client.get("/submissions")
    csrf_stu = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page.text).group(1)

    valid_pdf_v1 = b"%PDF-1.4\nSynopsis Version 1\n%%EOF"
    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("synopsis_v1.pdf", valid_pdf_v1, "application/pdf")},
        data={"csrf_token": csrf_stu},
        follow_redirects=True
    )
    assert res.status_code == 200

    db_session.rollback()
    v1 = db_session.query(Submission).filter(
        Submission.assignment_id == assign.id,
        Submission.chapter == ChapterEnum.SYNOPSIS,
        Submission.version == 1
    ).first()
    assert v1 is not None

    # 2. Supervisor reviews v1 with NEEDS_REVISION
    login_client(client, sup.user.username)
    rev_page = client.get(f"/submissions/{v1.id}/review")
    csrf_sup = re.search(r'name="csrf_token"\s+value="([^"]+)"', rev_page.text).group(1)

    res = client.post(
        f"/submissions/{v1.id}/feedback",
        data={
            "status": "NEEDS_REVISION",
            "comments": "Please refine the scope and literature survey.",
            "csrf_token": csrf_sup
        },
        follow_redirects=True
    )
    assert res.status_code == 200

    # 3. Student uploads Synopsis v2
    login_client(client, stu.user.username)
    subs_page = client.get("/submissions")
    csrf_stu_v2 = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page.text).group(1)

    valid_pdf_v2 = b"%PDF-1.4\nSynopsis Version 2 Fixed\n%%EOF"
    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("synopsis_v2.pdf", valid_pdf_v2, "application/pdf")},
        data={"csrf_token": csrf_stu_v2},
        follow_redirects=True
    )
    assert res.status_code == 200

    # 4. Verify version history in DB
    db_session.rollback()
    all_subs = db_session.query(Submission).filter(
        Submission.assignment_id == assign.id,
        Submission.chapter == ChapterEnum.SYNOPSIS
    ).order_by(Submission.version.asc()).all()
    assert len(all_subs) == 2
    assert all_subs[0].version == 1
    assert all_subs[0].feedback[0].status == FeedbackStatusEnum.NEEDS_REVISION
    assert all_subs[1].version == 2

    # 5. Supervisor approves v2
    login_client(client, sup.user.username)
    rev_page_v2 = client.get(f"/submissions/{all_subs[1].id}/review")
    csrf_sup_v2 = re.search(r'name="csrf_token"\s+value="([^"]+)"', rev_page_v2.text).group(1)

    res = client.post(
        f"/submissions/{all_subs[1].id}/feedback",
        data={
            "status": "APPROVED",
            "comments": "Revisions look great. Approved!",
            "csrf_token": csrf_sup_v2
        },
        follow_redirects=True
    )
    assert res.status_code == 200

    # 6. Student can now upload SRS_DESIGN!
    login_client(client, stu.user.username)
    subs_page_v3 = client.get("/submissions")
    csrf_stu_v3 = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page_v3.text).group(1)

    srs_pdf = b"%PDF-1.4\nSRS Document\n%%EOF"
    res = client.post(
        "/submissions/SRS_DESIGN/upload",
        files={"file": ("srs_v1.pdf", srs_pdf, "application/pdf")},
        data={"csrf_token": csrf_stu_v3},
        follow_redirects=True
    )
    assert res.status_code == 200
    db_session.rollback()
    srs_sub = db_session.query(Submission).filter(
        Submission.assignment_id == assign.id,
        Submission.chapter == ChapterEnum.SRS_DESIGN
    ).first()
    assert srs_sub is not None
    assert srs_sub.version == 1


def test_final_report_approval_locks_github_url(client: TestClient, db_session: Session):
    """
    Verifies that when a supervisor approves the FINAL_REPORT milestone:
    1. The assignment's github_url_locked flag is set to True.
    2. completed_at timestamp is set.
    3. The student can no longer modify the GitHub URL.
    """
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    # Seed Final Report submission
    final_sub = Submission(
        assignment_id=assign.id,
        chapter=ChapterEnum.FINAL_REPORT,
        version=1,
        file_path="storage/submissions/final_rep.pdf",
        original_filename="Final_Thesis.pdf",
        file_size=2048,
        is_late=False
    )
    db_session.add(final_sub)
    db_session.commit()

    # Supervisor approves Final Report
    login_client(client, sup.user.username)
    dash = client.get("/dashboard")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', dash.text).group(1)

    res = client.post(
        f"/submissions/{final_sub.id}/feedback",
        data={
            "status": "APPROVED",
            "comments": "Final project approved with distinction.",
            "csrf_token": csrf
        },
        follow_redirects=True
    )
    assert res.status_code == 200

    # Verify assignment lock
    db_session.rollback()
    refreshed_assign = db_session.query(TopicAssignment).filter(TopicAssignment.id == assign.id).first()
    assert refreshed_assign.github_url_locked is True
    assert refreshed_assign.completed_at is not None

    # Student attempts to edit locked GitHub URL -> 400 Bad Request
    login_client(client, stu.user.username)
    subs_page = client.get("/submissions")
    csrf_stu = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page.text).group(1)
    res = client.post(
        "/submissions/github-url",
        data={"github_url": "https://github.com/alice/new-repo", "csrf_token": csrf_stu}
    )
    assert res.status_code == 400
    assert "locked after Final Report approval" in res.text


def test_csrf_rejection_on_all_phase4_post_routes(client: TestClient, db_session: Session):
    """
    Verifies that every new POST endpoint in Phase 4 rejects requests missing a valid CSRF token.
    """
    # 1. /coordinator/deadlines
    res = client.post(
        "/coordinator/deadlines",
        data={"session_id": 1, "chapter": "SYNOPSIS", "title": "Test", "due_date": "2026-12-31 23:59:00"}
    )
    assert res.status_code == 403

    # 2. /coordinator/deadlines/{id}/delete
    res = client.post("/coordinator/deadlines/1/delete", data={})
    assert res.status_code == 403

    # 3. /submissions/github-url
    res = client.post("/submissions/github-url", data={"github_url": "https://github.com/a/b"})
    assert res.status_code == 403

    # 4. /submissions/{chapter}/upload
    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("dummy.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={}
    )
    assert res.status_code == 403

    # 5. /submissions/{id}/feedback
    res = client.post(
        "/submissions/1/feedback",
        data={"status": "APPROVED", "comments": "Test"}
    )
    assert res.status_code == 403


def test_xss_in_feedback_comments_rendered_as_plain_text(client: TestClient, db_session: Session):
    """
    Verifies that XSS payloads in supervisor feedback comments are auto-escaped as plain text.
    """
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    sub = Submission(
        assignment_id=assign.id,
        chapter=ChapterEnum.SYNOPSIS,
        version=1,
        file_path="storage/submissions/xss_doc.pdf",
        original_filename="Synopsis.pdf",
        file_size=512,
        is_late=False
    )
    db_session.add(sub)
    db_session.commit()

    xss_payload = f"<script>alert('xss-feedback-{uid}')</script>"
    fb = Feedback(
        submission_id=sub.id,
        supervisor_id=sup.id,
        status=FeedbackStatusEnum.NEEDS_REVISION,
        comments=xss_payload
    )
    db_session.add(fb)
    db_session.commit()

    # View as student on /submissions
    login_client(client, stu.user.username)
    res = client.get("/submissions")
    assert res.status_code == 200
    assert xss_payload not in res.text
    assert f"&lt;script&gt;alert(&#39;xss-feedback-{uid}&#39;)&lt;/script&gt;" in res.text or "&lt;script&gt;" in res.text


def test_coordinator_can_download_any_submission(client: TestClient, db_session: Session):
    """
    Explicitly verifies that the coordinator (Admin) can download any student submission
    regardless of department, assignment ownership, or supervisor pairing.
    """
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    sub = Submission(
        assignment_id=assign.id,
        chapter=ChapterEnum.FINAL_REPORT,
        version=1,
        file_path="storage/submissions/coord_doc.pdf",
        original_filename="Final_Report_Coord.pdf",
        file_size=2048,
        is_late=False
    )
    db_session.add(sub)
    db_session.commit()

    from pathlib import Path
    Path("storage/submissions").mkdir(parents=True, exist_ok=True)
    Path("storage/submissions/coord_doc.pdf").write_bytes(b"%PDF-1.4\nCoordinator Download Test\n%%EOF")

    coord = create_test_coordinator(db_session, uid)
    login_client(client, coord.username)
    res = client.get(f"/submissions/{sub.id}/download")
    assert res.status_code == 200
    assert "attachment; filename=\"Final_Report_Coord.pdf\"" in res.headers["content-disposition"]
    assert len(res.content) > 0


def test_real_docx_upload_accepted(client: TestClient, db_session: Session):
    """
    Verifies that uploading a real, valid .docx file (ZIP archive containing XML parts
    and starting with PK\x03\x04 magic bytes) is accepted, validated, and stored properly.
    """
    uid = uuid.uuid4().hex[:6]
    stu = create_test_student(db_session, uid)
    sup = create_test_supervisor(db_session, uid)
    assign = create_active_assignment(db_session, stu, sup, uid)

    # Construct genuine valid .docx package in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>'
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>SPMS Project Submission Real DOCX</w:t></w:r></w:p></w:body></w:document>'
        )
    docx_bytes = buf.getvalue()
    assert docx_bytes.startswith(b"PK\x03\x04"), "DOCX bytes must start with PK zip header"

    login_client(client, stu.user.username)
    subs_page = client.get("/submissions")
    assert subs_page.status_code == 200
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', subs_page.text).group(1)

    res = client.post(
        "/submissions/SYNOPSIS/upload",
        files={"file": ("Genuine_Project_Synopsis.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"csrf_token": csrf},
        follow_redirects=True
    )
    assert res.status_code == 200
    assert "Under Review" in res.text or "Synopsis" in res.text

    # Verify submission record in DB
    db_session.rollback()
    sub_record = (
        db_session.query(Submission)
        .filter(Submission.assignment_id == assign.id, Submission.chapter == ChapterEnum.SYNOPSIS)
        .first()
    )
    assert sub_record is not None
    assert sub_record.original_filename == "Genuine_Project_Synopsis.docx"
    assert sub_record.file_path.endswith(".docx")
    assert sub_record.file_size == len(docx_bytes)

    # Verify file stored on filesystem
    from pathlib import Path
    actual_file = Path(sub_record.file_path)
    assert actual_file.exists()
    assert actual_file.read_bytes().startswith(b"PK\x03\x04")

