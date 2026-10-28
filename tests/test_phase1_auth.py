import uuid
import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.user import User, Department, AcademicSession, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.core.security import hash_password, generate_resubmit_token

def test_csrf_rejection_on_post(client: TestClient):
    """Verifies that state-changing POST requests without CSRF token are rejected with 403."""
    client.cookies.clear()
    response = client.post("/auth/login", data={"username": "admin", "password": "any"})
    assert response.status_code == 403
    assert "Invalid or missing CSRF token" in response.text

def test_login_pending_account_rejection(client: TestClient, db_session: Session):
    """Verifies that PENDING accounts cannot log in and receive an informative message."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    u = User(
        username=f"PENDING_STU_{uid}",
        email=f"pending_{uid}@test.local",
        password_hash=hash_password("Secret123!"),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.PENDING
    )
    db_session.add(u)
    db_session.commit()

    # Step 1: GET login page to obtain a valid CSRF token in the test session
    get_res = client.get("/auth/login")
    assert get_res.status_code == 200

    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', get_res.text)
    assert match is not None
    token = match.group(1)

    # Step 2: POST login
    post_res = client.post(
        "/auth/login",
        data={"username": f"PENDING_STU_{uid}", "password": "Secret123!", "csrf_token": token}
    )
    assert post_res.status_code == 403
    assert "pending coordinator approval" in post_res.text

def test_login_rejected_account_flow(client: TestClient, db_session: Session):
    """Verifies that REJECTED accounts receive rejection remarks and a resubmit token link."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u = User(
        username=f"REJ_STU_{uid}",
        email=f"rej_{uid}@test.local",
        password_hash=hash_password("Secret123!"),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.REJECTED,
        remarks="Invalid phone number and department mismatch."
    )
    db_session.add(u)
    db_session.flush()

    s = Student(
        user_id=u.id,
        department_id=dept.id,
        session_id=sess.id,
        usn=f"REJ_STU_{uid}",
        full_name="Rejected Student",
        semester=8,
        academic_year=sess.name,
        phone="000"
    )
    db_session.add(s)
    db_session.commit()

    # GET login page
    get_res = client.get("/auth/login")
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', get_res.text)
    token = match.group(1)

    # POST login
    post_res = client.post(
        "/auth/login",
        data={"username": f"REJ_STU_{uid}", "password": "Secret123!", "csrf_token": token}
    )
    assert post_res.status_code == 403
    assert "Invalid phone number and department mismatch" in post_res.text
    assert "/register/resubmit?token=" in post_res.text

def test_resubmit_registration(client: TestClient, db_session: Session):
    """Verifies the resubmission flow using a signed token."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u = User(
        username=f"RESUB_STU_{uid}",
        email=f"resub_{uid}@test.local",
        password_hash=hash_password("Secret123!"),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.REJECTED,
        remarks="Please correct phone number."
    )
    db_session.add(u)
    db_session.flush()

    s = Student(
        user_id=u.id,
        department_id=dept.id,
        session_id=sess.id,
        usn=f"RESUB_STU_{uid}",
        full_name="Resubmit Student",
        semester=8,
        academic_year=sess.name,
        phone="000"
    )
    db_session.add(s)
    db_session.commit()

    token = generate_resubmit_token(u.id)

    # GET resubmit page
    res_get = client.get(f"/register/resubmit?token={token}")
    assert res_get.status_code == 200
    assert "Update & Resubmit Registration" in res_get.text

    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', res_get.text)
    csrf = match.group(1)

    # POST resubmit with corrected details
    res_post = client.post(
        "/register/resubmit",
        data={
            "resubmit_token": token,
            "csrf_token": csrf,
            "usn": f"RESUB_STU_{uid}",
            "full_name": "Corrected Student Name",
            "department_id": dept.id,
            "session_id": sess.id,
            "semester": 8,
            "email": f"corrected_{uid}@test.local",
            "phone": "+91 9888877777"
        }
    )
    assert res_post.status_code == 200
    assert "corrected registration has been submitted" in res_post.text

    # End transaction in db_session to see changes committed by route
    db_session.rollback()
    u_fresh = db_session.query(User).filter(User.id == u.id).first()
    assert u_fresh.status == AccountStatusEnum.PENDING
    assert u_fresh.email == f"corrected_{uid}@test.local"

def test_forced_password_change_and_session_invalidation(client: TestClient, db_session: Session):
    """
    Tests:
    1. Login with must_change_password=True redirects to /auth/change-password.
    2. Attempting to access /dashboard is blocked with 303 to /auth/change-password.
    3. Changing password increments session_version and unsets must_change_password.
    4. An older session with the old session_version is invalidated with 401.
    """
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    u = User(
        username=f"FORCE_{uid}",
        email=f"force_{uid}@test.local",
        password_hash=hash_password("TempPassword123!"),
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED,
        must_change_password=True,
        session_version=1
    )
    db_session.add(u)
    db_session.commit()

    # Login
    get_res = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', get_res.text).group(1)

    login_res = client.post(
        "/auth/login",
        data={"username": f"FORCE_{uid}", "password": "TempPassword123!", "csrf_token": csrf},
        follow_redirects=False
    )
    assert login_res.status_code == 303
    assert login_res.headers["location"] == "/auth/change-password"

    # Attempting to access dashboard with must_change_password=True redirects to change-password
    dash_res = client.get("/dashboard", follow_redirects=False)
    assert dash_res.status_code == 303
    assert dash_res.headers["location"] == "/auth/change-password"

    # Save session cookie before password change (Session 1)
    old_session_cookie = client.cookies.get("session")

    # Complete password change
    cp_page = client.get("/auth/change-password")
    cp_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', cp_page.text).group(1)

    change_res = client.post(
        "/auth/change-password",
        data={
            "current_password": "TempPassword123!",
            "new_password": "NewPermanentPass123!",
            "confirm_password": "NewPermanentPass123!",
            "csrf_token": cp_csrf
        },
        follow_redirects=False
    )
    assert change_res.status_code == 303
    assert change_res.headers["location"] == "/dashboard"

    # Verify user record updated
    db_session.expire_all()
    u_fresh = db_session.query(User).filter(User.id == u.id).first()
    assert u_fresh.must_change_password is False
    assert u_fresh.session_version == 2

    # Verify that a client presenting the old session cookie (session_version=1) is rejected with 401
    stale_client = TestClient(client.app, cookies={"session": old_session_cookie})
    stale_res = stale_client.get("/dashboard", follow_redirects=False)
    assert stale_res.status_code == 401

def test_post_logout_with_csrf_and_rejection_without(client: TestClient, db_session: Session):
    """Verifies that logout requires POST and a valid CSRF token."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    u = User(
        username=f"LOGOUT_{uid}",
        email=f"logout_{uid}@test.local",
        password_hash=hash_password("Password123!"),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    db_session.add(u)
    db_session.flush()

    s = Student(
        user_id=u.id,
        department_id=dept.id,
        session_id=sess.id,
        usn=f"LOGOUT_{uid}",
        full_name="Logout Student",
        semester=8,
        academic_year=sess.name,
        phone="+91 9999111122"
    )
    db_session.add(s)
    db_session.commit()

    # Login
    get_res = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', get_res.text).group(1)

    login_res = client.post(
        "/auth/login",
        data={"username": f"LOGOUT_{uid}", "password": "Password123!", "csrf_token": csrf},
        follow_redirects=False
    )
    assert login_res.status_code == 303

    # Attempt POST logout WITHOUT CSRF token -> MUST FAIL (403)
    bad_logout = client.post("/auth/logout", data={}, follow_redirects=False)
    assert bad_logout.status_code == 403

    # Attempt POST logout WITH valid CSRF token -> MUST SUCCEED (303 to login)
    dash = client.get("/dashboard")
    valid_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', dash.text).group(1)
    good_logout = client.post(
        "/auth/logout",
        data={"csrf_token": valid_csrf},
        follow_redirects=False
    )
    assert good_logout.status_code == 303
    assert good_logout.headers["location"] == "/auth/login"

def test_403_role_check(client: TestClient, db_session: Session):
    """Verifies that a student attempting to access coordinator-only endpoints receives 403."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    u = User(
        username=f"ROLE_STU_{uid}",
        email=f"role_stu_{uid}@test.local",
        password_hash=hash_password("Pass123!"),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    db_session.add(u)
    db_session.flush()

    s = Student(
        user_id=u.id,
        department_id=dept.id,
        session_id=sess.id,
        usn=f"ROLE_STU_{uid}",
        full_name="Role Student",
        semester=8,
        academic_year=sess.name,
        phone="+91 9999111133"
    )
    db_session.add(s)
    db_session.commit()

    from app.core.dependencies import require_role
    checker = require_role([RoleEnum.ADMIN])
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        checker(u)
    assert exc_info.value.status_code == 403
    assert "not authorized" in exc_info.value.detail

def test_rejected_user_blocked_from_all_routes_except_resubmit(client: TestClient, db_session: Session):
    """Verifies that a REJECTED user cannot access dashboard or profile and is limited to resubmit."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u = User(
        username=f"BLOCK_REJ_{uid}", email=f"block_rej_{uid}@test.local",
        password_hash=hash_password("Pass123!"), role=RoleEnum.STUDENT,
        status=AccountStatusEnum.REJECTED, remarks="Document verification failed."
    )
    db_session.add(u)
    db_session.flush()

    s = Student(
        user_id=u.id, department_id=dept.id, session_id=sess.id,
        usn=f"BLOCK_REJ_{uid}", full_name="Rejected User", semester=8,
        academic_year=sess.name, phone="9998887776"
    )
    db_session.add(s)
    db_session.commit()

    # 1. Login fails with 403 and provides resubmission link
    get_login = client.get("/auth/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', get_login.text).group(1)
    login_resp = client.post(
        "/auth/login",
        data={"username": f"BLOCK_REJ_{uid}", "password": "Pass123!", "csrf_token": csrf}
    )
    assert login_resp.status_code == 403
    assert "/register/resubmit?token=" in login_resp.text

    # 2. Resubmit URL is accessible (200 OK)
    token_match = re.search(r'/register/resubmit\?token=([a-zA-Z0-9_\-\.]+)', login_resp.text)
    assert token_match is not None
    token = token_match.group(1)
    resubmit_get = client.get(f"/register/resubmit?token={token}")
    assert resubmit_get.status_code == 200

    # 3. Protected routes block the rejected user
    dash_resp = client.get("/dashboard", follow_redirects=False)
    assert dash_resp.status_code in [303, 401, 403]
    prof_resp = client.get("/profile/student", follow_redirects=False)
    assert prof_resp.status_code in [303, 401, 403]

    # Verify get_current_user directly raises 403 for REJECTED status
    from app.core.dependencies import get_current_user
    from fastapi import HTTPException
    class MockRequest:
        def __init__(self, user_id, session_version):
            self.session = {"user_id": user_id, "session_version": session_version}
            self.url = type("URL", (), {"path": "/dashboard"})()

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(MockRequest(u.id, u.session_version), db_session)
    assert exc_info.value.status_code == 403
    assert "REJECTED" in exc_info.value.detail

def test_resubmit_token_single_use_and_expiry(client: TestClient, db_session: Session):
    """Verifies that an expired token is rejected and a valid token cannot be reused after submission."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    u = User(
        username=f"TOKEN_REJ_{uid}", email=f"token_rej_{uid}@test.local",
        password_hash=hash_password("Pass123!"), role=RoleEnum.STUDENT,
        status=AccountStatusEnum.REJECTED, remarks="Needs new ID proof."
    )
    db_session.add(u)
    db_session.flush()

    s = Student(
        user_id=u.id, department_id=dept.id, session_id=sess.id,
        usn=f"TOKEN_REJ_{uid}", full_name="Token Test Student", semester=8,
        academic_year=sess.name, phone="9998881111"
    )
    db_session.add(s)
    db_session.commit()

    # 1. Invalid or expired token returns 403
    from app.core.security import verify_resubmit_token
    token = generate_resubmit_token(u.id)
    assert verify_resubmit_token(token, max_age=-1) is None
    bad_get = client.get("/register/resubmit?token=expired_or_fake_token")
    assert bad_get.status_code == 403

    # 2. Valid token allows viewing resubmission form
    valid_token = generate_resubmit_token(u.id)
    page_get = client.get(f"/register/resubmit?token={valid_token}")
    assert page_get.status_code == 200
    csrf_tok = re.search(r'name="csrf_token"\s+value="([^"]+)"', page_get.text).group(1)

    # First submission succeeds -> status changes to PENDING
    post_resp = client.post(
        "/register/resubmit",
        data={
            "resubmit_token": valid_token,
            "usn": f"TOKEN_REJ_{uid}",
            "full_name": "Token Student Updated",
            "department_id": dept.id,
            "session_id": sess.id,
            "semester": 8,
            "email": f"token_rej_upd_{uid}@test.local",
            "phone": "9876543210",
            "csrf_token": csrf_tok
        }
    )
    assert post_resp.status_code == 200
    assert "pending coordinator review" in post_resp.text

    # Reusing the SAME token now fails with 400 because account is no longer REJECTED
    get_again = client.get(f"/register/resubmit?token={valid_token}")
    assert get_again.status_code == 400
    assert "not in a rejected state" in get_again.text

    post_again = client.post(
        "/register/resubmit",
        data={
            "resubmit_token": valid_token,
            "usn": f"TOKEN_REJ_{uid}",
            "full_name": "Token Student Updated Again",
            "department_id": dept.id,
            "session_id": sess.id,
            "semester": 8,
            "email": f"token_rej_upd_{uid}@test.local",
            "phone": "9876543210",
            "csrf_token": csrf_tok
        }
    )
    assert post_again.status_code == 400

def test_xss_payload_in_registration_rendered_as_plain_text(client: TestClient, db_session: Session):
    """Verifies that HTML/JavaScript injected into registration fields is auto-escaped as plain text."""
    client.cookies.clear()
    uid = uuid.uuid4().hex[:6]
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    xss_name = f"<script>alert('xss-name-{uid}')</script>"
    xss_skills = f"<img src=x onerror=alert('xss-skills-{uid}')>"

    # 1. Register with XSS payloads
    reg_page = client.get("/auth/register")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', reg_page.text).group(1)

    reg_resp = client.post(
        "/auth/register",
        data={
            "usn": f"XSS_{uid}",
            "full_name": xss_name,
            "department_id": dept.id,
            "session_id": sess.id,
            "semester": 8,
            "email": f"xss_{uid}@test.local",
            "phone": "9998881234",
            "skills": xss_skills,
            "password": "Password123!",
            "csrf_token": csrf
        }
    )
    assert reg_resp.status_code == 200

    # 2. Approve user in database and log in
    db_session.rollback()
    u = db_session.query(User).filter(User.username == f"XSS_{uid}".upper()).first()
    assert u is not None
    u.status = AccountStatusEnum.APPROVED
    db_session.commit()

    login_page = client.get("/auth/login")
    csrf_log = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
    client.post(
        "/auth/login",
        data={"username": f"XSS_{uid}".upper(), "password": "Password123!", "csrf_token": csrf_log}
    )

    # 3. Check Dashboard & Profile: XSS must be escaped
    dash_resp = client.get("/dashboard")
    assert dash_resp.status_code == 200
    assert f"<script>alert('xss-name-{uid}')</script>" not in dash_resp.text
    assert f"&lt;script&gt;alert(&#39;xss-name-{uid}&#39;)&lt;/script&gt;" in dash_resp.text or f"&lt;script&gt;alert('xss-name-{uid}')&lt;/script&gt;" in dash_resp.text

    prof_resp = client.get("/profile/student")
    assert prof_resp.status_code == 200
    assert f"<img src=x onerror=" not in prof_resp.text
