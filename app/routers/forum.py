from datetime import datetime
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.user import User, RoleEnum, Department
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.communication import ForumThread, ForumReply
from app.core.dependencies import get_current_user
from app.core.security import get_or_create_csrf_token, validate_csrf_token
from app.core.datetime_util import utc_now
from app.services.notification_service import create_notification

router = APIRouter(prefix="/forum", tags=["Forum"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def _get_user_department_id(user: User, db: Session) -> Optional[int]:
    """Resolves user's assigned department ID."""
    if user.role == RoleEnum.STUDENT:
        student = db.query(Student).filter(Student.user_id == user.id).first()
        return student.department_id if student else None
    elif user.role == RoleEnum.SUPERVISOR:
        supervisor = db.query(Supervisor).filter(Supervisor.user_id == user.id).first()
        return supervisor.department_id if supervisor else None
    return None

def _enforce_department_isolation(user: User, thread_dept_id: int, db: Session):
    """Enforces strict department scoping. Coordinator can access all."""
    if user.role == RoleEnum.ADMIN:
        return
    user_dept_id = _get_user_department_id(user, db)
    if user_dept_id is None or user_dept_id != thread_dept_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Department isolation violation. You can only access discussions within your own department."
        )

@router.get("", response_class=HTMLResponse)
def list_threads(
    request: Request,
    page: int = Query(1, ge=1),
    dept_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists department-scoped discussion threads with pagination."""
    PAGE_SIZE = 15
    user_dept_id = _get_user_department_id(current_user, db)

    # Determine scoped department
    if current_user.role == RoleEnum.ADMIN:
        target_dept_id = dept_id or (user_dept_id if user_dept_id else 1)
    else:
        target_dept_id = user_dept_id
        if not target_dept_id:
            raise HTTPException(status_code=400, detail="User is not affiliated with any department.")

    department = db.query(Department).filter(Department.id == target_dept_id).first()
    departments = db.query(Department).all() if current_user.role == RoleEnum.ADMIN else []

    query = (
        db.query(ForumThread)
        .filter(ForumThread.department_id == target_dept_id)
        .order_by(ForumThread.is_pinned.desc(), ForumThread.updated_at.desc())
    )
    total_threads = query.count()
    threads = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    total_pages = max(1, (total_threads + PAGE_SIZE - 1) // PAGE_SIZE)

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="forum/index.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "department": department,
            "departments": departments,
            "threads": threads,
            "page": page,
            "total_pages": total_pages,
            "total_threads": total_threads,
            "active_nav": "forum"
        }
    )

@router.get("/new", response_class=HTMLResponse)
def new_thread_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_dept_id = _get_user_department_id(current_user, db)
    if current_user.role != RoleEnum.ADMIN and not user_dept_id:
        raise HTTPException(status_code=400, detail="User has no department affiliation.")

    departments = db.query(Department).all() if current_user.role == RoleEnum.ADMIN else []
    department = db.query(Department).filter(Department.id == user_dept_id).first() if user_dept_id else None

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="forum/new.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "department": department,
            "departments": departments,
            "active_nav": "forum"
        }
    )

@router.post("/new")
def create_thread(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    department_id: Optional[int] = Form(None),
    is_pinned: bool = Form(False),
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_title = title.strip()
    clean_content = content.strip()

    if len(clean_title) < 3 or len(clean_title) > 255:
        raise HTTPException(status_code=400, detail="Title must be between 3 and 255 characters.")
    if len(clean_content) < 5:
        raise HTTPException(status_code=400, detail="Discussion content must be at least 5 characters.")

    if current_user.role == RoleEnum.ADMIN:
        target_dept_id = department_id
        if not target_dept_id:
            first_dept = db.query(Department).first()
            target_dept_id = first_dept.id if first_dept else 1
    else:
        target_dept_id = _get_user_department_id(current_user, db)
        is_pinned = False  # Only coordinator can pin

    if not target_dept_id:
        raise HTTPException(status_code=400, detail="Cannot create thread without a department.")

    thread = ForumThread(
        department_id=target_dept_id,
        user_id=current_user.id,
        title=clean_title,
        content=clean_content,
        is_pinned=is_pinned
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    return RedirectResponse(
        url=f"/forum/{thread.id}",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.get("/{thread_id}", response_class=HTMLResponse)
def view_thread(
    request: Request,
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    thread = db.query(ForumThread).filter(ForumThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Forum thread not found.")

    # Strict Department Isolation Check
    _enforce_department_isolation(current_user, thread.department_id, db)

    replies = (
        db.query(ForumReply)
        .filter(ForumReply.thread_id == thread_id)
        .order_by(ForumReply.created_at.asc())
        .all()
    )

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="forum/view.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "thread": thread,
            "replies": replies,
            "active_nav": "forum"
        }
    )

@router.post("/{thread_id}/reply")
def reply_thread(
    request: Request,
    thread_id: int,
    content: str = Form(...),
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    thread = db.query(ForumThread).filter(ForumThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")

    # Strict Department Isolation Check
    _enforce_department_isolation(current_user, thread.department_id, db)

    if thread.is_closed:
        raise HTTPException(status_code=400, detail="This discussion thread is closed for further replies.")

    clean_content = content.strip()
    if not clean_content:
        raise HTTPException(status_code=400, detail="Reply cannot be empty.")

    reply = ForumReply(
        thread_id=thread.id,
        user_id=current_user.id,
        content=clean_content
    )
    db.add(reply)
    thread.updated_at = utc_now()
    db.flush()

    # Trigger notification to thread author (if different user)
    if thread.user_id != current_user.id:
        create_notification(
            db=db,
            user_id=thread.user_id,
            title=f"New forum reply: {thread.title[:30]}...",
            message=f"{current_user.username} replied: {clean_content[:60]}...",
            link=f"/forum/{thread.id}"
        )

    db.commit()

    return RedirectResponse(
        url=f"/forum/{thread.id}#reply-{reply.id}",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/{thread_id}/delete")
def delete_thread(
    request: Request,
    thread_id: int,
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    thread = db.query(ForumThread).filter(ForumThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found.")

    # Only Author or Coordinator can delete
    if thread.user_id != current_user.id and current_user.role != RoleEnum.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Only the thread author or project coordinator can delete this thread."
        )

    db.delete(thread)
    db.commit()

    return RedirectResponse(
        url="/forum",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post("/reply/{reply_id}/delete")
def delete_reply(
    request: Request,
    reply_id: int,
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    reply = db.query(ForumReply).filter(ForumReply.id == reply_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found.")

    thread_id = reply.thread_id
    # Only Author or Coordinator can delete
    if reply.user_id != current_user.id and current_user.role != RoleEnum.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Only the reply author or project coordinator can delete this reply."
        )

    db.delete(reply)
    db.commit()

    return RedirectResponse(
        url=f"/forum/{thread_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )
