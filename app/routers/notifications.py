from datetime import datetime
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.guideline import Notification
from app.core.dependencies import get_current_user
from app.core.security import get_or_create_csrf_token, validate_csrf_token
from app.core.datetime_util import utc_now

router = APIRouter(prefix="/notifications", tags=["Notifications"])
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@router.get("", response_class=HTMLResponse)
def list_notifications(
    request: Request,
    page: int = Query(1, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Full notifications page with pagination."""
    PAGE_SIZE = 20
    query = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )
    total_count = query.count()
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .count()
    )
    notifications = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="notifications/index.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "notifications": notifications,
            "unread_count": unread_count,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "active_nav": "notifications"
        }
    )

@router.get("/unread")
def get_unread_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """AJAX polling endpoint for navbar bell badge and preview dropdown."""
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .order_by(Notification.created_at.desc())
        .limit(5)
        .all()
    )
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .count()
    )

    return JSONResponse({
        "count": unread_count,
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "link": n.link or "#",
                "created_at": n.created_at.strftime("%b %d, %H:%M")
            }
            for n in unread
        ]
    })

@router.post("/{notification_id}/read")
def mark_as_read(
    request: Request,
    notification_id: int,
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    token = csrf_token or request.headers.get("X-CSRF-Token")
    if not validate_csrf_token(request, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")

    notif.is_read = True
    notif.read_at = utc_now()
    db.commit()

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "success", "id": notification_id})

    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/read-all")
def mark_all_as_read(
    request: Request,
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    token = csrf_token or request.headers.get("X-CSRF-Token")
    if not validate_csrf_token(request, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    ).update({
        Notification.is_read: True,
        Notification.read_at: utc_now()
    })
    db.commit()

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "success"})

    return RedirectResponse(url="/notifications", status_code=status.HTTP_303_SEE_OTHER)
