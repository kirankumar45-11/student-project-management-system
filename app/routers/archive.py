import logging
from math import ceil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, RoleEnum, AccountStatusEnum, Department, AcademicSession
from app.models.topic import Topic, TopicAssignment, AssignmentStatusEnum, TopicStatusEnum
from app.models.submission import Submission, ChapterEnum, Feedback, FeedbackStatusEnum
from app.core.dependencies import get_current_user
from app.core.security import get_or_create_csrf_token

logger = logging.getLogger("spms.archive")
router = APIRouter(tags=["Project Archive"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/archive", response_class=HTMLResponse)
def view_project_archive(
    request: Request,
    q: Optional[str] = Query(None, description="Keyword search"),
    department_id: Optional[str] = Query(None, description="Department filter"),
    session_id: Optional[str] = Query(None, description="Academic Session / Year filter"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(9, ge=1, le=50, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Searchable, filterable project archive:
    - Search by keyword in title, description, domain
    - Filter by Academic Session (Year) and Department
    - Privacy Boundary: Under no circumstances does this view expose student personal private data
      (NO USN, NO email, NO phone number, NO student password/hash).
    - Report download button adheres to strict authentication & status rules.
    """
    csrf_token = get_or_create_csrf_token(request)

    # Safe parsing of query filter IDs to prevent 422 on empty string ""
    dept_id_int: Optional[int] = None
    if department_id and department_id.strip():
        try:
            dept_id_int = int(department_id.strip())
        except ValueError:
            dept_id_int = None

    sess_id_int: Optional[int] = None
    if session_id and session_id.strip():
        try:
            sess_id_int = int(session_id.strip())
        except ValueError:
            sess_id_int = None

    # Base query for officially ARCHIVED projects
    query = db.query(Topic).filter(Topic.status == TopicStatusEnum.ARCHIVED)

    # Apply Filters
    if dept_id_int:
        query = query.filter(Topic.department_id == dept_id_int)
    if sess_id_int:
        query = query.filter(Topic.session_id == sess_id_int)
    if q and q.strip():
        tokens = [t.strip() for t in q.strip().split() if t.strip()]
        for token in tokens:
            term = f"%{token}%"
            query = query.filter(
                or_(
                    Topic.title.ilike(term),
                    Topic.description.ilike(term),
                    Topic.domain.ilike(term)
                )
            )

    total_count = query.count()
    total_pages = max(1, ceil(total_count / per_page))
    page = min(page, total_pages)
    offset = (page - 1) * per_page

    archived_topics = (
        query
        .order_by(Topic.id.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    project_cards = []
    for topic in archived_topics:
        # Find completed assignment
        completed_assignment = (
            db.query(TopicAssignment)
            .filter(
                TopicAssignment.topic_id == topic.id,
                TopicAssignment.status == AssignmentStatusEnum.COMPLETED
            )
            .order_by(TopicAssignment.id.desc())
            .first()
        )

        supervisor_name = completed_assignment.supervisor.full_name if completed_assignment and completed_assignment.supervisor else "Faculty Supervisor"
        github_url = completed_assignment.github_url if completed_assignment else None
        final_grade = completed_assignment.assessment.coordinator_final_grade if (completed_assignment and completed_assignment.assessment) else "Completed"
        completed_at = completed_assignment.completed_at if completed_assignment else topic.updated_at

        # Check if final report file is available
        has_final_report = False
        if completed_assignment:
            final_sub = (
                db.query(Submission)
                .filter(
                    Submission.assignment_id == completed_assignment.id,
                    Submission.chapter == ChapterEnum.FINAL_REPORT
                )
                .order_by(Submission.version.desc())
                .first()
            )
            if final_sub and final_sub.feedback:
                has_final_report = any(fb.status == FeedbackStatusEnum.APPROVED for fb in final_sub.feedback)

        # STRICT PRIVACY: Student personal info is completely excluded
        project_cards.append({
            "topic_id": topic.id,
            "title": topic.title,
            "description": topic.description,
            "domain": topic.domain,
            "department_code": topic.department.code if topic.department else "",
            "department_name": topic.department.name if topic.department else "",
            "session_name": topic.session.name if topic.session else "",
            "supervisor_name": supervisor_name,
            "github_url": github_url,
            "final_grade": final_grade,
            "completed_at": completed_at,
            "has_final_report": has_final_report
        })

    departments = db.query(Department).order_by(Department.code.asc()).all()
    sessions = db.query(AcademicSession).order_by(AcademicSession.name.desc()).all()

    # Clear Download Rules stated for users
    download_rules = [
        "Authentication Required: Only logged-in, authenticated users can download archive reports.",
        "Active Status Required: User account must be in APPROVED status.",
        "Authorized Roles: Students, Supervisors, and Coordinators are eligible to view archived final reports for academic reference.",
        "Project State: Only officially COMPLETED and ARCHIVED projects with verified, approved reports may be retrieved."
    ]

    return templates.TemplateResponse(
        request=request,
        name="archive/index.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "project_cards": project_cards,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "q": q or "",
            "selected_department_id": dept_id_int,
            "selected_session_id": sess_id_int,
            "departments": departments,
            "sessions": sessions,
            "download_rules": download_rules,
            "active_nav": "archive"
        }
    )


@router.get("/archive/{topic_id}", response_class=HTMLResponse)
def view_archive_detail(
    topic_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Dedicated detail view for an archived project:
    - Displays full title, abstract/description, department, session, supervisor, grade, locked GitHub URL.
    - Strictly preserves student privacy (no student USN, phone, email, or name exposed).
    """
    topic = (
        db.query(Topic)
        .filter(Topic.id == topic_id, Topic.status == TopicStatusEnum.ARCHIVED)
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="Archived project topic not found.")

    completed_assignment = (
        db.query(TopicAssignment)
        .filter(
            TopicAssignment.topic_id == topic.id,
            TopicAssignment.status == AssignmentStatusEnum.COMPLETED
        )
        .order_by(TopicAssignment.id.desc())
        .first()
    )

    supervisor_name = completed_assignment.supervisor.full_name if (completed_assignment and completed_assignment.supervisor) else "Faculty Supervisor"
    github_url = completed_assignment.github_url if completed_assignment else None
    final_grade = completed_assignment.assessment.coordinator_final_grade if (completed_assignment and completed_assignment.assessment) else "Completed"
    completed_at = completed_assignment.completed_at if completed_assignment else topic.updated_at

    has_final_report = False
    if completed_assignment:
        final_sub = (
            db.query(Submission)
            .filter(
                Submission.assignment_id == completed_assignment.id,
                Submission.chapter == ChapterEnum.FINAL_REPORT
            )
            .order_by(Submission.version.desc())
            .first()
        )
        if final_sub and final_sub.feedback:
            has_final_report = any(fb.status == FeedbackStatusEnum.APPROVED for fb in final_sub.feedback)

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="archive/detail.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "topic": topic,
            "supervisor_name": supervisor_name,
            "github_url": github_url,
            "final_grade": final_grade,
            "completed_at": completed_at,
            "has_final_report": has_final_report,
            "active_nav": "archive"
        }
    )


@router.get("/archive/{topic_id}/download")
def download_archived_report(
    topic_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Authenticated download of an archived project's approved final report:
    - Rule 1: Authenticated user required
    - Rule 2: User must have an APPROVED account
    - Rule 3: User must be STUDENT, SUPERVISOR, or ADMIN
    - Rule 4: Topic must be in ARCHIVED status and have an approved Final Report
    """
    if current_user.status != AccountStatusEnum.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only approved accounts may download archived reports."
        )

    if current_user.role not in [RoleEnum.STUDENT, RoleEnum.SUPERVISOR, RoleEnum.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Your role is not authorized to download archived reports."
        )

    topic = (
        db.query(Topic)
        .filter(Topic.id == topic_id, Topic.status == TopicStatusEnum.ARCHIVED)
        .first()
    )
    if not topic:
        raise HTTPException(status_code=404, detail="Archived project topic not found.")

    assignment = (
        db.query(TopicAssignment)
        .filter(
            TopicAssignment.topic_id == topic.id,
            TopicAssignment.status == AssignmentStatusEnum.COMPLETED
        )
        .order_by(TopicAssignment.id.desc())
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="No completed assignment found for this project.")

    final_sub = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment.id,
            Submission.chapter == ChapterEnum.FINAL_REPORT
        )
        .order_by(Submission.version.desc())
        .first()
    )
    if not final_sub or not final_sub.feedback:
        raise HTTPException(status_code=404, detail="No final report submission found for this project.")

    is_approved = any(fb.status == FeedbackStatusEnum.APPROVED for fb in final_sub.feedback)
    if not is_approved:
        raise HTTPException(status_code=404, detail="The final report for this project was not officially approved.")

    file_path = Path(final_sub.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report document file is missing from server storage.")

    # Determine MIME type
    ext = file_path.suffix.lower()
    media_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=file_path,
        filename=final_sub.original_filename,
        media_type=media_type
    )
