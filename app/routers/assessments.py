import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, RoleEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import Topic, TopicAssignment, AssignmentStatusEnum, TopicStatusEnum
from app.models.submission import Submission, ChapterEnum, Feedback, FeedbackStatusEnum
from app.models.assessment import Assessment
from app.core.dependencies import get_current_user
from app.core.security import get_or_create_csrf_token, validate_csrf_token
from app.core.datetime_util import utc_now
from app.services.notification_service import create_notification

logger = logging.getLogger("spms.assessments")
router = APIRouter(tags=["Assessments"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _is_final_report_approved(db: Session, assignment_id: int) -> bool:
    """Checks whether the final report chapter has an approved feedback record."""
    final_sub = (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment_id,
            Submission.chapter == ChapterEnum.FINAL_REPORT
        )
        .order_by(Submission.version.desc())
        .first()
    )
    if not final_sub or not final_sub.feedback:
        return False
    return any(fb.status == FeedbackStatusEnum.APPROVED for fb in final_sub.feedback)


@router.get("/assessments", response_class=HTMLResponse)
def list_assessments(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Role-specific assessment landing page:
    - Supervisor: lists their assigned students and scoring status.
    - Admin/Coordinator: redirects to /coordinator/assessments.
    - Student: displays their own project grade card if assessed.
    """
    csrf_token = get_or_create_csrf_token(request)

    if current_user.role == RoleEnum.ADMIN:
        return RedirectResponse(url="/coordinator/assessments", status_code=status.HTTP_303_SEE_OTHER)

    if current_user.role == RoleEnum.STUDENT:
        student = db.query(Student).filter(Student.user_id == current_user.id).first()
        assignment = None
        if student:
            assignment = (
                db.query(TopicAssignment)
                .filter(
                    TopicAssignment.student_id == student.id,
                    TopicAssignment.status.in_([AssignmentStatusEnum.ACTIVE, AssignmentStatusEnum.COMPLETED])
                )
                .first()
            )
        return templates.TemplateResponse(
            request=request,
            name="assessments/student_view.html",
            context={
                "csrf_token": csrf_token,
                "current_user": current_user,
                "student": student,
                "assignment": assignment,
                "active_nav": "assessments"
            }
        )

    # Supervisor role
    supervisor = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor profile not found.")

    assignments = (
        db.query(TopicAssignment)
        .filter(TopicAssignment.supervisor_id == supervisor.id)
        .order_by(TopicAssignment.id.desc())
        .all()
    )

    assessment_items = []
    for assign in assignments:
        is_approved = _is_final_report_approved(db, assign.id)
        assessment_items.append({
            "assignment": assign,
            "is_final_approved": is_approved,
            "assessment": assign.assessment,
            "is_finalized": bool(assign.assessment and assign.assessment.finalized_at)
        })

    return templates.TemplateResponse(
        request=request,
        name="assessments/supervisor_list.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "supervisor": supervisor,
            "assessment_items": assessment_items,
            "active_nav": "assessments"
        }
    )


@router.get("/assessments/{assignment_id}/grade", response_class=HTMLResponse)
def get_grade_form(
    assignment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Supervisor form to grade presentation, report, and implementation."""
    if current_user.role != RoleEnum.SUPERVISOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only supervisors can score assessments.")

    supervisor = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor profile not found.")

    assignment = db.query(TopicAssignment).filter(TopicAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Project assignment not found.")

    # Non-owner supervisor check -> 403 Forbidden
    if assignment.supervisor_id != supervisor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not the assigned supervisor for this student."
        )

    # Final Report approval check -> 400 Bad Request
    if not _is_final_report_approved(db, assignment.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot score assessment: Final Report has not been approved."
        )

    # Immutability check
    if assignment.assessment and assignment.assessment.finalized_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assessment has already been finalized by coordinator and is immutable."
        )

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="assessments/grade_form.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "assignment": assignment,
            "assessment": assignment.assessment,
            "active_nav": "assessments"
        }
    )


@router.post("/assessments/{assignment_id}/grade")
def submit_grade(
    assignment_id: int,
    request: Request,
    presentation_score: float = Form(...),
    report_score: float = Form(...),
    implementation_score: float = Form(...),
    supervisor_remarks: Optional[str] = Form(None),
    csrf_token: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Submits or updates supervisor marks:
    - Presentation: 0 - 30
    - Report: 0 - 30
    - Implementation: 0 - 40
    - Total computed server-side: 0 - 100
    """
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    if current_user.role != RoleEnum.SUPERVISOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only supervisors can score assessments.")

    supervisor = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
    if not supervisor:
        raise HTTPException(status_code=404, detail="Supervisor profile not found.")

    assignment = db.query(TopicAssignment).filter(TopicAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Project assignment not found.")

    # Non-owner supervisor check -> 403 Forbidden
    if assignment.supervisor_id != supervisor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not the assigned supervisor for this student."
        )

    # Final Report approval check -> 400 Bad Request
    if not _is_final_report_approved(db, assignment.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot score assessment: Final Report has not been approved."
        )

    # Immutability check
    if assignment.assessment and assignment.assessment.finalized_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assessment has already been finalized by coordinator and is immutable."
        )

    # Score range validation
    if not (0.0 <= presentation_score <= 30.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Presentation score must be between 0.0 and 30.0."
        )
    if not (0.0 <= report_score <= 30.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Report score must be between 0.0 and 30.0."
        )
    if not (0.0 <= implementation_score <= 40.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Implementation score must be between 0.0 and 40.0."
        )

    # Server-side total computation
    total_score = round(presentation_score + report_score + implementation_score, 2)
    clean_remarks = supervisor_remarks.strip() if supervisor_remarks else None

    assessment = assignment.assessment
    if assessment:
        assessment.presentation_score = presentation_score
        assessment.report_score = report_score
        assessment.implementation_score = implementation_score
        assessment.total_score = total_score
        assessment.supervisor_remarks = clean_remarks
    else:
        assessment = Assessment(
            assignment_id=assignment.id,
            supervisor_id=supervisor.id,
            presentation_score=presentation_score,
            report_score=report_score,
            implementation_score=implementation_score,
            total_score=total_score,
            supervisor_remarks=clean_remarks
        )
        db.add(assessment)

    # Notify student
    create_notification(
        db=db,
        user_id=assignment.student.user_id,
        title="Project Assessment Marks Submitted",
        message=f"Supervisor {supervisor.full_name} submitted marks: Presentation {presentation_score}/30, Report {report_score}/30, Implementation {implementation_score}/40 (Total: {total_score}/100).",
        link="/dashboard"
    )

    # Notify coordinator(s)
    coordinators = db.query(User).filter(User.role == RoleEnum.ADMIN).all()
    for coord in coordinators:
        create_notification(
            db=db,
            user_id=coord.id,
            title="Project Ready for Finalization",
            message=f"Supervisor {supervisor.full_name} submitted marks for {assignment.student.full_name} ({assignment.topic.title}). Total: {total_score}/100.",
            link="/coordinator/assessments"
        )

    db.commit()
    return RedirectResponse(url="/assessments", status_code=status.HTTP_303_SEE_OTHER)


# =========================================================================
# COORDINATOR / ADMIN ASSESSMENT ROUTES
# =========================================================================

@router.get("/coordinator/assessments", response_class=HTMLResponse)
def list_coordinator_assessments(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Coordinator views all project assessments, scoring progress, and finalization status."""
    if current_user.role != RoleEnum.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Coordinator access required.")

    csrf_token = get_or_create_csrf_token(request)

    assignments = (
        db.query(TopicAssignment)
        .order_by(TopicAssignment.id.desc())
        .all()
    )

    assessment_records = []
    total_assessed = 0
    pending_finalization = 0
    finalized_count = 0

    for a in assignments:
        is_final_approved = _is_final_report_approved(db, a.id)
        assessment = a.assessment

        if assessment:
            total_assessed += 1
            if assessment.finalized_at:
                finalized_count += 1
            else:
                pending_finalization += 1

        assessment_records.append({
            "assignment": a,
            "is_final_approved": is_final_approved,
            "assessment": assessment,
            "is_finalized": bool(assessment and assessment.finalized_at)
        })

    return templates.TemplateResponse(
        request=request,
        name="assessments/coordinator_list.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "records": assessment_records,
            "total_assessed": total_assessed,
            "pending_finalization": pending_finalization,
            "finalized_count": finalized_count,
            "active_nav": "coordinator_assessments"
        }
    )


@router.get("/coordinator/assessments/{assessment_id}/finalize", response_class=HTMLResponse)
def get_finalize_form(
    assessment_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Coordinator review form for assigning the final grade."""
    if current_user.role != RoleEnum.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Coordinator access required.")

    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found.")

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(
        request=request,
        name="assessments/finalize_form.html",
        context={
            "csrf_token": csrf_token,
            "current_user": current_user,
            "assessment": assessment,
            "assignment": assessment.assignment,
            "active_nav": "coordinator_assessments"
        }
    )


@router.post("/coordinator/assessments/{assessment_id}/finalize")
def submit_finalization(
    assessment_id: int,
    request: Request,
    coordinator_final_grade: str = Form(...),
    csrf_token: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Finalizes the project assessment:
    - Immutable once finalized
    - Sets coordinator_final_grade, finalized_by_user_id, finalized_at
    - Transitions TopicAssignment to COMPLETED
    - Transitions Topic to ARCHIVED
    - Sends notifications to student and supervisor
    """
    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")

    if current_user.role != RoleEnum.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Coordinator access required.")

    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found.")

    # Immutability check -> 400 Bad Request
    if assessment.finalized_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assessment has already been finalized and cannot be modified."
        )

    clean_grade = coordinator_final_grade.strip().upper()
    if not clean_grade or len(clean_grade) > 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid final grade format.")

    now = utc_now()
    assessment.coordinator_final_grade = clean_grade
    assessment.finalized_by_user_id = current_user.id
    assessment.finalized_at = now

    assignment = assessment.assignment
    assignment.status = AssignmentStatusEnum.COMPLETED
    assignment.completed_at = now
    assignment.topic.status = TopicStatusEnum.ARCHIVED

    # Notify student
    create_notification(
        db=db,
        user_id=assignment.student.user_id,
        title="Project Grade Finalized & Completed",
        message=f"Congratulations! Your final project grade has been finalized as '{clean_grade}' by the Coordinator. Your project is now archived.",
        link="/dashboard"
    )

    # Notify supervisor
    create_notification(
        db=db,
        user_id=assignment.supervisor.user_id,
        title="Student Project Grade Finalized",
        message=f"Coordinator finalized grade '{clean_grade}' for student {assignment.student.full_name} on project '{assignment.topic.title}'.",
        link="/assessments"
    )

    db.commit()
    return RedirectResponse(url="/coordinator/assessments", status_code=status.HTTP_303_SEE_OTHER)
