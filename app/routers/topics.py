from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models.user import User, RoleEnum, AcademicSession, Department
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import (
    Topic, TopicStatusEnum, TopicAssignment, AssignmentStatusEnum,
    TopicRequest, TopicRequestStatusEnum, TopicProposedRoleEnum
)
from app.core.dependencies import get_current_user, require_role
from app.core.security import get_or_create_csrf_token, validate_csrf_token
from app.services.duplicate_detector import check_topic_duplicate
from app.services.notification_service import create_notification

router = APIRouter(prefix="/topics", tags=["Topics"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ============================================================================
# 1. BROWSE AVAILABLE TOPICS
# ============================================================================
@router.get("", response_class=HTMLResponse)
def list_available_topics(
    request: Request,
    q: Optional[str] = None,
    domain: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Topic).filter(Topic.status == TopicStatusEnum.AVAILABLE)

    if q:
        clean_q = f"%{q.strip()}%"
        query = query.filter(or_(Topic.title.ilike(clean_q), Topic.description.ilike(clean_q)))
    if domain:
        query = query.filter(Topic.domain == domain.strip())

    topics = query.order_by(Topic.created_at.desc()).all()
    domains = [d[0] for d in db.query(Topic.domain).distinct().all() if d[0]]

    student = None
    has_active_assignment = False
    requested_topic_ids = set()

    if current_user.role == RoleEnum.STUDENT:
        student = db.query(Student).filter(Student.user_id == current_user.id).first()
        if student:
            act = db.query(TopicAssignment).filter(
                TopicAssignment.student_id == student.id,
                TopicAssignment.status == AssignmentStatusEnum.ACTIVE
            ).first()
            has_active_assignment = act is not None
            user_reqs = db.query(TopicRequest).filter(
                TopicRequest.student_id == student.id,
                TopicRequest.status.in_([TopicRequestStatusEnum.PENDING, TopicRequestStatusEnum.APPROVED])
            ).all()
            requested_topic_ids = {r.topic_id for r in user_reqs}

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="topics/browse.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "topics": topics,
            "domains": domains,
            "selected_domain": domain,
            "search_query": q,
            "has_active_assignment": has_active_assignment,
            "requested_topic_ids": requested_topic_ids,
            "active_nav": "topics"
        }
    )

# ============================================================================
# 2. STUDENT PROPOSE TOPIC
# ============================================================================
@router.get("/propose", response_class=HTMLResponse)
def propose_topic_page(
    request: Request,
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
):
    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    has_active = db.query(TopicAssignment).filter(
        TopicAssignment.student_id == student.id,
        TopicAssignment.status == AssignmentStatusEnum.ACTIVE
    ).first()

    departments = db.query(Department).all()
    sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
    csrf_token = get_or_create_csrf_token(request)

    return templates.TemplateResponse(
        request=request,
        name="topics/propose.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "student": student,
            "departments": departments,
            "sessions": sessions,
            "has_active_assignment": has_active is not None,
            "active_nav": "topics"
        }
    )

@router.post("/propose", response_class=HTMLResponse)
def submit_topic_proposal(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    domain: str = Form(...),
    department_id: int = Form(...),
    session_id: int = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    act = db.query(TopicAssignment).filter(
        TopicAssignment.student_id == student.id,
        TopicAssignment.status == AssignmentStatusEnum.ACTIVE
    ).first()
    if act:
        raise HTTPException(status_code=400, detail="You already have an active project assignment.")

    clean_title = title.strip()
    clean_desc = description.strip()
    clean_domain = domain.strip()

    # DUPLICATE DETECTION CHECK
    is_dup, score, match_title = check_topic_duplicate(db, clean_title)
    if is_dup:
        # DO NOT STORE DUPLICATE
        departments = db.query(Department).all()
        sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
        return templates.TemplateResponse(
            request=request,
            name="topics/propose.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "current_user": current_user,
                "student": student,
                "departments": departments,
                "sessions": sessions,
                "has_active_assignment": False,
                "active_nav": "topics",
                "error": f"Duplicate topic detected ({round(score * 100, 1)}% similarity). Conflicting with existing topic: '{match_title}'. Please refine your proposal.",
                "form_data": {
                    "title": clean_title,
                    "description": clean_desc,
                    "domain": clean_domain,
                    "department_id": department_id,
                    "session_id": session_id
                }
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Save student proposal
    new_topic = Topic(
        title=clean_title,
        normalized_title=clean_title.lower(),
        description=clean_desc,
        domain=clean_domain,
        department_id=department_id,
        session_id=session_id,
        proposed_by_role=TopicProposedRoleEnum.STUDENT,
        proposed_by_user_id=current_user.id,
        status=TopicStatusEnum.PROPOSED
    )
    db.add(new_topic)
    db.commit()

    return templates.TemplateResponse(
        request=request,
        name="topics/propose.html",
        context={
            "csrf_token": get_or_create_csrf_token(request),
            "current_user": current_user,
            "student": student,
            "departments": db.query(Department).all(),
            "sessions": db.query(AcademicSession).filter(AcademicSession.is_active == True).all(),
            "has_active_assignment": False,
            "active_nav": "topics",
            "success": "Your project topic proposal has been submitted successfully! It is pending coordinator review."
        }
    )

# ============================================================================
# 3. SUPERVISOR PUBLISH AVAILABLE TOPIC
# ============================================================================
@router.get("/publish", response_class=HTMLResponse)
def publish_topic_page(
    request: Request,
    current_user: User = Depends(require_role([RoleEnum.SUPERVISOR])),
    db: Session = Depends(get_db)
):
    supervisor = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
    departments = db.query(Department).all()
    sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
    csrf_token = get_or_create_csrf_token(request)

    return templates.TemplateResponse(
        request=request,
        name="topics/publish.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "supervisor": supervisor,
            "departments": departments,
            "sessions": sessions,
            "active_nav": "publish"
        }
    )

@router.post("/publish", response_class=HTMLResponse)
def submit_publish_topic(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    domain: str = Form(...),
    department_id: int = Form(...),
    session_id: int = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(require_role([RoleEnum.SUPERVISOR])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_title = title.strip()
    clean_desc = description.strip()
    clean_domain = domain.strip()

    # DUPLICATE DETECTION CHECK
    is_dup, score, match_title = check_topic_duplicate(db, clean_title)
    if is_dup:
        supervisor = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
        departments = db.query(Department).all()
        sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
        return templates.TemplateResponse(
            request=request,
            name="topics/publish.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "current_user": current_user,
                "supervisor": supervisor,
                "departments": departments,
                "sessions": sessions,
                "active_nav": "publish",
                "error": f"Duplicate topic detected ({round(score * 100, 1)}% similarity). Conflicting with existing topic: '{match_title}'.",
                "form_data": {
                    "title": clean_title,
                    "description": clean_desc,
                    "domain": clean_domain,
                    "department_id": department_id,
                    "session_id": session_id
                }
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    new_topic = Topic(
        title=clean_title,
        normalized_title=clean_title.lower(),
        description=clean_desc,
        domain=clean_domain,
        department_id=department_id,
        session_id=session_id,
        proposed_by_role=TopicProposedRoleEnum.SUPERVISOR,
        proposed_by_user_id=current_user.id,
        status=TopicStatusEnum.AVAILABLE
    )
    db.add(new_topic)
    db.commit()

    return RedirectResponse(url="/topics/published", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/published", response_class=HTMLResponse)
def list_published_topics(
    request: Request,
    current_user: User = Depends(require_role([RoleEnum.SUPERVISOR])),
    db: Session = Depends(get_db)
):
    topics = (
        db.query(Topic)
        .filter(Topic.proposed_by_user_id == current_user.id)
        .order_by(Topic.created_at.desc())
        .all()
    )
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="topics/published.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "topics": topics,
            "active_nav": "published"
        }
    )

# ============================================================================
# 4. STUDENT REQUEST AVAILABLE TOPIC
# ============================================================================
@router.post("/{topic_id}/request", response_class=HTMLResponse)
def request_available_topic(
    request: Request,
    topic_id: int,
    remarks: Optional[str] = Form(None),
    csrf_token: str = Form(None),
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    # Check student active assignment
    has_active = db.query(TopicAssignment).filter(
        TopicAssignment.student_id == student.id,
        TopicAssignment.status == AssignmentStatusEnum.ACTIVE
    ).first()
    if has_active:
        raise HTTPException(status_code=400, detail="You already have an active project assignment.")

    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic or topic.status != TopicStatusEnum.AVAILABLE:
        raise HTTPException(status_code=400, detail="Topic is not available for request.")

    # Check already requested
    existing_req = db.query(TopicRequest).filter(
        TopicRequest.topic_id == topic_id,
        TopicRequest.student_id == student.id,
        TopicRequest.status.in_([TopicRequestStatusEnum.PENDING, TopicRequestStatusEnum.APPROVED])
    ).first()
    if existing_req:
        raise HTTPException(status_code=400, detail="You have already submitted a request for this topic.")

    req = TopicRequest(
        topic_id=topic_id,
        student_id=student.id,
        status=TopicRequestStatusEnum.PENDING,
        student_remarks=remarks.strip() if remarks else None
    )
    db.add(req)
    
    # Notify coordinator
    admin_user = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
    if admin_user:
        create_notification(
            db=db,
            user_id=admin_user.id,
            title="New Topic Request",
            message=f"Student {student.full_name} ({student.usn}) requested topic '{topic.title}'.",
            link="/coordinator/topic-requests"
        )

    db.commit()
    return RedirectResponse(url="/topics/my-requests", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/my-requests", response_class=HTMLResponse)
def list_my_requests(
    request: Request,
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
):
    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    requests = (
        db.query(TopicRequest)
        .filter(TopicRequest.student_id == student.id)
        .order_by(TopicRequest.created_at.desc())
        .all()
    )
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="topics/my_requests.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "student": student,
            "requests": requests,
            "active_nav": "topics"
        }
    )
