from typing import List, Optional
from fastapi import Depends, Request, HTTPException, status, Form
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.core.security import validate_csrf_token

class AuthenticationRequiredException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in."
        )

class ForbiddenRoleException(HTTPException):
    def __init__(self, detail: str = "Access denied: insufficient permissions."):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
        )

class PasswordChangeRequiredException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Password change required before proceeding.",
            headers={"Location": "/auth/change-password"}
        )

def verify_csrf(request: Request, csrf_token: Optional[str] = Form(None)):
    """Validates CSRF token in form payload on state-changing requests."""
    # Also support header X-CSRF-Token for AJAX
    token = csrf_token or request.headers.get("X-CSRF-Token")
    if not validate_csrf_token(request, token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token."
        )

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Enforces authentication, status check, session_version validity,
    and mandatory password change.
    """
    user_id = request.session.get("user_id")
    session_version = request.session.get("session_version")
    
    if not user_id or session_version is None:
        raise AuthenticationRequiredException()

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        raise AuthenticationRequiredException()

    # Recheck account status on every request
    if user.status != AccountStatusEnum.APPROVED:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account access denied (Status: {user.status.value}). Remarks: {user.remarks or 'None'}"
        )

    # Invalidate session if session_version in cookie differs from database
    if user.session_version != session_version:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or was invalidated by a password change. Please log in again."
        )

    # Enforce password change check on staff/students with must_change_password flag
    path = request.url.path
    allowed_change_paths = [
        "/auth/change-password",
        "/auth/logout",
        "/health",
        "/static"
    ]
    if user.must_change_password and not any(path.startswith(p) for p in allowed_change_paths):
        raise PasswordChangeRequiredException()

    return user

def require_role(allowed_roles: List[RoleEnum]):
    """Role-based access dependency."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenRoleException(
                f"Role '{current_user.role.value}' is not authorized to access this resource."
            )
        return current_user
    return role_checker

def get_current_student(
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
) -> Student:
    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    return student

def get_current_supervisor(
    current_user: User = Depends(require_role([RoleEnum.SUPERVISOR])),
    db: Session = Depends(get_db)
) -> Supervisor:
    supervisor = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor profile not found.")
    return supervisor

def get_current_coordinator(
    current_user: User = Depends(require_role([RoleEnum.ADMIN]))
) -> User:
    return current_user
