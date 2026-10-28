from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.models.user import User, RoleEnum
from app.models.student import Student
from app.core.dependencies import get_current_user, require_role
from app.core.security import get_or_create_csrf_token, validate_csrf_token

router = APIRouter(prefix="/profile", tags=["Profile"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/student", response_class=HTMLResponse)
def view_student_profile(
    request: Request,
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
):
    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="profile/student_profile.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "student": student,
            "user": current_user,
            "active_nav": "profile"
        }
    )

@router.post("/student", response_class=HTMLResponse)
def update_student_profile(
    request: Request,
    email: str = Form(...),
    phone: str = Form(...),
    github_url: str = Form(None),
    linkedin_url: str = Form(None),
    skills: str = Form(None),
    show_contact_to_students: bool = Form(False),
    csrf_token: str = Form(None),
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    student = db.query(Student).filter(Student.user_id == current_user.id).first()

    clean_email = email.strip().lower()
    collision = (
        db.query(User)
        .filter(User.email == clean_email, User.id != current_user.id)
        .first()
    )
    if collision:
        return templates.TemplateResponse(
            request=request,
            name="profile/student_profile.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "current_user": current_user,
                "student": student,
                "user": current_user,
                "active_nav": "profile",
                "error": "This email address is already in use by another account."
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    current_user.email = clean_email
    student.phone = phone.strip()
    student.github_url = github_url.strip() if github_url else None
    student.linkedin_url = linkedin_url.strip() if linkedin_url else None
    student.skills = skills.strip() if skills else None
    student.show_contact_to_students = show_contact_to_students

    db.commit()

    return templates.TemplateResponse(
        request=request,
        name="profile/student_profile.html",
        context={
            "csrf_token": get_or_create_csrf_token(request),
            "current_user": current_user,
            "student": student,
            "user": current_user,
            "active_nav": "profile",
            "success": "Your profile information has been successfully updated!"
        }
    )
