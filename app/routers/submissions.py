import os
import uuid
import re
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.user import User, RoleEnum, AcademicSession
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import TopicAssignment, AssignmentStatusEnum
from app.models.submission import (
    Submission, Feedback, Deadline, ChapterEnum, FeedbackStatusEnum, CHAPTER_DISPLAY_NAMES
)
from app.core.dependencies import get_current_user, require_role
from app.core.security import get_or_create_csrf_token, validate_csrf_token
from app.core.datetime_util import utc_now, ensure_utc
from app.services.notification_service import create_notification

router = APIRouter(prefix="/submissions", tags=["Submissions & Pipeline"])
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR.parent / "storage" / "submissions"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Max allowed submission size: 10MB
MAX_SUBMISSION_FILE_SIZE = 10 * 1024 * 1024

# Allowed extensions and magic byte headers
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}

CHAPTER_SEQUENCE = [
    ChapterEnum.SYNOPSIS,
    ChapterEnum.SRS_DESIGN,
    ChapterEnum.IMPLEMENTATION,
    ChapterEnum.FINAL_REPORT
]

GITHUB_URL_REGEX = re.compile(r"^https://github\.com/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)/?$")


def validate_github_url(url: str) -> bool:
    """Validates that a URL is strictly formatted as https://github.com/user/repo."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    match = GITHUB_URL_REGEX.match(url)
    if not match:
        return False
    user, repo = match.groups()
    if repo.endswith(".git"):
        repo = repo[:-4]
    return bool(user and repo)


def _validate_uploaded_file(file: UploadFile, content: bytes):
    """Enforces 10MB limit, valid extension, and magic-byte signatures."""
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > MAX_SUBMISSION_FILE_SIZE:
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
        if not content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise HTTPException(status_code=400, detail="Invalid DOC (OLE Compound File) header.")
    elif ext == ".docx":
        if not content.startswith(b"PK\x03\x04"):
            raise HTTPException(status_code=400, detail="Invalid DOCX (ZIP archive) header.")


def _render_pipeline_response(
    request: Request,
    current_user: User,
    db: Session,
    error: Optional[str] = None,
    status_code: int = 200
):
    student = current_user.student_profile
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    assignment = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.student_id == student.id, TopicAssignment.status.in_([AssignmentStatusEnum.ACTIVE, AssignmentStatusEnum.COMPLETED]))
        .order_by(TopicAssignment.id.desc())
        .first()
    )

    csrf_token = get_or_create_csrf_token(request)
    now = utc_now()

    if not assignment:
        return templates.TemplateResponse(
            request=request,
            name="submissions/index.html",
            context={
                "csrf_token": csrf_token,
                "current_user": current_user,
                "student": student,
                "assignment": None,
                "error": error,
                "active_nav": "submissions"
            },
            status_code=status_code
        )

    # Fetch deadlines for this session
    deadlines = db.query(Deadline).filter(Deadline.session_id == assignment.session_id).all()
    deadline_by_chapter = {d.chapter: d for d in deadlines}

    # Fetch all submissions for this assignment
    submissions = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment.id)
        .order_by(Submission.chapter.asc(), Submission.version.asc())
        .all()
    )
    submissions_by_chapter = {}
    for s in submissions:
        submissions_by_chapter.setdefault(s.chapter, []).append(s)

    # Build Pipeline Data for all 4 chapters in sequence
    pipeline = []
    previous_chapter_approved = True
    approved_count = 0

    for ch in CHAPTER_SEQUENCE:
        chapter_subs = submissions_by_chapter.get(ch, [])
        latest_sub = chapter_subs[-1] if chapter_subs else None
        latest_feedback = latest_sub.feedback[-1] if (latest_sub and latest_sub.feedback) else None

        # Determine status
        is_approved = latest_feedback is not None and latest_feedback.status == FeedbackStatusEnum.APPROVED
        is_needs_revision = latest_feedback is not None and latest_feedback.status == FeedbackStatusEnum.NEEDS_REVISION
        is_under_review = latest_sub is not None and latest_feedback is None

        if is_approved:
            state = "APPROVED"
            approved_count += 1
            can_submit = False
        elif not previous_chapter_approved:
            state = "LOCKED"
            can_submit = False
        elif is_under_review:
            state = "UNDER_REVIEW"
            can_submit = False
        elif is_needs_revision:
            state = "NEEDS_REVISION"
            can_submit = True
        else:
            state = "READY_TO_SUBMIT"
            can_submit = True

        previous_chapter_approved = is_approved

        # Deadline evaluation
        dl = deadline_by_chapter.get(ch)
        is_overdue = False
        remaining_str = "No deadline configured"
        can_submit_deadline = True

        if dl:
            dl_due = ensure_utc(dl.due_date)
            is_overdue = now > dl_due
            diff = dl_due - now
            if is_overdue:
                remaining_str = f"Overdue by {abs(diff.days)}d {abs(diff.seconds)//3600}h"
                if not dl.allow_late:
                    can_submit_deadline = False
            else:
                remaining_str = f"{diff.days}d {diff.seconds//3600}h remaining"

        effective_can_submit = can_submit and can_submit_deadline

        pipeline.append({
            "chapter": ch,
            "chapter_name": ch.value,
            "display_name": CHAPTER_DISPLAY_NAMES[ch],
            "state": state,
            "can_submit": effective_can_submit,
            "can_submit_deadline": can_submit_deadline,
            "latest_submission": latest_sub,
            "latest_feedback": latest_feedback,
            "submissions": chapter_subs,
            "deadline": dl,
            "is_overdue": is_overdue,
            "remaining_str": remaining_str
        })

    progress_percentage = int((approved_count / len(CHAPTER_SEQUENCE)) * 100)

    return templates.TemplateResponse(
        request=request,
        name="submissions/index.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "student": student,
            "assignment": assignment,
            "pipeline": pipeline,
            "approved_count": approved_count,
            "progress_percentage": progress_percentage,
            "error": error,
            "active_nav": "submissions"
        },
        status_code=status_code
    )


# ============================================================================
# 1. STUDENT PIPELINE & SUBMISSIONS VIEW
# ============================================================================
@router.get("", response_class=HTMLResponse)
def view_student_pipeline(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != RoleEnum.STUDENT:
        if current_user.role == RoleEnum.SUPERVISOR:
            return RedirectResponse(url="/submissions/reviews", status_code=status.HTTP_303_SEE_OTHER)
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    return _render_pipeline_response(request, current_user, db)


# ============================================================================
# 2. GITHUB REPOSITORY URL LINKING
# ============================================================================
@router.post("/github-url", response_class=HTMLResponse)
def update_github_url(
    request: Request,
    github_url: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    student = current_user.student_profile
    assignment = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.student_id == student.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=400, detail="No active topic assignment found.")

    if assignment.github_url_locked:
        raise HTTPException(
            status_code=400,
            detail="GitHub repository URL is locked after Final Report approval and cannot be modified."
        )

    clean_url = github_url.strip()
    if not validate_github_url(clean_url):
        raise HTTPException(
            status_code=400,
            detail="Invalid GitHub repository URL. Must strictly match format: https://github.com/username/repository"
        )

    assignment.github_url = clean_url
    db.commit()

    return RedirectResponse(url="/submissions", status_code=status.HTTP_303_SEE_OTHER)


# ============================================================================
# 3. CHAPTER FILE SUBMISSION (UPLOAD)
# ============================================================================
@router.post("/{chapter}/upload", response_class=HTMLResponse)
def upload_chapter_submission(
    request: Request,
    chapter: str,
    file: UploadFile = File(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(require_role([RoleEnum.STUDENT])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    student = current_user.student_profile
    assignment = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.student_id == student.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=400, detail="No active topic assignment found.")

    try:
        ch_enum = ChapterEnum(chapter.strip())
    except ValueError:
        return _render_pipeline_response(request, current_user, db, error=f"Invalid chapter '{chapter}'.", status_code=400)

    # Read and validate file format and magic bytes first
    try:
        content = file.file.read()
        _validate_uploaded_file(file, content)
    except HTTPException as e:
        return _render_pipeline_response(request, current_user, db, error=e.detail, status_code=400)

    # Sequence Check: chapters open strictly in order
    idx = CHAPTER_SEQUENCE.index(ch_enum)
    if idx > 0:
        prev_ch = CHAPTER_SEQUENCE[idx - 1]
        prev_sub = (
            db.query(Submission)
            .filter(Submission.assignment_id == assignment.id, Submission.chapter == prev_ch)
            .order_by(Submission.version.desc())
            .first()
        )
        prev_feedback = prev_sub.feedback[-1] if (prev_sub and prev_sub.feedback) else None
        if not prev_feedback or prev_feedback.status != FeedbackStatusEnum.APPROVED:
            return _render_pipeline_response(
                request, current_user, db,
                error=f"Submission blocked: You must have an approved submission for {CHAPTER_DISPLAY_NAMES[prev_ch]} before submitting {CHAPTER_DISPLAY_NAMES[ch_enum]}.",
                status_code=400
            )

    # Current chapter review state check
    existing_subs = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment.id, Submission.chapter == ch_enum)
        .order_by(Submission.version.desc())
        .all()
    )
    if existing_subs:
        latest = existing_subs[0]
        latest_fb = latest.feedback[-1] if latest.feedback else None
        if latest_fb and latest_fb.status == FeedbackStatusEnum.APPROVED:
            return _render_pipeline_response(request, current_user, db, error="This chapter has already been approved.", status_code=400)
        if not latest_fb:
            return _render_pipeline_response(
                request, current_user, db,
                error="Your previous submission for this chapter is currently awaiting supervisor review. Resubmission is permitted only after feedback requesting revision.",
                status_code=400
            )

    # Deadline validation
    dl = db.query(Deadline).filter(Deadline.session_id == assignment.session_id, Deadline.chapter == ch_enum).first()
    now = utc_now()
    is_late = False
    if dl:
        dl_due = ensure_utc(dl.due_date)
        if now > dl_due:
            if not dl.allow_late:
                return _render_pipeline_response(
                    request, current_user, db,
                    error=f"The deadline for {CHAPTER_DISPLAY_NAMES[ch_enum]} passed on {dl.due_date.strftime('%Y-%m-%d %H:%M')} and late submissions are not allowed.",
                    status_code=400
                )
            else:
                is_late = True

    # Save to storage outside web root
    ext = Path(file.filename or "").suffix.lower()
    saved_filename = f"{uuid.uuid4().hex}{ext}"
    dest_path = STORAGE_DIR / saved_filename
    dest_path.write_bytes(content)

    next_version = len(existing_subs) + 1
    new_sub = Submission(
        assignment_id=assignment.id,
        chapter=ch_enum,
        version=next_version,
        file_path=str(Path("storage/submissions") / saved_filename).replace("\\", "/"),
        original_filename=Path(file.filename).name,
        file_size=len(content),
        submitted_at=now,
        is_late=is_late
    )
    db.add(new_sub)
    db.flush()

    # Notify supervisor
    create_notification(
        db=db,
        user_id=assignment.supervisor.user_id,
        title=f"New Submission: {CHAPTER_DISPLAY_NAMES[ch_enum]} (v{next_version})",
        message=f"Student {student.full_name} submitted {CHAPTER_DISPLAY_NAMES[ch_enum]} (v{next_version}) for project '{assignment.topic.title}'.",
        link=f"/submissions/{new_sub.id}/review"
    )

    db.commit()
    return RedirectResponse(url="/submissions", status_code=status.HTTP_303_SEE_OTHER)


# ============================================================================
# 4. AUTHENTICATED SUBMISSION FILE DOWNLOAD
# ============================================================================
@router.get("/{submission_id}/download")
def download_submission_file(
    request: Request,
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found.")

    assignment = sub.assignment
    if not assignment:
        raise HTTPException(status_code=404, detail="Topic assignment not found.")

    # Authorization Check
    # Allowed: Assigned Student, Assigned Supervisor, Coordinator/Admin
    is_assigned_student = (
        current_user.role == RoleEnum.STUDENT and
        current_user.student_profile and
        assignment.student_id == current_user.student_profile.id
    )
    is_assigned_supervisor = (
        current_user.role == RoleEnum.SUPERVISOR and
        current_user.supervisor_profile and
        assignment.supervisor_id == current_user.supervisor_profile.id
    )
    is_coordinator = current_user.role == RoleEnum.ADMIN

    if not (is_assigned_student or is_assigned_supervisor or is_coordinator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to download this project submission."
        )

    file_name = Path(sub.file_path).name
    actual_path = STORAGE_DIR / file_name
    if not actual_path.exists():
        raise HTTPException(status_code=404, detail="Stored submission file is missing from filesystem.")

    return FileResponse(
        path=str(actual_path),
        filename=sub.original_filename,
        media_type="application/octet-stream"
    )


# ============================================================================
# 5. SUPERVISOR REVIEW ROUTES
# ============================================================================
@router.get("/reviews", response_class=HTMLResponse)
def list_supervisor_reviews(
    request: Request,
    current_user: User = Depends(require_role([RoleEnum.SUPERVISOR])),
    db: Session = Depends(get_db)
):
    supervisor = current_user.supervisor_profile
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor profile not found.")

    # Fetch active student assignments for this supervisor
    assignments = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.supervisor_id == supervisor.id, TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
        .all()
    )

    review_data = []
    for a in assignments:
        # Chapter progress
        subs = db.query(Submission).filter(Submission.assignment_id == a.id).order_by(Submission.version.asc()).all()
        subs_by_ch = {}
        for s in subs:
            subs_by_ch.setdefault(s.chapter, []).append(s)

        ch_statuses = []
        pending_review_subs = []
        for ch in CHAPTER_SEQUENCE:
            chapter_list = subs_by_ch.get(ch, [])
            latest_s = chapter_list[-1] if chapter_list else None
            latest_f = latest_s.feedback[-1] if (latest_s and latest_s.feedback) else None
            
            status_text = "Not Submitted"
            if latest_f:
                status_text = latest_f.status.value
            elif latest_s:
                status_text = "Pending Review"
                pending_review_subs.append(latest_s)

            ch_statuses.append({
                "chapter": ch,
                "display_name": CHAPTER_DISPLAY_NAMES[ch],
                "status": status_text,
                "latest_sub": latest_s
            })

        review_data.append({
            "assignment": a,
            "student": a.student,
            "topic": a.topic,
            "github_url": a.github_url,
            "github_url_locked": a.github_url_locked,
            "chapters": ch_statuses,
            "pending_subs": pending_review_subs
        })

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="submissions/reviews.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "supervisor": supervisor,
            "review_data": review_data,
            "active_nav": "reviews"
        }
    )


@router.get("/{submission_id}/review", response_class=HTMLResponse)
def review_submission_detail(
    request: Request,
    submission_id: int,
    current_user: User = Depends(require_role([RoleEnum.SUPERVISOR])),
    db: Session = Depends(get_db)
):
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found.")

    assignment = sub.assignment
    supervisor = current_user.supervisor_profile

    # Server-side authorization check: ID tampering gives 403
    if not supervisor or assignment.supervisor_id != supervisor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not the assigned supervisor for this student."
        )

    # Fetch full version history for this chapter
    version_history = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment.id, Submission.chapter == sub.chapter)
        .order_by(Submission.version.asc())
        .all()
    )

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="submissions/review.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "submission": sub,
            "assignment": assignment,
            "chapter_display": CHAPTER_DISPLAY_NAMES[sub.chapter],
            "version_history": version_history,
            "active_nav": "reviews"
        }
    )


@router.post("/{submission_id}/feedback", response_class=HTMLResponse)
def submit_supervisor_feedback(
    request: Request,
    submission_id: int,
    status_choice: str = Form(..., alias="status"),
    comments: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(require_role([RoleEnum.SUPERVISOR])),
    db: Session = Depends(get_db)
):
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    clean_comments = comments.strip()
    if not clean_comments:
        raise HTTPException(status_code=400, detail="Feedback comments cannot be empty.")

    try:
        fb_status = FeedbackStatusEnum(status_choice.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid feedback status '{status_choice}'.")

    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found.")

    assignment = sub.assignment
    supervisor = current_user.supervisor_profile

    # Server-side check: supervisor can only review their own students
    if not supervisor or assignment.supervisor_id != supervisor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not the assigned supervisor for this student."
        )

    # Save Feedback
    fb = Feedback(
        submission_id=sub.id,
        supervisor_id=supervisor.id,
        status=fb_status,
        comments=clean_comments,
        created_at=utc_now()
    )
    db.add(fb)

    # If Final Report is approved, lock the GitHub URL
    if fb_status == FeedbackStatusEnum.APPROVED and sub.chapter == ChapterEnum.FINAL_REPORT:
        assignment.github_url_locked = True
        assignment.completed_at = utc_now()

    # Notify student
    create_notification(
        db=db,
        user_id=assignment.student.user_id,
        title=f"{CHAPTER_DISPLAY_NAMES[sub.chapter]} Feedback: {fb_status.value}",
        message=f"Supervisor {supervisor.full_name} marked your {CHAPTER_DISPLAY_NAMES[sub.chapter]} (v{sub.version}) submission as {fb_status.value}. Comments: {clean_comments}",
        link="/submissions"
    )

    db.commit()
    return RedirectResponse(url="/submissions/reviews", status_code=status.HTTP_303_SEE_OTHER)
