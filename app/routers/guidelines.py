import os
import uuid
import re
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, RoleEnum, AcademicSession
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.guideline import Guideline
from app.core.dependencies import get_current_user, require_role
from app.core.security import get_or_create_csrf_token, validate_csrf_token
from app.services.notification_service import create_notification

router = APIRouter(prefix="/guidelines", tags=["Guidelines"])
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR.parent / "storage" / "guidelines"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Max allowed size: 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024

# Allowed extensions and magic byte signatures
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream"  # Browser generic fallback
}

def _validate_uploaded_file(file: UploadFile, content: bytes):
    """Enforces strict extension, MIME type, size, and magic byte validation."""
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum allowed size of 10 MB (received {len(content) / (1024*1024):.2f} MB)."
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file extension '{ext}'. Only PDF, DOC, and DOCX files are permitted."
        )

    # Magic byte signature check
    if ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="Invalid PDF file header.")
    elif ext == ".doc":
        # OLE CFB signature
        if not content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise HTTPException(status_code=400, detail="Invalid DOC file format.")
    elif ext == ".docx":
        # ZIP file header (PK\x03\x04)
        if not content.startswith(b"PK\x03\x04"):
            raise HTTPException(status_code=400, detail="Invalid DOCX file archive format.")

def _sanitize_filename(name: str) -> str:
    """Sanitizes filename for safe Content-Disposition headers."""
    clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)
    return clean[:128] or "guideline_document"

@router.get("", response_class=HTMLResponse)
def list_guidelines(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all published guidelines with download links. Coordinator gets manage controls."""
    guidelines = db.query(Guideline).order_by(Guideline.created_at.desc()).all()
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="guidelines/index.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "guidelines": guidelines,
            "is_coordinator": current_user.role == RoleEnum.ADMIN,
            "active_nav": "guidelines"
        }
    )

@router.post("/upload")
async def upload_guideline(
    request: Request,
    title: str = Form(...),
    description: Optional[str] = Form(""),
    file: UploadFile = File(...),
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(require_role([RoleEnum.ADMIN])),
    db: Session = Depends(get_db)
):
    """Coordinator uploads a project guideline document."""
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_title = title.strip()
    if not clean_title or len(clean_title) > 128:
        raise HTTPException(status_code=400, detail="Title must be between 1 and 128 characters.")

    file_bytes = await file.read()
    _validate_uploaded_file(file, file_bytes)

    # Generate secure UUID filename outside web root
    ext = Path(file.filename or "file").suffix.lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    target_path = STORAGE_DIR / stored_name

    with open(target_path, "wb") as f:
        f.write(file_bytes)

    orig_clean = _sanitize_filename(Path(file.filename or f"guideline{ext}").name)
    guideline = Guideline(
        coordinator_id=current_user.id,
        title=clean_title,
        description=description.strip() if description else None,
        file_path=str(target_path),
        original_filename=orig_clean,
        file_size=len(file_bytes)
    )
    db.add(guideline)
    db.flush()

    # Broadcast notification to active session students & supervisors
    active_sess = db.query(AcademicSession).filter(AcademicSession.is_active == True).first()
    if active_sess:
        active_student_uids = [
            s.user_id for s in db.query(Student.user_id).filter(Student.session_id == active_sess.id).all()
        ]
        supervisor_uids = [
            sup.user_id for sup in db.query(Supervisor.user_id).all()
        ]
        recipient_uids = set(active_student_uids + supervisor_uids)
        for uid in recipient_uids:
            create_notification(
                db=db,
                user_id=uid,
                title="New Guideline Published",
                message=f"Coordinator published: '{clean_title}'",
                link="/guidelines"
            )

    db.commit()
    return RedirectResponse(url="/guidelines", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/{guideline_id}/edit")
def edit_guideline(
    request: Request,
    guideline_id: int,
    title: str = Form(...),
    description: Optional[str] = Form(""),
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(require_role([RoleEnum.ADMIN])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    guideline = db.query(Guideline).filter(Guideline.id == guideline_id).first()
    if not guideline:
        raise HTTPException(status_code=404, detail="Guideline not found.")

    clean_title = title.strip()
    if not clean_title or len(clean_title) > 128:
        raise HTTPException(status_code=400, detail="Title must be between 1 and 128 characters.")

    guideline.title = clean_title
    guideline.description = description.strip() if description else None
    db.commit()

    return RedirectResponse(url="/guidelines", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/{guideline_id}/delete")
def delete_guideline(
    request: Request,
    guideline_id: int,
    csrf_token: Optional[str] = Form(None),
    current_user: User = Depends(require_role([RoleEnum.ADMIN])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    guideline = db.query(Guideline).filter(Guideline.id == guideline_id).first()
    if not guideline:
        raise HTTPException(status_code=404, detail="Guideline not found.")

    # Remove file from disk
    if guideline.file_path and os.path.exists(guideline.file_path):
        try:
            os.remove(guideline.file_path)
        except OSError:
            pass

    db.delete(guideline)
    db.commit()

    return RedirectResponse(url="/guidelines", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/{guideline_id}/download")
def download_guideline(
    guideline_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Authenticated file download route."""
    guideline = db.query(Guideline).filter(Guideline.id == guideline_id).first()
    if not guideline:
        raise HTTPException(status_code=404, detail="Guideline document not found.")

    if not os.path.exists(guideline.file_path):
        raise HTTPException(status_code=404, detail="File missing from storage disk.")

    ext = Path(guideline.file_path).suffix.lower()
    media_type = "application/pdf" if ext == ".pdf" else "application/octet-stream"

    return FileResponse(
        path=guideline.file_path,
        filename=guideline.original_filename,
        media_type=media_type
    )
