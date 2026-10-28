import secrets
import bcrypt
from fastapi import Request, HTTPException, status
from itsdangerous import URLSafeTimedSerializer
from app.config import settings

serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="spms-resubmit-salt")

def hash_password(plain_password: str) -> str:
    """Hash password using direct bcrypt with work factor 12."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def get_or_create_csrf_token(request: Request) -> str:
    """Retrieve or generate per-session CSRF token."""
    token = request.session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["_csrf_token"] = token
    return token

def validate_csrf_token(request: Request, submitted_token: str | None) -> bool:
    """Validate submitted token against session CSRF token."""
    expected_token = request.session.get("_csrf_token")
    if not expected_token or not submitted_token:
        return False
    return secrets.compare_digest(str(expected_token), str(submitted_token))

def generate_resubmit_token(user_id: int) -> str:
    """Generate signed, single-use token for rejected student resubmission (1 hour validity)."""
    return serializer.dumps({"resubmit_user_id": user_id})

def verify_resubmit_token(token: str, max_age: int = 3600) -> int | None:
    """Verify signed token and return user_id, or None if invalid/expired."""
    try:
        data = serializer.loads(token, max_age=max_age)
        return data.get("resubmit_user_id")
    except Exception:
        return None
