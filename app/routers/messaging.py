from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.models.user import User, RoleEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import TopicAssignment, AssignmentStatusEnum
from app.models.communication import Message
from app.core.dependencies import get_current_user, require_role, verify_csrf
from app.core.security import get_or_create_csrf_token, validate_csrf_token
from app.core.datetime_util import utc_now
from app.services.notification_service import create_notification

router = APIRouter(prefix="/messaging", tags=["Messaging"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def _check_assignment_access(assignment: TopicAssignment, user: User) -> bool:
    """Verifies that the user is either the assigned student or supervisor."""
    if not assignment:
        return False
    is_assigned_student = assignment.student and assignment.student.user_id == user.id
    is_assigned_supervisor = assignment.supervisor and assignment.supervisor.user_id == user.id
    return bool(is_assigned_student or is_assigned_supervisor)

@router.get("", response_class=HTMLResponse)
def messaging_hub(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Directs user to their project chat:
    - Student: redirected to their single active assignment thread.
    - Supervisor: views inbox list of assigned students with unread counts.
    - Coordinator: views all active project communication channels.
    """
    csrf_token = get_or_create_csrf_token(request)

    if current_user.role == RoleEnum.STUDENT:
        student = db.query(Student).filter(Student.user_id == current_user.id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Student profile not found.")
        active_assignment = (
            db.query(TopicAssignment)
            .filter(
                TopicAssignment.student_id == student.id,
                TopicAssignment.status == AssignmentStatusEnum.ACTIVE
            )
            .first()
        )
        if active_assignment:
            return RedirectResponse(
                url=f"/messaging/{active_assignment.id}",
                status_code=status.HTTP_303_SEE_OTHER
            )
        return templates.TemplateResponse(
            request=request,
            name="messaging/index.html",
            context={
                "csrf_token": csrf_token,
                "current_user": current_user,
                "active_nav": "messages",
                "assignments": [],
                "has_assignment": False,
                "role": "STUDENT"
            }
        )

    elif current_user.role == RoleEnum.SUPERVISOR:
        supervisor = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
        if not supervisor:
            raise HTTPException(status_code=404, detail="Supervisor profile not found.")
        active_assignments = (
            db.query(TopicAssignment)
            .filter(
                TopicAssignment.supervisor_id == supervisor.id,
                TopicAssignment.status == AssignmentStatusEnum.ACTIVE
            )
            .all()
        )
        threads = []
        for a in active_assignments:
            unread_cnt = (
                db.query(Message)
                .filter(
                    Message.assignment_id == a.id,
                    Message.recipient_id == current_user.id,
                    Message.is_read == False
                )
                .count()
            )
            last_msg = (
                db.query(Message)
                .filter(Message.assignment_id == a.id)
                .order_by(Message.id.desc())
                .first()
            )
            threads.append({
                "assignment": a,
                "unread_count": unread_cnt,
                "last_message": last_msg
            })

        return templates.TemplateResponse(
            request=request,
            name="messaging/index.html",
            context={
                "csrf_token": csrf_token,
                "current_user": current_user,
                "active_nav": "messages",
                "threads": threads,
                "has_assignment": len(threads) > 0,
                "role": "SUPERVISOR"
            }
        )

    else:
        # Coordinator view
        return templates.TemplateResponse(
            request=request,
            name="messaging/index.html",
            context={
                "csrf_token": csrf_token,
                "current_user": current_user,
                "active_nav": "messages",
                "threads": [],
                "has_assignment": False,
                "role": "ADMIN"
            }
        )

@router.get("/{assignment_id}", response_class=HTMLResponse)
def view_thread(
    request: Request,
    assignment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    assignment = db.query(TopicAssignment).filter(TopicAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Project assignment not found.")

    # Tampering Guard: strictly verify student or supervisor membership
    if not _check_assignment_access(assignment, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you are not authorized to view this project conversation."
        )

    # Mark incoming unread messages as read
    db.query(Message).filter(
        Message.assignment_id == assignment_id,
        Message.recipient_id == current_user.id,
        Message.is_read == False
    ).update({
        Message.is_read: True,
        Message.read_at: utc_now()
    })
    db.commit()

    # Load messages chronological (newest at bottom)
    messages = (
        db.query(Message)
        .filter(Message.assignment_id == assignment_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    other_user = (
        assignment.supervisor.user
        if current_user.id == assignment.student.user_id
        else assignment.student.user
    )

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="messaging/thread.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "assignment": assignment,
            "messages": messages,
            "other_user": other_user,
            "active_nav": "messages"
        }
    )

@router.post("/{assignment_id}/send")
def send_message(
    request: Request,
    assignment_id: int,
    content: str = Form(...),
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    token = csrf_token or request.headers.get("X-CSRF-Token")
    if not validate_csrf_token(request, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    assignment = db.query(TopicAssignment).filter(TopicAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Project assignment not found.")

    # Tampering Guard
    if not _check_assignment_access(assignment, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: unauthorized assignment conversation."
        )

    clean_content = content.strip()
    if not clean_content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")
    if len(clean_content) > 2000:
        raise HTTPException(status_code=400, detail="Message content exceeds 2000 character limit.")

    recipient_id = (
        assignment.supervisor.user_id
        if current_user.id == assignment.student.user_id
        else assignment.student.user_id
    )

    new_msg = Message(
        assignment_id=assignment.id,
        sender_id=current_user.id,
        recipient_id=recipient_id,
        content=clean_content
    )
    db.add(new_msg)
    db.flush()

    # Trigger notification to recipient
    create_notification(
        db=db,
        user_id=recipient_id,
        title=f"New message from {current_user.username}",
        message=f"New message on topic '{assignment.topic.title}': {clean_content[:60]}...",
        link=f"/messaging/{assignment.id}"
    )
    db.commit()

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({
            "status": "success",
            "message_id": new_msg.id,
            "created_at": new_msg.created_at.strftime("%b %d, %H:%M")
        })

    return RedirectResponse(
        url=f"/messaging/{assignment_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.get("/{assignment_id}/poll")
def poll_messages(
    request: Request,
    assignment_id: int,
    after_id: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    assignment = db.query(TopicAssignment).filter(TopicAssignment.id == assignment_id).first()
    if not assignment or not _check_assignment_access(assignment, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    new_messages = (
        db.query(Message)
        .filter(
            Message.assignment_id == assignment_id,
            Message.id > after_id
        )
        .order_by(Message.id.asc())
        .all()
    )

    # Mark incoming as read
    for m in new_messages:
        if m.recipient_id == current_user.id and not m.is_read:
            m.is_read = True
            m.read_at = utc_now()
    db.commit()

    return JSONResponse({
        "messages": [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "sender_name": m.sender.username,
                "is_me": m.sender_id == current_user.id,
                "content": m.content,
                "created_at": m.created_at.strftime("%b %d, %H:%M")
            }
            for m in new_messages
        ]
    })
