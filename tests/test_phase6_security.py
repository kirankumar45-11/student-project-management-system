import pytest
import secrets
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.models.user import User, RoleEnum, AccountStatusEnum, Department, AcademicSession
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import Topic, TopicAssignment, AssignmentStatusEnum
from app.core.security import hash_password, get_or_create_csrf_token
from app.core.datetime_util import utc_now
from app.core.rate_limiter import limiter


@pytest.fixture
def test_users(db_session):
    unique = secrets.token_hex(4)
    pwd = hash_password("Password123!")

    # Fetch or create department and active session
    dept = db_session.query(Department).first()
    sess = db_session.query(AcademicSession).filter(AcademicSession.is_active == True).first()

    # 1. Admin/Coordinator
    coord = User(
        username=f"coord_{unique}",
        email=f"coord_{unique}@spms.local",
        password_hash=pwd,
        role=RoleEnum.ADMIN,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    # 2. Supervisor
    sup = User(
        username=f"sup_{unique}",
        email=f"sup_{unique}@spms.local",
        password_hash=pwd,
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    # 3. Student
    stu = User(
        username=f"1SP23CS{unique.upper()[:6]}",
        email=f"stu_{unique}@spms.local",
        password_hash=pwd,
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.APPROVED,
        must_change_password=False,
        session_version=1
    )
    db_session.add_all([coord, sup, stu])
    db_session.flush()

    sup_prof = Supervisor(
        user_id=sup.id,
        department_id=dept.id,
        full_name=f"Dr. Test Supervisor {unique}",
        designation="Professor",
        max_slots=5
    )
    stu_prof = Student(
        user_id=stu.id,
        usn=stu.username,
        full_name=f"Test Student {unique}",
        department_id=dept.id,
        session_id=sess.id,
        academic_year="2025-2026",
        semester=8,
        phone="9876543210"
    )
    db_session.add_all([sup_prof, stu_prof])
    db_session.commit()

    return {"coord": coord, "sup": sup, "stu": stu, "sup_prof": sup_prof, "stu_prof": stu_prof}


def auth_client(user: User):
    client = TestClient(app)
    # Set signed session cookie
    with client:
        # Simulate session by calling a helper or setting cookie directly
        client.get("/auth/login")  # initialize session
        # modify session dict
        session_cookie = client.cookies.get("session")
    
    # Alternatively use client session
    c = TestClient(app)
    # Login via /auth/login with CSRF
    res1 = c.get("/auth/login")
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', res1.text)
    csrf = m.group(1) if m else "test"
    c.post("/auth/login", data={"username": user.username, "password": "Password123!", "csrf_token": csrf})
    return c


# =========================================================================
# 1. SECURITY HEADERS VERIFICATION
# =========================================================================
def test_security_headers_present_on_all_responses():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    headers = response.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert "Content-Security-Policy" in headers
    csp = headers.get("Content-Security-Policy")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self' https://cdn.jsdelivr.net 'nonce-" in csp
    # Strict verification: script-src directive MUST NOT use 'unsafe-inline'
    script_directive = [d.strip() for d in csp.split(";") if d.strip().startswith("script-src")][0]
    assert "'unsafe-inline'" not in script_directive, "script-src must not permit 'unsafe-inline'!"
    assert "'nonce-" in script_directive


# =========================================================================
# 2. SESSION COOKIE FLAGS
# =========================================================================
def test_session_cookie_flags():
    client = TestClient(app)
    res = client.get("/auth/login")
    assert "session" in client.cookies
    # Verify cookie parameters through starlette session middleware configuration
    assert settings.SESSION_COOKIE_SAMESITE in ["lax", "strict"]
    assert settings.SESSION_MAX_AGE_SECONDS > 0


# =========================================================================
# 3. API DOCS RESTRICTION OUTSIDE DEVELOPMENT
# =========================================================================
def test_api_docs_restricted_outside_development(monkeypatch):
    from fastapi import FastAPI
    # When ENVIRONMENT == "production"
    is_prod = (settings.ENVIRONMENT == "production")
    if is_prod:
        client = TestClient(app)
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    else:
        # In development mode docs exist
        client = TestClient(app)
        assert client.get("/docs").status_code in [200, 307]


# =========================================================================
# 4. ROUTE-BY-ROLE ACCESS MATRIX (ROLE CHECKS)
# =========================================================================
def test_route_role_access_matrix(test_users):
    stu_client = auth_client(test_users["stu"])
    sup_client = auth_client(test_users["sup"])
    coord_client = auth_client(test_users["coord"])
    anon_client = TestClient(app)

    # A. Coordinator-only routes: student and supervisor MUST get 403, anon gets redirected
    coord_routes = [
        "/coordinator/departments",
        "/coordinator/supervisors",
        "/coordinator/topics",
        "/coordinator/topic-requests",
        "/coordinator/deadlines",
        "/coordinator/approvals",
        "/coordinator/assessments"
    ]
    for route in coord_routes:
        assert stu_client.get(route).status_code == 403, f"Student accessed coordinator route {route}"
        assert sup_client.get(route).status_code == 403, f"Supervisor accessed coordinator route {route}"
        assert coord_client.get(route).status_code == 200, f"Coordinator blocked from {route}"
        # Anon gets 303 redirect to login
        assert anon_client.get(route, follow_redirects=False).status_code in [303, 401]

    # B. Student-only routes: supervisor and coordinator get 403
    student_routes = [
        "/topics/propose",
        "/topics/my-requests",
        "/profile/student"
    ]
    for route in student_routes:
        assert sup_client.get(route).status_code == 403, f"Supervisor accessed student route {route}"
        assert stu_client.get(route).status_code == 200, f"Student blocked from {route}"

    # C. Supervisor-only routes: student gets 403
    supervisor_routes = [
        "/topics/publish",
        "/topics/published",
        "/submissions/reviews"
    ]
    for route in supervisor_routes:
        assert stu_client.get(route).status_code == 403, f"Student accessed supervisor route {route}"
        assert sup_client.get(route).status_code == 200, f"Supervisor blocked from {route}"


# =========================================================================
# 5. CSRF REJECTION ON STATE-CHANGING POST ROUTES
# =========================================================================
def test_csrf_rejection_on_profile_student(test_users):
    """Verify newly added CSRF protection on /profile/student."""
    stu_client = auth_client(test_users["stu"])
    # Missing CSRF
    res = stu_client.post("/profile/student", data={"email": "new@spms.local", "phone": "1234567890"})
    assert res.status_code == 403
    assert "Invalid CSRF" in res.text or "CSRF" in res.text

    # Invalid CSRF
    res2 = stu_client.post("/profile/student", data={"email": "new@spms.local", "phone": "1234567890", "csrf_token": "tampered_token"})
    assert res2.status_code == 403


# =========================================================================
# 6. LOGIN RATE LIMITING TEST
# =========================================================================
def test_login_rate_limiting():
    """Verify rate limiter is wired to /auth/login and limits rapid requests."""
    limiter.enabled = True
    try:
        client = TestClient(app)
        statuses = []
        for _ in range(70):
            r = client.post("/auth/login", data={"username": "nonexistent_rl", "password": "bad", "csrf_token": "none"}, follow_redirects=False)
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in statuses, f"Expected 429 in statuses, got {set(statuses)}"
    finally:
        limiter.enabled = False
