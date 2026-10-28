import uuid
import re
import threading
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, Department, AcademicSession, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import (
    Topic, TopicStatusEnum, TopicAssignment, AssignmentStatusEnum,
    TopicRequest, TopicRequestStatusEnum, TopicProposedRoleEnum
)
from app.models.guideline import Notification
from app.core.security import hash_password
from app.database import SessionLocal

def create_test_coordinator(db: Session, uid: str) -> User:
    unique_hex = uuid.uuid4().hex[:8].upper()
    u = User(
        username=f"COORD_{unique_hex}",
        email=f"coord_{unique_hex.lower()}@test.local",
        password_hash=hash_password("CoordPass123!"),
        role=RoleEnum.ADMIN,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    db.add(u)
    db.commit()
    return u

def create_test_student(db: Session, uid: str, status: AccountStatusEnum = AccountStatusEnum.APPROVED) -> Student:
    dept = db.query(Department).first()
    sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    unique_hex = uuid.uuid4().hex[:8].upper()
    u = User(
        username=f"STU_{unique_hex}",
        email=f"stu_{unique_hex.lower()}@test.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.STUDENT,
        status=status,
        must_change_password=False,
        session_version=1
    )
    db.add(u)
    db.flush()
    s = Student(
        user_id=u.id,
        department_id=dept.id,
        session_id=sess.id,
        usn=f"1SP23CS{unique_hex[:5]}",
        full_name=f"Student {unique_hex}",
        semester=8,
        academic_year=sess.name,
        phone="+91 9888877777"
    )
    db.add(s)
    db.commit()
    return s

def create_test_supervisor(db: Session, uid: str, max_slots: int = 1) -> Supervisor:
    dept = db.query(Department).first()
    unique_hex = uuid.uuid4().hex[:8].upper()
    u = User(
        username=f"SUP_{unique_hex}",
        email=f"sup_{unique_hex.lower()}@test.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    db.add(u)
    db.flush()
    sup = Supervisor(
        user_id=u.id,
        department_id=dept.id,
        full_name=f"Dr. Supervisor {unique_hex}",
        designation="Professor",
        max_slots=max_slots
    )
    db.add(sup)
    db.commit()
    return sup

def test_student_gets_403_on_coordinator_routes(client: TestClient, db_session: Session):
    """Verifies that a student receives 403 Forbidden on all coordinator endpoints."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    student = create_test_student(db_session, uid)

    # Login as student
    login_page = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    client.post("/auth/login", data={"username": student.user.username, "password": "Pass123!", "csrf_token": csrf})

    # Coordinator routes
    coord_routes = [
        "/coordinator/departments",
        "/coordinator/sessions",
        "/coordinator/supervisors",
        "/coordinator/approvals",
        "/coordinator/topics",
        "/coordinator/topic-requests"
    ]
    for route in coord_routes:
        res = client.get(route)
        assert res.status_code == 403, f"Expected 403 for student on {route}, got {res.status_code}"

def test_csrf_rejection_on_new_post_routes(client: TestClient, db_session: Session):
    """Verifies that POST requests missing or providing invalid CSRF tokens are rejected with 403."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    coord = create_test_coordinator(db_session, uid)

    # Login as coordinator
    login_page = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    client.post("/auth/login", data={"username": coord.username, "password": "CoordPass123!", "csrf_token": csrf})

    # Post without CSRF token
    routes = [
        ("/coordinator/departments", {"code": "TEST", "name": "Test Department"}),
        ("/coordinator/sessions", {"name": "2029-2030", "start_date": "2029-01-01", "end_date": "2029-12-31"}),
        ("/coordinator/supervisors", {"full_name": "Test", "email": "sup_nocsrf@test.local", "department_id": 1, "designation": "Prof", "max_slots": 2}),
        ("/coordinator/approvals/999/approve", {}),
        ("/coordinator/approvals/999/reject", {"remarks": "Invalid"}),
        ("/coordinator/topics/999/approve", {"supervisor_id": 1}),
        ("/coordinator/topics/999/reject", {"remarks": "Invalid"}),
        ("/coordinator/topic-requests/999/approve", {}),
        ("/coordinator/topic-requests/999/reject", {"remarks": "Invalid"}),
        ("/topics/propose", {"title": "No CSRF", "description": "desc", "domain": "AI", "department_id": 1, "session_id": 1}),
        ("/topics/publish", {"title": "No CSRF", "description": "desc", "domain": "AI", "department_id": 1, "session_id": 1}),
        ("/topics/999/request", {"remarks": "interest"})
    ]

    for path, data in routes:
        # Without csrf_token
        res = client.post(path, data=data)
        assert res.status_code == 403, f"Expected 403 on {path} without CSRF token, got {res.status_code}"

def test_supervisor_at_max_slots_rejected(client: TestClient, db_session: Session):
    """Verifies that attempting to assign a supervisor at max_slots capacity is rejected with 400."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    coord = create_test_coordinator(db_session, uid)
    sup = create_test_supervisor(db_session, uid, max_slots=1)
    stu1 = create_test_student(db_session, f"{uid}1")
    stu2 = create_test_student(db_session, f"{uid}2")

    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # Pre-occupy the 1 slot
    t1 = Topic(
        title=f"Slot Topic 1 {uid}", normalized_title=f"slot topic 1 {uid}",
        description="Desc", domain="AI", department_id=dept.id, session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR, proposed_by_user_id=sup.user_id,
        status=TopicStatusEnum.ASSIGNED
    )
    db_session.add(t1)
    db_session.flush()

    assign1 = TopicAssignment(
        topic_id=t1.id, student_id=stu1.id, supervisor_id=sup.id, session_id=sess.id,
        status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(assign1)
    db_session.commit()

    # Student 2 proposes Topic 2
    t2 = Topic(
        title=f"Slot Topic 2 {uid}", normalized_title=f"slot topic 2 {uid}",
        description="Desc 2", domain="Web", department_id=dept.id, session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.STUDENT, proposed_by_user_id=stu2.user_id,
        status=TopicStatusEnum.PROPOSED
    )
    db_session.add(t2)
    db_session.commit()

    # Login as coordinator
    login_page = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    client.post("/auth/login", data={"username": coord.username, "password": "CoordPass123!", "csrf_token": csrf})

    # Attempt to assign the full supervisor to Topic 2 -> MUST FAIL WITH 400
    topics_page = client.get("/coordinator/topics")
    csrf_tok = re.search(r'name="csrf_token"\s+value="([^"]+)"', topics_page.text).group(1)
    res = client.post(
        f"/coordinator/topics/{t2.id}/approve",
        data={"supervisor_id": sup.id, "csrf_token": csrf_tok}
    )
    assert res.status_code == 400
    assert "maximum capacity" in res.text

def test_simultaneous_assignments_last_slot_concurrency(db_session: Session):
    """Verifies that two simultaneous threads assigning the last slot are serialized by SELECT ... FOR UPDATE."""
    uid = uuid.uuid4().hex[:6]
    sup = create_test_supervisor(db_session, uid, max_slots=1)
    stu1 = create_test_student(db_session, f"{uid}A")
    stu2 = create_test_student(db_session, f"{uid}B")
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    t1 = Topic(
        title=f"Conc Topic A {uid}", normalized_title=f"conc topic a {uid}",
        description="Desc A", domain="IoT", department_id=dept.id, session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR, proposed_by_user_id=sup.user_id,
        status=TopicStatusEnum.AVAILABLE
    )
    t2 = Topic(
        title=f"Conc Topic B {uid}", normalized_title=f"conc topic b {uid}",
        description="Desc B", domain="IoT", department_id=dept.id, session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR, proposed_by_user_id=sup.user_id,
        status=TopicStatusEnum.AVAILABLE
    )
    db_session.add_all([t1, t2])
    db_session.commit()

    results = []
    sup_id = sup.id
    sess_id = sess.id
    t1_id, stu1_id = t1.id, stu1.id
    t2_id, stu2_id = t2.id, stu2.id

    def worker_assign(student_id: int, topic_id: int):
        db = SessionLocal()
        try:
            # Lock supervisor row
            locked_sup = db.query(Supervisor).filter(Supervisor.id == sup_id).with_for_update().first()
            current_active = (
                db.query(TopicAssignment)
                .filter(TopicAssignment.supervisor_id == locked_sup.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
                .count()
            )
            if current_active >= locked_sup.max_slots:
                results.append("CAPACITY_EXCEEDED")
                db.rollback()
                return

            assign = TopicAssignment(
                topic_id=topic_id,
                student_id=student_id,
                supervisor_id=locked_sup.id,
                session_id=sess_id,
                status=AssignmentStatusEnum.ACTIVE
            )
            db.add(assign)
            db.commit()
            results.append("ASSIGNED")
        except Exception as e:
            db.rollback()
            results.append(f"ERROR: {e}")
        finally:
            db.close()

    th1 = threading.Thread(target=worker_assign, args=(stu1_id, t1_id))
    th2 = threading.Thread(target=worker_assign, args=(stu2_id, t2_id))

    th1.start()
    th2.start()
    th1.join()
    th2.join()

    # Exactly 1 thread must succeed and 1 must be rejected for capacity
    assert results.count("ASSIGNED") == 1
    assert results.count("CAPACITY_EXCEEDED") == 1

def test_topic_request_state_machine_and_notifications(client: TestClient, db_session: Session):
    """
    Verifies full topic request state machine:
    1. Student 1 and Student 2 request Topic T1 (published by Supervisor).
    2. Student 1 also requests Topic T2.
    3. Coordinator approves Student 1's request for Topic T1.
    4. State machine:
       - Student 1 assigned to Topic T1 (ACTIVE assignment).
       - Topic T1 status -> ASSIGNED.
       - Student 1's request for T1 -> APPROVED.
       - Student 1's other request for T2 -> CANCELLED.
       - Student 2's competing request for T1 -> REJECTED.
    5. Notifications table contains entries for all affected parties.
    """
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    coord = create_test_coordinator(db_session, uid)
    sup = create_test_supervisor(db_session, uid, max_slots=2)
    stu1 = create_test_student(db_session, f"{uid}1")
    stu2 = create_test_student(db_session, f"{uid}2")
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # Topics
    t1 = Topic(
        title=f"Machine Learning in Healthcare {uid}", normalized_title=f"machine learning in healthcare {uid}",
        description="Healthcare ML", domain="AI", department_id=dept.id, session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR, proposed_by_user_id=sup.user_id,
        status=TopicStatusEnum.AVAILABLE
    )
    t2 = Topic(
        title=f"Cybersecurity Threat Hunting {uid}", normalized_title=f"cybersecurity threat hunting {uid}",
        description="Cybersecurity", domain="Security", department_id=dept.id, session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR, proposed_by_user_id=sup.user_id,
        status=TopicStatusEnum.AVAILABLE
    )
    db_session.add_all([t1, t2])
    db_session.commit()

    # Student 1 requests T1 and T2
    req1_stu1 = TopicRequest(topic_id=t1.id, student_id=stu1.id, status=TopicRequestStatusEnum.PENDING, student_remarks="First preference")
    req2_stu1 = TopicRequest(topic_id=t2.id, student_id=stu1.id, status=TopicRequestStatusEnum.PENDING, student_remarks="Second preference")
    # Student 2 requests T1
    req1_stu2 = TopicRequest(topic_id=t1.id, student_id=stu2.id, status=TopicRequestStatusEnum.PENDING, student_remarks="Also want T1")
    db_session.add_all([req1_stu1, req2_stu1, req1_stu2])
    db_session.commit()

    # Login as coordinator
    login_page = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    client.post("/auth/login", data={"username": coord.username, "password": "CoordPass123!", "csrf_token": csrf})

    # Coordinator approves req1_stu1 (Student 1 -> Topic 1)
    reqs_page = client.get("/coordinator/topic-requests")
    csrf_tok = re.search(r'name="csrf_token"\s+value="([^"]+)"', reqs_page.text).group(1)
    approve_res = client.post(
        f"/coordinator/topic-requests/{req1_stu1.id}/approve",
        data={"csrf_token": csrf_tok},
        follow_redirects=False
    )
    assert approve_res.status_code == 303

    # Reset snapshot and verify state machine transitions
    db_session.rollback()
    
    # 1. Topic 1 is ASSIGNED
    t1_fresh = db_session.query(Topic).filter(Topic.id == t1.id).first()
    assert t1_fresh.status == TopicStatusEnum.ASSIGNED

    # 2. req1_stu1 is APPROVED
    r1_s1_fresh = db_session.query(TopicRequest).filter(TopicRequest.id == req1_stu1.id).first()
    assert r1_s1_fresh.status == TopicRequestStatusEnum.APPROVED

    # 3. Student 1's other request (req2_stu1 for T2) is CANCELLED
    r2_s1_fresh = db_session.query(TopicRequest).filter(TopicRequest.id == req2_stu1.id).first()
    assert r2_s1_fresh.status == TopicRequestStatusEnum.CANCELLED

    # 4. Student 2's competing request for T1 is REJECTED
    r1_s2_fresh = db_session.query(TopicRequest).filter(TopicRequest.id == req1_stu2.id).first()
    assert r1_s2_fresh.status == TopicRequestStatusEnum.REJECTED

    # 5. Active TopicAssignment created for Student 1
    assign = db_session.query(TopicAssignment).filter(TopicAssignment.topic_id == t1.id, TopicAssignment.student_id == stu1.id).first()
    assert assign is not None
    assert assign.status == AssignmentStatusEnum.ACTIVE

    # 6. Notifications stored
    stu1_notifs = db_session.query(Notification).filter(Notification.user_id == stu1.user_id).all()
    assert len(stu1_notifs) >= 1
    stu2_notifs = db_session.query(Notification).filter(Notification.user_id == stu2.user_id).all()
    assert len(stu2_notifs) >= 1
    sup_notifs = db_session.query(Notification).filter(Notification.user_id == sup.user_id).all()
    assert len(sup_notifs) >= 1

def test_xss_payload_in_topic_rendered_as_plain_text(client: TestClient, db_session: Session):
    """Verifies that XSS payloads in topic titles and descriptions are auto-escaped as plain text."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    coord = create_test_coordinator(db_session, uid)
    sup = create_test_supervisor(db_session, uid, max_slots=3)
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    xss_title = f"<script>alert('xss-topic-{uid}')</script>"
    xss_desc = f"<img src=x onerror=alert('xss-topic-desc-{uid}')>"

    # Create topic directly in DB to bypass title validation and test template rendering
    t = Topic(
        title=xss_title,
        normalized_title=f"xss topic {uid}",
        description=xss_desc,
        domain="Security",
        department_id=dept.id,
        session_id=sess.id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=sup.user_id,
        status=TopicStatusEnum.AVAILABLE
    )
    db_session.add(t)
    db_session.commit()

    # 1. View /topics as public/authenticated user
    login_page = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    client.post("/auth/login", data={"username": coord.username, "password": "CoordPass123!", "csrf_token": csrf})

    topics_res = client.get("/topics")
    assert topics_res.status_code == 200
    # Must NOT contain raw unescaped script or img tag
    assert xss_title not in topics_res.text
    assert f"<img src=x onerror=" not in topics_res.text
    # Must contain escaped representation
    assert f"&lt;script&gt;alert(&#39;xss-topic-{uid}&#39;)&lt;/script&gt;" in topics_res.text or f"&lt;script&gt;alert('xss-topic-{uid}')&lt;/script&gt;" in topics_res.text

    # 2. View /coordinator/topics
    coord_topics = client.get("/coordinator/topics")
    assert coord_topics.status_code == 200
    assert xss_title not in coord_topics.text
    assert f"<img src=x onerror=" not in coord_topics.text
