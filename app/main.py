import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.core.rate_limiter import limiter
from app.core.dependencies import AuthenticationRequiredException, ForbiddenRoleException
from app.routers import health, auth, profile, dashboard, coordinator, topics, messaging, forum, guidelines, notifications, submissions, assessments, archive

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spms.main")

BASE_DIR = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup verification
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            logger.info("=" * 60)
            logger.info(f"SPMS STARTUP: Successfully connected to MySQL 8.0!")
            logger.info(f"MySQL Version: {version}")
            logger.info(f"Database Name: {settings.DB_NAME}")
            logger.info(f"Runtime DB User: {settings.DB_USER}")
            logger.info("=" * 60)
    except Exception as e:
        logger.error(f"FATAL: Database connection failed on startup: {e}")
    yield
    # Shutdown
    engine.dispose()

docs_url = "/docs" if settings.ENVIRONMENT == "development" else None
redoc_url = "/redoc" if settings.ENVIRONMENT == "development" else None
openapi_url = "/openapi.json" if settings.ENVIRONMENT == "development" else None

app = FastAPI(
    title="Student Project Management System",
    description="SPMS Final-Year Project Management Automation",
    version="1.0.0",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
    lifespan=lifespan
)

# Attach rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security Headers Middleware with Cryptographic Nonce
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    csp = (
        "default-src 'self'; "
        f"script-src 'self' https://cdn.jsdelivr.net 'nonce-{nonce}'; "
        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    response.headers["Content-Security-Policy"] = csp
    return response

# Starlette SessionMiddleware (signed HttpOnly SameSite cookie)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=settings.SESSION_MAX_AGE_SECONDS,
    same_site=settings.SESSION_COOKIE_SAMESITE,
    https_only=settings.SESSION_COOKIE_SECURE
)

# Mount Static Files
static_dir = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["csp_nonce"] = lambda request: getattr(getattr(request, "state", None), "csp_nonce", "")

# Custom Exception Handlers
@app.exception_handler(AuthenticationRequiredException)
async def auth_required_handler(request: Request, exc: AuthenticationRequiredException):
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)

@app.exception_handler(ForbiddenRoleException)
async def forbidden_role_handler(request: Request, exc: ForbiddenRoleException):
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head><title>403 Forbidden</title><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css'></head>
        <body class='p-5 bg-light text-center'>
            <div class='card p-5 mx-auto shadow-sm' style='max-width: 500px;'>
                <h1 class='text-danger'>403</h1>
                <h4>Access Denied</h4>
                <p class='text-muted'>{exc.detail}</p>
                <a href='/dashboard' class='btn btn-primary mt-3'>Return to Dashboard</a>
            </div>
        </body>
        </html>
        """,
        status_code=status.HTTP_403_FORBIDDEN
    )

# Include Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(dashboard.router)
app.include_router(coordinator.router)
app.include_router(topics.router)
app.include_router(messaging.router)
app.include_router(forum.router)
app.include_router(guidelines.router)
app.include_router(notifications.router)
app.include_router(submissions.router)
app.include_router(assessments.router)
app.include_router(archive.router)

@app.get("/messages")
def redirect_messages():
    return RedirectResponse(url="/messaging", status_code=status.HTTP_303_SEE_OTHER)
