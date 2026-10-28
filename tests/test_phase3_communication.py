import io
import uuid
import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, Department, AcademicSession, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import Topic, TopicAssignment, TopicStatusEnum, TopicProposedRoleEnum, AssignmentStatusEnum
from app.models.communication import Message, ForumThread, ForumReply
from app.models.guideline import Guideline, Notification
from app.core.security import hash_password

def _get_csrf_token(client: TestClient, url: str) -> str:
    res = client.get(url)
    assert res.status_code == 200
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', res.text)
    assert match is not None, f"CSRF token not found on {url}"
    return match.group(1)

def _login(client: TestClient, username: str, password: str = "Password123!"):
    client.cookies.clear()
    login_page = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    res = client.post("/auth/login", data={"username": username, "password": password, "csrf_token": csrf})
    assert res.status_code in [200, 303]

def _create_user(db: Session, username: str, email: str, role: RoleEnum) -> User:
    u = User(
        username=username,
        email=email,
        password_hash=hash_password("Password123!"),
        role=role,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    db.add(u)
    db.flush()

    # If student, also attach valid student profile
    if role == RoleEnum.STUDENT:
        dept = db.query(Department).first()
        sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
        stu = Student(
            user_id=u.id,
            department_id=dept.id,
            session_id=sess.id,
            usn=f"U_{uuid.uuid4().hex[:7].upper()}",
            full_name=f"Full {username}",
            semester=8,
            academic_year=sess.name,
            phone="9876543210"
        )
        db.add(stu)
        db.flush()

    return u

def test_messaging_id_tampering_gets_403(client: TestClient, db_session: Session):
    """
    Verifies that only the assigned student and supervisor can access a conversation.
    An unauthorized student (Student B) or unauthorized supervisor (Supervisor B)
    attempting to view or send to Assignment A gets 403 Forbidden.
    """
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # Assignment Pair A
    u_stu_a = _create_user(db_session, f"MSG_STUA_{uid}", f"msg_stua_{uid}@test.local", RoleEnum.STUDENT)
    stu_a = db_session.query(Student).filter(Student.user_id == u_stu_a.id).first()

    u_sup_a = _create_user(db_session, f"MSG_SUPA_{uid}", f"msg_supa_{uid}@test.local", RoleEnum.SUPERVISOR)
    sup_a = Supervisor(user_id=u_sup_a.id, department_id=dept.id, full_name="Supervisor A", designation="Professor", max_slots=4)
    db_session.add(sup_a)
    db_session.flush()

    top_a = Topic(
        title=f"Topic A {uid}", normalized_title=f"topic a {uid}", description="Desc", domain="AI",
        department_id=dept.id, session_id=sess.id, proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=u_sup_a.id, status=TopicStatusEnum.ASSIGNED
    )
    db_session.add(top_a)
    db_session.flush()

    assign_a = TopicAssignment(
        topic_id=top_a.id, student_id=stu_a.id, supervisor_id=sup_a.id, session_id=sess.id, status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(assign_a)

    # Unauthorized Student B
    u_stu_b = _create_user(db_session, f"MSG_STUB_{uid}", f"msg_stub_{uid}@test.local", RoleEnum.STUDENT)
    db_session.commit()

    # Student B logs in
    _login(client, u_stu_b.username)

    # 1. Student B attempts GET /messaging/{assign_a.id} -> MUST RETURN 403
    res_get = client.get(f"/messaging/{assign_a.id}")
    assert res_get.status_code == 403
    assert "Access denied" in res_get.text

    # 2. Student B attempts POST /messaging/{assign_a.id}/send -> MUST RETURN 403
    dash = client.get("/dashboard")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', dash.text).group(1)
    res_post = client.post(
        f"/messaging/{assign_a.id}/send",
        data={"content": "Tampered message", "csrf_token": csrf}
    )
    assert res_post.status_code == 403

def test_messaging_send_and_notification(client: TestClient, db_session: Session):
    """Verifies message sending, database persistence, recipient notification, and AJAX polling."""
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u_stu = _create_user(db_session, f"MSG_S_{uid}", f"msg_s_{uid}@test.local", RoleEnum.STUDENT)
    stu = db_session.query(Student).filter(Student.user_id == u_stu.id).first()

    u_sup = _create_user(db_session, f"MSG_P_{uid}", f"msg_p_{uid}@test.local", RoleEnum.SUPERVISOR)
    sup = Supervisor(user_id=u_sup.id, department_id=dept.id, full_name="Chat Supervisor", designation="Professor", max_slots=4)
    db_session.add(sup)
    db_session.flush()

    top = Topic(
        title=f"Chat Topic {uid}", normalized_title=f"chat topic {uid}", description="Chat Topic Desc", domain="Cloud",
        department_id=dept.id, session_id=sess.id, proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=u_sup.id, status=TopicStatusEnum.ASSIGNED
    )
    db_session.add(top)
    db_session.flush()

    assign = TopicAssignment(
        topic_id=top.id, student_id=stu.id, supervisor_id=sup.id, session_id=sess.id, status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(assign)
    db_session.commit()

    # Student logs in and sends message
    _login(client, u_stu.username)
    thread_page = client.get(f"/messaging/{assign.id}")
    assert thread_page.status_code == 200
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', thread_page.text).group(1)

    post_res = client.post(
        f"/messaging/{assign.id}/send",
        data={"content": "Hello Dr. Supervisor, here is my weekly update.", "csrf_token": csrf},
        follow_redirects=True
    )
    assert post_res.status_code == 200
    assert "Hello Dr. Supervisor, here is my weekly update." in post_res.text

    # Rollback test session snapshot to see committed data from test client
    db_session.rollback()

    # Verify message in DB
    msg = db_session.query(Message).filter(Message.assignment_id == assign.id).first()
    assert msg is not None
    assert msg.sender_id == u_stu.id
    assert msg.recipient_id == u_sup.id
    assert msg.is_read == False

    # Verify notification for supervisor
    notif = db_session.query(Notification).filter(Notification.user_id == u_sup.id).order_by(Notification.id.desc()).first()
    assert notif is not None
    assert "New message from" in notif.title

    # Supervisor logs in and polls
    _login(client, u_sup.username)
    poll_res = client.get(f"/messaging/{assign.id}/poll?after_id=0")
    assert poll_res.status_code == 200
    poll_data = poll_res.json()
    assert len(poll_data["messages"]) >= 1
    assert poll_data["messages"][0]["content"] == "Hello Dr. Supervisor, here is my weekly update."

def test_forum_department_isolation(client: TestClient, db_session: Session):
    """
    Verifies department-scoped isolation in the forum:
    - Thread created in Department 1 cannot be viewed by a student from Department 2 (403 Forbidden).
    - Replying to a thread from another department also returns 403 Forbidden.
    """
    uid = uuid.uuid4().hex[:6]
    depts = db_session.query(Department).all()
    if len(depts) < 2:
        dept2 = Department(code=f"D2_{uid[:4]}", name="Second Department")
        db_session.add(dept2)
        db_session.commit()
        depts = db_session.query(Department).all()

    dept1, dept2 = depts[0], depts[1]
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # User in Dept 1
    u1 = _create_user(db_session, f"F_DEPT1_{uid}", f"fdept1_{uid}@test.local", RoleEnum.STUDENT)
    stu1 = db_session.query(Student).filter(Student.user_id == u1.id).first()
    stu1.department_id = dept1.id

    # User in Dept 2
    u2 = _create_user(db_session, f"F_DEPT2_{uid}", f"fdept2_{uid}@test.local", RoleEnum.STUDENT)
    stu2 = db_session.query(Student).filter(Student.user_id == u2.id).first()
    stu2.department_id = dept2.id
    db_session.commit()

    # User 1 creates thread in Dept 1
    _login(client, u1.username)
    new_page = client.get("/forum/new")
    csrf1 = re.search(r'name="csrf_token"\s+value="([^"]+)"', new_page.text).group(1)
    create_res = client.post(
        "/forum/new",
        data={"title": f"Dept 1 Exclusive Discussion {uid}", "content": "Important discussion for Dept 1 students only.", "csrf_token": csrf1},
        follow_redirects=False
    )
    assert create_res.status_code == 303
    thread_id = int(create_res.headers["location"].split("/")[-1])

    # User 2 logs in (Dept 2)
    _login(client, u2.username)

    # 1. User 2 attempts to view thread_id from Dept 1 -> MUST BE 403 FORBIDDEN
    view_res = client.get(f"/forum/{thread_id}")
    assert view_res.status_code == 403
    assert "Department isolation violation" in view_res.text

    # 2. User 2 attempts to reply to thread_id -> MUST BE 403 FORBIDDEN
    dash = client.get("/dashboard")
    csrf2 = re.search(r'name="csrf_token"\s+value="([^"]+)"', dash.text).group(1)
    reply_res = client.post(
        f"/forum/{thread_id}/reply",
        data={"content": "Attempting cross-department reply", "csrf_token": csrf2}
    )
    assert reply_res.status_code == 403

def test_forum_delete_permissions(client: TestClient, db_session: Session):
    """
    Verifies that only the thread author or the project coordinator can delete a thread.
    Other students or supervisors receive 403 Forbidden.
    """
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u_author = _create_user(db_session, f"F_AUTH_{uid}", f"fauth_{uid}@test.local", RoleEnum.STUDENT)
    u_other = _create_user(db_session, f"F_OTHER_{uid}", f"fother_{uid}@test.local", RoleEnum.STUDENT)
    db_session.commit()

    thread = ForumThread(department_id=dept.id, user_id=u_author.id, title=f"Delete Test Thread {uid}", content="Content to delete")
    db_session.add(thread)
    db_session.commit()
    t_id = thread.id

    # Other student attempts to delete -> 403
    _login(client, u_other.username)
    dash = client.get("/dashboard")
    csrf_other = re.search(r'name="csrf_token"\s+value="([^"]+)"', dash.text).group(1)
    del_res = client.post(f"/forum/{t_id}/delete", data={"csrf_token": csrf_other})
    assert del_res.status_code == 403
    assert "Access denied" in del_res.text

    # Author deletes -> 303 Redirect
    _login(client, u_author.username)
    dash = client.get("/dashboard")
    csrf_author = re.search(r'name="csrf_token"\s+value="([^"]+)"', dash.text).group(1)
    del_res2 = client.post(f"/forum/{t_id}/delete", data={"csrf_token": csrf_author}, follow_redirects=False)
    assert del_res2.status_code == 303

    db_session.rollback()
    assert db_session.query(ForumThread).filter(ForumThread.id == t_id).first() is None

def test_guidelines_upload_rejections(client: TestClient, db_session: Session):
    """
    Verifies coordinator upload validations:
    1. Executable file (.exe) rejected with 400.
    2. Invalid file header (.pdf extension but fake contents) rejected with 400.
    3. File exceeding 10MB limit rejected with 400.
    """
    coord = db_session.query(User).filter(User.role == RoleEnum.ADMIN).first()
    _login(client, coord.username)
    guide_page = client.get("/guidelines")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', guide_page.text).group(1)

    # 1. Reject .exe file
    exe_content = b"MZ\x90\x00\x03\x00\x00\x00BinaryExeCode"
    res1 = client.post(
        "/guidelines/upload",
        data={"title": "Malicious Executable", "description": "test", "csrf_token": csrf},
        files={"file": ("malicious.exe", io.BytesIO(exe_content), "application/x-msdownload")}
    )
    assert res1.status_code == 400
    assert "Invalid file extension" in res1.text or "Only PDF, DOC, and DOCX" in res1.text

    # 2. Reject fake PDF (does not start with %PDF-)
    fake_pdf = b"This is plain text pretending to be a pdf"
    res2 = client.post(
        "/guidelines/upload",
        data={"title": "Fake PDF", "description": "test", "csrf_token": csrf},
        files={"file": ("fake.pdf", io.BytesIO(fake_pdf), "application/pdf")}
    )
    assert res2.status_code == 400
    assert "Invalid PDF file header" in res2.text

    # 3. Reject over 10MB
    oversized = b"%PDF-1.4 " + (b"A" * (10 * 1024 * 1024 + 100))
    res3 = client.post(
        "/guidelines/upload",
        data={"title": "Oversized Manual", "description": "test", "csrf_token": csrf},
        files={"file": ("huge.pdf", io.BytesIO(oversized), "application/pdf")}
    )
    assert res3.status_code == 400
    assert "maximum allowed size of 10 MB" in res3.text

def test_guidelines_valid_upload_and_download(client: TestClient, db_session: Session):
    """Verifies that a valid PDF can be uploaded by the coordinator, broadcasts notifications, and is downloadable."""
    uid = uuid.uuid4().hex[:6]
    coord = db_session.query(User).filter(User.role == RoleEnum.ADMIN).first()
    _login(client, coord.username)

    guide_page = client.get("/guidelines")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', guide_page.text).group(1)

    valid_pdf_content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\nxref\n0 2\n0000000000 65535 f \n0000000010 00000 n \ntrailer<</Size 2/Root 1 0 R>>\nstartxref\n50\n%%EOF"
    upload_res = client.post(
        "/guidelines/upload",
        data={"title": f"Official Manual {uid}", "description": "Sample guidelines", "csrf_token": csrf},
        files={"file": ("manual.pdf", io.BytesIO(valid_pdf_content), "application/pdf")},
        follow_redirects=False
    )
    assert upload_res.status_code == 303

    db_session.rollback()

    # Check guideline stored in DB
    g = db_session.query(Guideline).filter(Guideline.title == f"Official Manual {uid}").first()
    assert g is not None
    assert g.original_filename == "manual.pdf"

    # Authenticated download route
    download_res = client.get(f"/guidelines/{g.id}/download")
    assert download_res.status_code == 200
    assert download_res.content == valid_pdf_content

def test_csrf_rejection_on_all_phase3_post_routes(client: TestClient, db_session: Session):
    """Verifies that all Phase 3 POST routes strictly reject requests missing valid CSRF token with 403."""
    uid = uuid.uuid4().hex[:6]
    u = _create_user(db_session, f"CSRF_P3_{uid}", f"csrf_p3_{uid}@test.local", RoleEnum.STUDENT)
    db_session.commit()
    _login(client, u.username)

    student_routes = [
        ("/messaging/1/send", {"content": "Hello"}),
        ("/forum/new", {"title": "Title", "content": "Content"}),
        ("/forum/1/reply", {"content": "Reply"}),
        ("/forum/1/delete", {}),
        ("/forum/reply/1/delete", {}),
        ("/notifications/1/read", {}),
        ("/notifications/read-all", {}),
    ]

    for route, data in student_routes:
        # POST without csrf_token
        res = client.post(route, data=data)
        assert res.status_code == 403, f"Expected 403 for {route} without CSRF token, got {res.status_code}"
        assert "Invalid" in res.text or "CSRF" in res.text

    # Coordinator POST routes
    coord = db_session.query(User).filter(User.role == RoleEnum.ADMIN).first()
    _login(client, coord.username)
    
    # Guidelines upload without CSRF
    res_upload = client.post(
        "/guidelines/upload",
        data={"title": "Test Title"},
        files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
    )
    assert res_upload.status_code == 403
    assert "Invalid" in res_upload.text or "CSRF" in res_upload.text

    coord_routes = [
        ("/guidelines/1/edit", {"title": "Title"}),
        ("/guidelines/1/delete", {}),
    ]
    for route, data in coord_routes:
        res = client.post(route, data=data)
        assert res.status_code == 403, f"Expected 403 for {route} without CSRF token, got {res.status_code}"
        assert "Invalid" in res.text or "CSRF" in res.text

def test_xss_payloads_in_messages_and_forum_rendered_as_plain_text(client: TestClient, db_session: Session):
    """Verifies that HTML/Script tags in messages, forum threads, and forum replies are auto-escaped as plain text."""
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u_stu = _create_user(db_session, f"XSS_S_{uid}", f"xss_s_{uid}@test.local", RoleEnum.STUDENT)
    stu = db_session.query(Student).filter(Student.user_id == u_stu.id).first()

    u_sup = _create_user(db_session, f"XSS_P_{uid}", f"xss_p_{uid}@test.local", RoleEnum.SUPERVISOR)
    sup = Supervisor(user_id=u_sup.id, department_id=dept.id, full_name="XSS Supervisor", designation="Professor", max_slots=4)
    db_session.add(sup)
    db_session.flush()

    top = Topic(
        title=f"XSS Topic {uid}", normalized_title=f"xss topic {uid}", description="Desc", domain="Security",
        department_id=dept.id, session_id=sess.id, proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=u_sup.id, status=TopicStatusEnum.ASSIGNED
    )
    db_session.add(top)
    db_session.flush()

    assign = TopicAssignment(
        topic_id=top.id, student_id=stu.id, supervisor_id=sup.id, session_id=sess.id, status=AssignmentStatusEnum.ACTIVE
    )
    db_session.add(assign)
    db_session.commit()

    # 1. XSS in Chat message
    xss_msg_payload = f"<script>alert('xss-chat-{uid}')</script>"
    m = Message(assignment_id=assign.id, sender_id=u_stu.id, recipient_id=u_sup.id, content=xss_msg_payload)
    db_session.add(m)

    # 2. XSS in Forum thread and reply
    xss_forum_title = f"<script>alert('xss-title-{uid}')</script>"
    xss_forum_content = f"<img src=x onerror=alert('xss-content-{uid}')>"
    xss_reply_content = f"<svg onload=alert('xss-reply-{uid}')>"

    t = ForumThread(department_id=dept.id, user_id=u_stu.id, title=xss_forum_title, content=xss_forum_content)
    db_session.add(t)
    db_session.flush()

    r = ForumReply(thread_id=t.id, user_id=u_sup.id, content=xss_reply_content)
    db_session.add(r)
    db_session.commit()

    _login(client, u_stu.username)

    # Verify Chat thread renders payload as escaped text
    chat_page = client.get(f"/messaging/{assign.id}")
    assert chat_page.status_code == 200
    assert xss_msg_payload not in chat_page.text or "&lt;script&gt;" in chat_page.text

    # Verify Forum view renders payload as escaped text
    forum_page = client.get(f"/forum/{t.id}")
    assert forum_page.status_code == 200
    assert "<script>alert" not in forum_page.text
    assert "<svg onload" not in forum_page.text
    assert "&lt;script&gt;" in forum_page.text or "alert" in forum_page.text

def test_notification_read_unread_behavior(client: TestClient, db_session: Session):
    """
    Verifies notification behaviors:
    1. Unread count starts at 2.
    2. Marking one notification as read decrements count to 1.
    3. Marking all as read sets unread count to 0.
    """
    uid = uuid.uuid4().hex[:6]
    u = _create_user(db_session, f"NOTIF_U_{uid}", f"notif_u_{uid}@test.local", RoleEnum.STUDENT)
    db_session.commit()

    n1 = Notification(user_id=u.id, title="Alert 1", message="Message 1", link="/dashboard")
    n2 = Notification(user_id=u.id, title="Alert 2", message="Message 2", link="/topics")
    db_session.add_all([n1, n2])
    db_session.commit()

    _login(client, u.username)

    # Step 1: Poll unread
    res1 = client.get("/notifications/unread")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["count"] == 2
    assert len(data1["notifications"]) == 2

    # Step 2: Mark n1 as read
    notif_page = client.get("/notifications")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', notif_page.text).group(1)

    read_res = client.post(
        f"/notifications/{n1.id}/read",
        data={"csrf_token": csrf},
        headers={"Accept": "application/json"}
    )
    assert read_res.status_code == 200

    res2 = client.get("/notifications/unread")
    assert res2.json()["count"] == 1

    # Step 3: Mark all as read
    read_all_res = client.post(
        "/notifications/read-all",
        data={"csrf_token": csrf},
        headers={"Accept": "application/json"}
    )
    assert read_all_res.status_code == 200

    res3 = client.get("/notifications/unread")
    assert res3.json()["count"] == 0
