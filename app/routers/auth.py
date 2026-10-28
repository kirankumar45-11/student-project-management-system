import logging
from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pathlib import Path

from app.database import get_db
from app.models.user import User, Department, AcademicSession, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.core.security import (
    hash_password, verify_password, get_or_create_csrf_token,
    validate_csrf_token, generate_resubmit_token, verify_resubmit_token
)
from app.core.dependencies import verify_csrf, get_current_user
from app.core.rate_limiter import limiter

logger = logging.getLogger("spms.auth")

router = APIRouter(tags=["Authentication"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "csrf_token": csrf_token,
            "current_user": None
        }
    )

@router.post("/auth/login", response_class=HTMLResponse)
@limiter.limit("60/minute")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(None),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        csrf_token = get_or_create_csrf_token(request)
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "csrf_token": csrf_token,
                "current_user": None,
                "error": "Invalid or missing CSRF token. Please refresh and try again.",
                "username": username
            },
            status_code=status.HTTP_403_FORBIDDEN
        )

    clean_user = username.strip()
    user = (
        db.query(User)
        .filter(or_(User.username == clean_user, User.email == clean_user))
        .first()
    )

    if not user or not verify_password(password, user.password_hash):
        csrf_token = get_or_create_csrf_token(request)
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "csrf_token": csrf_token,
                "current_user": None,
                "error": "Invalid username/USN or password.",
                "username": username
            },
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    if user.status == AccountStatusEnum.PENDING:
        csrf_token = get_or_create_csrf_token(request)
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "csrf_token": csrf_token,
                "current_user": None,
                "error": "Your registration is currently pending coordinator approval. You will receive an email once approved.",
                "username": username
            },
            status_code=status.HTTP_403_FORBIDDEN
        )

    if user.status == AccountStatusEnum.REJECTED:
        resubmit_token = generate_resubmit_token(user.id)
        csrf_token = get_or_create_csrf_token(request)
        remarks_msg = f"Your registration was rejected. Coordinator remarks: '{user.remarks or 'Please correct your details'}'. Use the link below to resubmit."
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "csrf_token": csrf_token,
                "current_user": None,
                "error": remarks_msg,
                "resubmit_token": resubmit_token,
                "username": username
            },
            status_code=status.HTTP_403_FORBIDDEN
        )

    # Approved user
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["session_version"] = user.session_version
    get_or_create_csrf_token(request)

    if user.must_change_password:
        return RedirectResponse(url="/auth/change-password", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/auth/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    departments = db.query(Department).all()
    sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={
            "csrf_token": csrf_token,
            "departments": departments,
            "sessions": sessions,
            "current_user": None,
            "form_data": None
        }
    )

@router.post("/auth/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    usn: str = Form(...),
    full_name: str = Form(...),
    department_id: int = Form(...),
    session_id: int = Form(...),
    semester: int = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
    github_url: str = Form(None),
    linkedin_url: str = Form(None),
    skills: str = Form(None),
    show_contact_to_students: bool = Form(False),
    csrf_token: str = Form(None),
    db: Session = Depends(get_db)
):
    form_data = {
        "usn": usn, "full_name": full_name, "department_id": department_id,
        "session_id": session_id, "semester": semester, "email": email,
        "phone": phone, "github_url": github_url, "linkedin_url": linkedin_url,
        "skills": skills, "show_contact_to_students": show_contact_to_students
    }

    if not validate_csrf_token(request, csrf_token):
        departments = db.query(Department).all()
        sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "departments": departments, "sessions": sessions,
                "current_user": None, "form_data": form_data,
                "error": "Invalid CSRF token. Please reload the page."
            },
            status_code=status.HTTP_403_FORBIDDEN
        )

    clean_usn = usn.strip().upper()
    clean_email = email.strip().lower()

    existing_user = db.query(User).filter(or_(User.username == clean_usn, User.email == clean_email)).first()
    if existing_user:
        departments = db.query(Department).all()
        sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "departments": departments, "sessions": sessions,
                "current_user": None, "form_data": form_data,
                "error": "An account with this USN or Email already exists."
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    new_user = User(
        username=clean_usn,
        email=clean_email,
        password_hash=hash_password(password),
        role=RoleEnum.STUDENT,
        status=AccountStatusEnum.PENDING,
        must_change_password=False,
        session_version=1
    )
    db.add(new_user)
    db.flush()

    academic_session = db.query(AcademicSession).filter(AcademicSession.id == session_id).first()
    academic_year = academic_session.name if academic_session else "2025-2026"

    new_student = Student(
        user_id=new_user.id,
        department_id=department_id,
        session_id=session_id,
        usn=clean_usn,
        full_name=full_name.strip(),
        semester=semester,
        academic_year=academic_year,
        phone=phone.strip(),
        github_url=github_url.strip() if github_url else None,
        linkedin_url=linkedin_url.strip() if linkedin_url else None,
        skills=skills.strip() if skills else None,
        show_contact_to_students=show_contact_to_students
    )
    db.add(new_student)
    db.commit()

    csrf = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "csrf_token": csrf,
            "current_user": None,
            "success": "Registration submitted successfully! Your account is pending coordinator approval."
        }
    )

@router.get("/register/resubmit", response_class=HTMLResponse)
def resubmit_page(
    request: Request,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    user_id = verify_resubmit_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resubmission token is invalid or has expired."
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.status != AccountStatusEnum.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is not in a rejected state."
        )

    student = db.query(Student).filter(Student.user_id == user.id).first()
    departments = db.query(Department).all()
    sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
    csrf_token = get_or_create_csrf_token(request)

    return templates.TemplateResponse(
        request=request,
        name="auth/resubmit.html",
        context={
            "csrf_token": csrf_token,
            "resubmit_token": token,
            "user": user,
            "student": student,
            "remarks": user.remarks,
            "departments": departments,
            "sessions": sessions,
            "current_user": None
        }
    )

@router.post("/register/resubmit", response_class=HTMLResponse)
def resubmit_submit(
    request: Request,
    resubmit_token: str = Form(...),
    usn: str = Form(...),
    full_name: str = Form(...),
    department_id: int = Form(...),
    session_id: int = Form(...),
    semester: int = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    github_url: str = Form(None),
    linkedin_url: str = Form(None),
    skills: str = Form(None),
    csrf_token: str = Form(None),
    db: Session = Depends(get_db)
):
    user_id = verify_resubmit_token(resubmit_token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid resubmission token.")

    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.status != AccountStatusEnum.REJECTED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account is not rejected.")

    student = db.query(Student).filter(Student.user_id == user.id).first()

    clean_usn = usn.strip().upper()
    clean_email = email.strip().lower()

    existing_other = (
        db.query(User)
        .filter(or_(User.username == clean_usn, User.email == clean_email))
        .filter(User.id != user.id)
        .first()
    )
    if existing_other:
        departments = db.query(Department).all()
        sessions = db.query(AcademicSession).filter(AcademicSession.is_active == True).all()
        return templates.TemplateResponse(
            request=request,
            name="auth/resubmit.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "resubmit_token": resubmit_token, "user": user, "student": student,
                "remarks": user.remarks, "departments": departments, "sessions": sessions,
                "current_user": None,
                "error": "The updated USN or Email is already registered by another account."
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    user.username = clean_usn
    user.email = clean_email
    user.status = AccountStatusEnum.PENDING
    user.remarks = "Resubmitted with updated details for coordinator review."

    student.usn = clean_usn
    student.full_name = full_name.strip()
    student.department_id = department_id
    student.session_id = session_id
    student.semester = semester
    student.phone = phone.strip()
    student.github_url = github_url.strip() if github_url else None
    student.linkedin_url = linkedin_url.strip() if linkedin_url else None
    student.skills = skills.strip() if skills else None

    db.commit()

    csrf = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "csrf_token": csrf,
            "current_user": None,
            "success": "Your corrected registration has been submitted! It is now pending coordinator review."
        }
    )

@router.get("/auth/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, current_user: User = Depends(get_current_user)):
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="auth/change_password.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user
        }
    )

@router.post("/auth/change-password", response_class=HTMLResponse)
def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        return templates.TemplateResponse(
            request=request,
            name="auth/change_password.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "current_user": current_user,
                "error": "Invalid CSRF token."
            },
            status_code=status.HTTP_403_FORBIDDEN
        )

    if not verify_password(current_password, current_user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="auth/change_password.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "current_user": current_user,
                "error": "Current password is incorrect."
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if len(new_password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="auth/change_password.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "current_user": current_user,
                "error": "New password must be at least 8 characters long."
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if new_password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="auth/change_password.html",
            context={
                "csrf_token": get_or_create_csrf_token(request),
                "current_user": current_user,
                "error": "New password and confirmation do not match."
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    current_user.password_hash = hash_password(new_password)
    current_user.must_change_password = False
    current_user.session_version += 1
    db.commit()

    request.session["session_version"] = current_user.session_version
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/auth/logout")
def logout(
    request: Request,
    csrf_token: str = Form(None)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token on logout."
        )

    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
