import secrets
from typing import Optional
from pathlib import Path
from datetime import datetime, date
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.database import get_db
from app.models.user import (
    User, RoleEnum, AccountStatusEnum, Department, AcademicSession
)
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import (
    Topic, TopicStatusEnum, TopicAssignment, AssignmentStatusEnum,
    TopicRequest, TopicRequestStatusEnum, TopicProposedRoleEnum
)
from app.models.submission import Deadline, ChapterEnum, CHAPTER_DISPLAY_NAMES
from app.core.dependencies import require_role
from app.core.security import get_or_create_csrf_token, validate_csrf_token, hash_password
from app.core.datetime_util import utc_now, ensure_utc
from app.services.notification_service import create_notification

router = APIRouter(prefix="/coordinator", tags=["Coordinator"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Dependency: Coordinator Only
coordinator_guard = require_role([RoleEnum.ADMIN])

# ============================================================================
# 1. DEPARTMENTS MANAGEMENT
# ============================================================================
@router.get("/departments", response_class=HTMLResponse)
def list_departments(
    request: Request,
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    departments = db.query(Department).all()
    dept_stats = []
    for d in departments:
        stu_count = db.query(Student).filter(Student.department_id == d.id).count()
        sup_count = db.query(Supervisor).filter(Supervisor.department_id == d.id).count()
        dept_stats.append({
            "dept": d,
            "student_count": stu_count,
            "supervisor_count": sup_count
        })

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="coordinator/departments.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "departments": dept_stats,
            "active_nav": "departments"
        }
    )

@router.post("/departments", response_class=HTMLResponse)
def create_department(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_code = code.strip().upper()
    clean_name = name.strip()

    existing = db.query(Department).filter(or_(Department.code == clean_code, Department.name == clean_name)).first()
    if existing:
        return list_departments(request, current_user, db)

    new_dept = Department(code=clean_code, name=clean_name)
    db.add(new_dept)
    db.commit()

    return RedirectResponse(url="/coordinator/departments", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/departments/{dept_id}/edit", response_class=HTMLResponse)
def edit_department(
    request: Request,
    dept_id: int,
    code: str = Form(...),
    name: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found.")

    dept.code = code.strip().upper()
    dept.name = name.strip()
    db.commit()

    return RedirectResponse(url="/coordinator/departments", status_code=status.HTTP_303_SEE_OTHER)

# ============================================================================
# 2. ACADEMIC SESSIONS MANAGEMENT
# ============================================================================
@router.get("/sessions", response_class=HTMLResponse)
def list_sessions(
    request: Request,
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    sessions = db.query(AcademicSession).order_by(AcademicSession.id.desc()).all()
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="coordinator/sessions.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "sessions": sessions,
            "active_nav": "sessions"
        }
    )

@router.post("/sessions", response_class=HTMLResponse)
def create_session(
    request: Request,
    name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    is_active: bool = Form(False),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_name = name.strip()
    d_start = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
    d_end = datetime.strptime(end_date.strip(), "%Y-%m-%d").date()

    if is_active:
        # Deactivate other sessions
        db.query(AcademicSession).update({AcademicSession.is_active: False})

    new_sess = AcademicSession(
        name=clean_name,
        start_date=d_start,
        end_date=d_end,
        is_active=is_active
    )
    db.add(new_sess)
    db.commit()

    return RedirectResponse(url="/coordinator/sessions", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/sessions/{session_id}/toggle", response_class=HTMLResponse)
def toggle_session_active(
    request: Request,
    session_id: int,
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    sess = db.query(AcademicSession).filter(AcademicSession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Deactivate others if activating this one
    db.query(AcademicSession).update({AcademicSession.is_active: False})
    sess.is_active = True
    db.commit()

    return RedirectResponse(url="/coordinator/sessions", status_code=status.HTTP_303_SEE_OTHER)

# ============================================================================
# 3. SUPERVISORS & SLOTS MANAGEMENT
# ============================================================================
@router.get("/supervisors", response_class=HTMLResponse)
def list_supervisors(
    request: Request,
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    supervisors = db.query(Supervisor).join(User).all()
    departments = db.query(Department).all()
    
    sup_data = []
    for s in supervisors:
        active_assignments = (
            db.query(TopicAssignment)
            .filter(TopicAssignment.supervisor_id == s.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
            .count()
        )
        sup_data.append({
            "supervisor": s,
            "active_count": active_assignments,
            "available_slots": max(0, s.max_slots - active_assignments)
        })

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="coordinator/supervisors.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "supervisors": sup_data,
            "departments": departments,
            "active_nav": "supervisors"
        }
    )

@router.post("/supervisors", response_class=HTMLResponse)
def create_supervisor(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    department_id: int = Form(...),
    designation: str = Form(...),
    max_slots: int = Form(4),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_email = email.strip().lower()
    clean_name = full_name.strip()
    
    existing = db.query(User).filter(User.email == clean_email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists.")

    username = f"SUP_{clean_email.split('@')[0].upper()[:20]}"
    # Generate secure one-time password
    temp_password = secrets.token_urlsafe(10)
    
    new_user = User(
        username=username,
        email=clean_email,
        password_hash=hash_password(temp_password),
        role=RoleEnum.SUPERVISOR,
        status=AccountStatusEnum.APPROVED,
        must_change_password=True,
        session_version=1,
        remarks="Supervisor account created by Coordinator."
    )
    db.add(new_user)
    db.flush()

    new_sup = Supervisor(
        user_id=new_user.id,
        department_id=department_id,
        full_name=clean_name,
        designation=designation.strip(),
        max_slots=max(1, max_slots)
    )
    db.add(new_sup)
    db.commit()

    # Flash credentials for one-time display to coordinator
    departments = db.query(Department).all()
    supervisors = db.query(Supervisor).join(User).all()
    sup_data = []
    for s in supervisors:
        cnt = db.query(TopicAssignment).filter(TopicAssignment.supervisor_id == s.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE).count()
        sup_data.append({"supervisor": s, "active_count": cnt, "available_slots": max(0, s.max_slots - cnt)})

    return templates.TemplateResponse(
        request=request,
        name="coordinator/supervisors.html",
        context={
            "csrf_token": get_or_create_csrf_token(request),
            "current_user": current_user,
            "supervisors": sup_data,
            "departments": departments,
            "active_nav": "supervisors",
            "success": f"Supervisor account '{username}' created successfully!",
            "one_time_creds": {
                "username": username,
                "email": clean_email,
                "temp_password": temp_password
            }
        }
    )

@router.post("/supervisors/{sup_id}/slots", response_class=HTMLResponse)
def update_supervisor_slots(
    request: Request,
    sup_id: int,
    max_slots: int = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    sup = db.query(Supervisor).filter(Supervisor.id == sup_id).first()
    if not sup:
        raise HTTPException(status_code=404, detail="Supervisor not found.")

    sup.max_slots = max(1, max_slots)
    db.commit()

    return RedirectResponse(url="/coordinator/supervisors", status_code=status.HTTP_303_SEE_OTHER)

# ============================================================================
# 4. STUDENT ACCOUNT APPROVALS & REJECTIONS
# ============================================================================
@router.get("/approvals", response_class=HTMLResponse)
def list_pending_approvals(
    request: Request,
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    pending_students = (
        db.query(Student)
        .join(User)
        .filter(User.status == AccountStatusEnum.PENDING)
        .all()
    )
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="coordinator/approvals.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "pending_students": pending_students,
            "active_nav": "approvals"
        }
    )

@router.post("/approvals/{user_id}/approve", response_class=HTMLResponse)
def approve_student_account(
    request: Request,
    user_id: int,
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.status = AccountStatusEnum.APPROVED
    user.remarks = "Approved by Coordinator."
    
    # Send persistent notification
    create_notification(
        db=db,
        user_id=user.id,
        title="Account Approved",
        message="Your student registration has been approved! You can now log in and explore project topics.",
        link="/dashboard"
    )
    db.commit()

    return RedirectResponse(url="/coordinator/approvals", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/approvals/{user_id}/reject", response_class=HTMLResponse)
def reject_student_account(
    request: Request,
    user_id: int,
    remarks: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_remarks = remarks.strip()
    if not clean_remarks:
        raise HTTPException(status_code=400, detail="Rejection remarks are required.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.status = AccountStatusEnum.REJECTED
    user.remarks = clean_remarks

    # Send persistent notification
    create_notification(
        db=db,
        user_id=user.id,
        title="Registration Rejected",
        message=f"Your registration was rejected. Reason: {clean_remarks}. Please use the resubmit link to correct your details.",
        link="/auth/login"
    )
    db.commit()

    return RedirectResponse(url="/coordinator/approvals", status_code=status.HTTP_303_SEE_OTHER)

# ============================================================================
# 5. TOPIC MANAGEMENT & PROPOSAL APPROVAL (STUDENT-PROPOSED TOPICS)
# ============================================================================
@router.get("/topics", response_class=HTMLResponse)
def list_coordinator_topics(
    request: Request,
    status_filter: Optional[str] = None,
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    query = db.query(Topic)
    if status_filter:
        query = query.filter(Topic.status == status_filter)
    
    topics = query.order_by(Topic.created_at.desc()).all()
    supervisors = db.query(Supervisor).join(User).all()
    
    sup_slots = []
    for sup in supervisors:
        act = db.query(TopicAssignment).filter(TopicAssignment.supervisor_id == sup.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE).count()
        sup_slots.append({
            "supervisor": sup,
            "active_count": act,
            "remaining_slots": max(0, sup.max_slots - act)
        })

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="coordinator/topics.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "topics": topics,
            "supervisors": sup_slots,
            "status_filter": status_filter,
            "active_nav": "topics"
        }
    )

@router.post("/topics/{topic_id}/approve", response_class=HTMLResponse)
def approve_topic_and_assign_supervisor(
    request: Request,
    topic_id: int,
    supervisor_id: int = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found.")

    # 1. SLOT GUARD: Row lock supervisor with SELECT ... FOR UPDATE
    sup = db.query(Supervisor).filter(Supervisor.id == supervisor_id).with_for_update().first()
    if not sup:
        raise HTTPException(status_code=404, detail="Supervisor not found.")

    active_count = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.supervisor_id == sup.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
        .count()
    )
    if active_count >= sup.max_slots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Supervisor {sup.full_name} has reached maximum capacity ({sup.max_slots} slots)."
        )

    # 2. Check student proposer
    student = db.query(Student).filter(Student.user_id == topic.proposed_by_user_id).first()
    if not student:
        raise HTTPException(status_code=400, detail="Topic was not proposed by a student.")

    existing_stu_assignment = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.student_id == student.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
        .first()
    )
    if existing_stu_assignment:
        raise HTTPException(status_code=400, detail="Student already has an active project assignment.")

    # 3. Create Assignment & update topic
    assignment = TopicAssignment(
        topic_id=topic.id,
        student_id=student.id,
        supervisor_id=sup.id,
        session_id=topic.session_id,
        status=AssignmentStatusEnum.ACTIVE
    )
    db.add(assignment)
    topic.status = TopicStatusEnum.ASSIGNED

    # 4. Cancel other pending topic requests by this student
    other_requests = (
        db.query(TopicRequest)
        .filter(TopicRequest.student_id == student.id, TopicRequest.status == TopicRequestStatusEnum.PENDING)
        .all()
    )
    for r in other_requests:
        r.status = TopicRequestStatusEnum.CANCELLED

    # 5. Dispatch Notifications
    create_notification(
        db=db,
        user_id=student.user_id,
        title="Topic Approved & Supervisor Assigned",
        message=f"Your proposed topic '{topic.title}' has been approved! Supervisor {sup.full_name} is assigned to guide you.",
        link="/dashboard"
    )
    create_notification(
        db=db,
        user_id=sup.user_id,
        title="New Student Project Assigned",
        message=f"You have been assigned as supervisor for student {student.full_name} on project '{topic.title}'.",
        link="/dashboard"
    )

    db.commit()
    return RedirectResponse(url="/coordinator/topics", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/topics/{topic_id}/reject", response_class=HTMLResponse)
def reject_student_topic(
    request: Request,
    topic_id: int,
    remarks: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_remarks = remarks.strip()
    if not clean_remarks:
        raise HTTPException(status_code=400, detail="Rejection remarks are required.")

    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found.")

    topic.status = TopicStatusEnum.REJECTED
    topic.rejection_remarks = clean_remarks

    # Notify student
    create_notification(
        db=db,
        user_id=topic.proposed_by_user_id,
        title="Topic Proposal Rejected",
        message=f"Your proposed topic '{topic.title}' was rejected by the coordinator. Remarks: {clean_remarks}. You may propose a revised or new topic.",
        link="/topics/propose"
    )
    db.commit()

    return RedirectResponse(url="/coordinator/topics", status_code=status.HTTP_303_SEE_OTHER)

# ============================================================================
# 6. TOPIC REQUEST APPROVALS (STUDENT REQUESTS FOR AVAILABLE TOPICS)
# ============================================================================
@router.get("/topic-requests", response_class=HTMLResponse)
def list_topic_requests(
    request: Request,
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    requests = (
        db.query(TopicRequest)
        .filter(TopicRequest.status == TopicRequestStatusEnum.PENDING)
        .all()
    )
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="coordinator/topic_requests.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "requests": requests,
            "active_nav": "topic_requests"
        }
    )

@router.post("/topic-requests/{req_id}/approve", response_class=HTMLResponse)
def approve_topic_request(
    request: Request,
    req_id: int,
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    req = db.query(TopicRequest).filter(TopicRequest.id == req_id).first()
    if not req or req.status != TopicRequestStatusEnum.PENDING:
        raise HTTPException(status_code=404, detail="Topic request not found or not pending.")

    topic = req.topic
    student = req.student

    # Identify supervisor who proposed the topic (or default supervisor)
    supervisor = db.query(Supervisor).filter(Supervisor.user_id == topic.proposed_by_user_id).first()
    if not supervisor:
        # Fallback to any supervisor in the department
        supervisor = db.query(Supervisor).filter(Supervisor.department_id == topic.department_id).first()
    if not supervisor:
        raise HTTPException(status_code=400, detail="No supervisor available for this topic assignment.")

    # 1. SLOT GUARD: SELECT ... FOR UPDATE on supervisor
    sup_locked = db.query(Supervisor).filter(Supervisor.id == supervisor.id).with_for_update().first()
    active_assignments = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.supervisor_id == sup_locked.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
        .count()
    )
    if active_assignments >= sup_locked.max_slots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Supervisor {sup_locked.full_name} has reached maximum capacity ({sup_locked.max_slots} slots)."
        )

    # 2. Check student single-active constraint
    existing_act = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.student_id == student.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
        .first()
    )
    if existing_act:
        raise HTTPException(status_code=400, detail="Student already has an active project assignment.")

    # 3. Create ACTIVE assignment
    assignment = TopicAssignment(
        topic_id=topic.id,
        student_id=student.id,
        supervisor_id=sup_locked.id,
        session_id=topic.session_id,
        status=AssignmentStatusEnum.ACTIVE
    )
    db.add(assignment)
    req.status = TopicRequestStatusEnum.APPROVED
    topic.status = TopicStatusEnum.ASSIGNED

    # 4. State Machine Transitions:
    # A) Cancel all OTHER pending requests from THIS student
    other_student_requests = (
        db.query(TopicRequest)
        .filter(TopicRequest.student_id == student.id, TopicRequest.id != req.id, TopicRequest.status == TopicRequestStatusEnum.PENDING)
        .all()
    )
    for r in other_student_requests:
        r.status = TopicRequestStatusEnum.CANCELLED
        create_notification(
            db=db,
            user_id=student.user_id,
            title="Topic Request Closed",
            message=f"Your request for '{r.topic.title}' was cancelled because topic '{topic.title}' was assigned to you."
        )

    # B) Reject all other students' pending requests for THIS topic
    competing_requests = (
        db.query(TopicRequest)
        .filter(TopicRequest.topic_id == topic.id, TopicRequest.id != req.id, TopicRequest.status == TopicRequestStatusEnum.PENDING)
        .all()
    )
    for cr in competing_requests:
        cr.status = TopicRequestStatusEnum.REJECTED
        cr.coordinator_remarks = "Topic was assigned to another applicant."
        create_notification(
            db=db,
            user_id=cr.student.user_id,
            title="Topic Request Update",
            message=f"Topic '{topic.title}' has been assigned to another student. You may browse and request other available topics.",
            link="/topics"
        )

    # 5. Notify approved student and supervisor
    create_notification(
        db=db,
        user_id=student.user_id,
        title="Topic Request Approved",
        message=f"Your request for topic '{topic.title}' was approved! Supervisor {sup_locked.full_name} is assigned to guide you.",
        link="/dashboard"
    )
    create_notification(
        db=db,
        user_id=sup_locked.user_id,
        title="New Student Assignment",
        message=f"Student {student.full_name} has been assigned to topic '{topic.title}'.",
        link="/dashboard"
    )

    db.commit()
    return RedirectResponse(url="/coordinator/topic-requests", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/topic-requests/{req_id}/reject", response_class=HTMLResponse)
def reject_topic_request(
    request: Request,
    req_id: int,
    remarks: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_remarks = remarks.strip()
    if not clean_remarks:
        raise HTTPException(status_code=400, detail="Rejection remarks are required.")

    req = db.query(TopicRequest).filter(TopicRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")

    req.status = TopicRequestStatusEnum.REJECTED
    req.coordinator_remarks = clean_remarks

    create_notification(
        db=db,
        user_id=req.student.user_id,
        title="Topic Request Rejected",
        message=f"Your request for topic '{req.topic.title}' was rejected by the coordinator. Remarks: {clean_remarks}.",
        link="/topics"
    )
    db.commit()

    return RedirectResponse(url="/coordinator/topic-requests", status_code=status.HTTP_303_SEE_OTHER)


# ============================================================================
# 6. DEADLINES MANAGEMENT
# ============================================================================
@router.get("/deadlines", response_class=HTMLResponse)
def list_deadlines(
    request: Request,
    session_id: Optional[int] = None,
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    sessions = db.query(AcademicSession).order_by(AcademicSession.id.desc()).all()
    selected_sess = None
    if session_id:
        selected_sess = db.query(AcademicSession).filter(AcademicSession.id == session_id).first()
    if not selected_sess and sessions:
        # Default to active session or first session
        selected_sess = next((s for s in sessions if s.is_active), sessions[0])

    deadlines = []
    if selected_sess:
        deadlines = db.query(Deadline).filter(Deadline.session_id == selected_sess.id).all()

    csrf_token = get_or_create_csrf_token(request)
    now = utc_now()

    # Pre-map deadline per chapter for clean UI display
    chapter_deadlines = []
    deadline_by_chapter = {d.chapter: d for d in deadlines}
    for ch in [ChapterEnum.SYNOPSIS, ChapterEnum.SRS_DESIGN, ChapterEnum.IMPLEMENTATION, ChapterEnum.FINAL_REPORT]:
        dl = deadline_by_chapter.get(ch)
        is_overdue = False
        remaining_str = "No deadline configured"
        if dl:
            dl_due = ensure_utc(dl.due_date)
            is_overdue = now > dl_due
            diff = dl_due - now
            if is_overdue:
                remaining_str = f"Overdue by {abs(diff.days)}d {abs(diff.seconds)//3600}h"
            else:
                remaining_str = f"{diff.days}d {diff.seconds//3600}h remaining"

        chapter_deadlines.append({
            "chapter": ch,
            "display_name": CHAPTER_DISPLAY_NAMES[ch],
            "deadline": dl,
            "is_overdue": is_overdue,
            "remaining_str": remaining_str
        })

    return templates.TemplateResponse(
        request=request,
        name="coordinator/deadlines.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "sessions": sessions,
            "selected_session": selected_sess,
            "chapter_deadlines": chapter_deadlines,
            "CHAPTER_DISPLAY_NAMES": CHAPTER_DISPLAY_NAMES,
            "active_nav": "deadlines"
        }
    )


@router.post("/deadlines", response_class=HTMLResponse)
def save_deadline(
    request: Request,
    session_id: int = Form(...),
    chapter: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    due_date: str = Form(...),
    allow_late: bool = Form(False),
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Deadline title is required.")

    try:
        ch_enum = ChapterEnum(chapter.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid chapter '{chapter}'.")

    # Parse due_date (support datetime-local format 'YYYY-MM-DDTHH:MM' and standard ISO)
    clean_dt = due_date.strip().replace("T", " ")
    parsed_date = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed_date = datetime.strptime(clean_dt, fmt)
            break
        except ValueError:
            continue

    if not parsed_date:
        raise HTTPException(status_code=400, detail="Invalid due_date format. Use YYYY-MM-DDTHH:MM.")

    sess = db.query(AcademicSession).filter(AcademicSession.id == session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Academic session not found.")

    # Check for existing deadline on (session_id, chapter)
    dl = db.query(Deadline).filter(Deadline.session_id == session_id, Deadline.chapter == ch_enum).first()
    if dl:
        dl.title = clean_title
        dl.description = description.strip() if description else None
        dl.due_date = parsed_date
        dl.allow_late = allow_late
    else:
        dl = Deadline(
            session_id=session_id,
            chapter=ch_enum,
            title=clean_title,
            description=description.strip() if description else None,
            due_date=parsed_date,
            allow_late=allow_late
        )
        db.add(dl)

    db.commit()

    # Notify students in this session
    students = db.query(Student).filter(Student.session_id == session_id).all()
    for s in students:
        create_notification(
            db=db,
            user_id=s.user_id,
            title=f"Deadline Set: {CHAPTER_DISPLAY_NAMES[ch_enum]}",
            message=f"Coordinator set the deadline for {CHAPTER_DISPLAY_NAMES[ch_enum]} to {parsed_date.strftime('%Y-%m-%d %H:%M')}.",
            link="/submissions"
        )
    db.commit()

    return RedirectResponse(
        url=f"/coordinator/deadlines?session_id={session_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/deadlines/{deadline_id}/delete", response_class=HTMLResponse)
def delete_deadline(
    request: Request,
    deadline_id: int,
    csrf_token: str = Form(None),
    current_user: User = Depends(coordinator_guard),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    dl = db.query(Deadline).filter(Deadline.id == deadline_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Deadline not found.")

    sess_id = dl.session_id
    db.delete(dl)
    db.commit()

    return RedirectResponse(
        url=f"/coordinator/deadlines?session_id={sess_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )
