import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, RoleEnum, AccountStatusEnum
from app.models.student import Student
from app.models.supervisor import Supervisor
from app.models.topic import Topic, TopicAssignment, AssignmentStatusEnum, TopicStatusEnum
from app.models.submission import Submission, ChapterEnum, Deadline, Feedback, FeedbackStatusEnum, CHAPTER_DISPLAY_NAMES
from app.models.assessment import Assessment
from app.models.guideline import Notification
from app.core.dependencies import get_current_user
from app.core.security import get_or_create_csrf_token
from app.core.datetime_util import utc_now, ensure_utc

logger = logging.getLogger("spms.dashboard")
router = APIRouter(tags=["Dashboard"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

CHAPTER_SEQUENCE = [
    ChapterEnum.SYNOPSIS,
    ChapterEnum.SRS_DESIGN,
    ChapterEnum.IMPLEMENTATION,
    ChapterEnum.FINAL_REPORT
]


@router.get("/", response_class=HTMLResponse)
def index_redirect():
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    csrf_token = get_or_create_csrf_token(request)
    now = utc_now()

    # =========================================================================
    # 1. STUDENT DASHBOARD
    # =========================================================================
    if current_user.role == RoleEnum.STUDENT:
        student = db.query(Student).filter(Student.user_id == current_user.id).first()
        assignment = None
        milestones = []
        deadlines_list = []
        assessment = None

        # Unread notifications
        unread_notifs_count = db.query(Notification).filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        ).count()

        if student:
            # Query active or completed assignment
            assignment = (
                db.query(TopicAssignment)
                .filter(
                    TopicAssignment.student_id == student.id,
                    TopicAssignment.status.in_([AssignmentStatusEnum.ACTIVE, AssignmentStatusEnum.COMPLETED])
                )
                .order_by(TopicAssignment.id.desc())
                .first()
            )

            if assignment:
                assessment = assignment.assessment

                # Fetch all submissions for milestone stepper
                submissions = (
                    db.query(Submission)
                    .filter(Submission.assignment_id == assignment.id)
                    .order_by(Submission.chapter.asc(), Submission.version.asc())
                    .all()
                )
                subs_by_chapter: Dict[ChapterEnum, List[Submission]] = {}
                for s in submissions:
                    subs_by_chapter.setdefault(s.chapter, []).append(s)

                prev_approved = True
                for ch in CHAPTER_SEQUENCE:
                    ch_subs = subs_by_chapter.get(ch, [])
                    latest_sub = ch_subs[-1] if ch_subs else None
                    latest_fb = latest_sub.feedback[-1] if (latest_sub and latest_sub.feedback) else None

                    is_app = latest_fb is not None and latest_fb.status == FeedbackStatusEnum.APPROVED
                    is_rev = latest_fb is not None and latest_fb.status == FeedbackStatusEnum.NEEDS_REVISION
                    is_review = latest_sub is not None and latest_fb is None

                    # If project is officially completed, all chapters are approved
                    if assignment.status == AssignmentStatusEnum.COMPLETED:
                        st = "APPROVED"
                    elif is_app:
                        st = "APPROVED"
                    elif not prev_approved:
                        st = "LOCKED"
                    elif is_review:
                        st = "UNDER_REVIEW"
                    elif is_rev:
                        st = "NEEDS_REVISION"
                    else:
                        st = "ACTIVE"

                    prev_approved = (st == "APPROVED")
                    milestones.append({
                        "chapter": ch.value,
                        "name": CHAPTER_DISPLAY_NAMES[ch],
                        "status": st
                    })

                # Deadlines for session
                deadlines = (
                    db.query(Deadline)
                    .filter(Deadline.session_id == assignment.session_id)
                    .order_by(Deadline.due_date.asc())
                    .all()
                )
                for dl in deadlines:
                    dl_due = ensure_utc(dl.due_date)
                    is_overdue = now > dl_due
                    diff = dl_due - now
                    if is_overdue:
                        countdown = f"Overdue by {abs(diff.days)}d {abs(diff.seconds)//3600}h"
                    else:
                        countdown = f"{diff.days}d {diff.seconds//3600}h remaining"

                    deadlines_list.append({
                        "chapter_name": CHAPTER_DISPLAY_NAMES.get(dl.chapter, dl.chapter.value),
                        "title": dl.title,
                        "due_date": dl.due_date,
                        "is_overdue": is_overdue,
                        "countdown": countdown,
                        "allow_late": dl.allow_late
                    })

        return templates.TemplateResponse(
            request=request,
            name="dashboard/student.html",
            context={
                "csrf_token": csrf_token,
                "current_user": current_user,
                "student": student,
                "assignment": assignment,
                "milestones": milestones,
                "deadlines": deadlines_list,
                "assessment": assessment,
                "unread_notifs_count": unread_notifs_count,
                "active_nav": "dashboard"
            }
        )

    # =========================================================================
    # 2. SUPERVISOR DASHBOARD
    # =========================================================================
    elif current_user.role == RoleEnum.SUPERVISOR:
        supervisor = db.query(Supervisor).filter(Supervisor.user_id == current_user.id).first()
        active_assignments = []
        pending_reviews = []
        pending_assessments_count = 0
        assigned_count = 0
        max_slots = 4
        slot_percentage = 0
        available_slots = 4
        assigned_data = []

        if supervisor:
            max_slots = supervisor.max_slots
            active_assignments = (
                db.query(TopicAssignment)
                .filter(
                    TopicAssignment.supervisor_id == supervisor.id,
                    TopicAssignment.status == AssignmentStatusEnum.ACTIVE
                )
                .order_by(TopicAssignment.id.desc())
                .all()
            )
            assigned_count = len(active_assignments)
            available_slots = max(0, max_slots - assigned_count)
            slot_percentage = min(100, int((assigned_count / max_slots) * 100)) if max_slots > 0 else 0

            # Gather student cards with milestones and pending actions
            for a in active_assignments:
                # Check for submissions needing review
                subs = (
                    db.query(Submission)
                    .filter(Submission.assignment_id == a.id)
                    .order_by(Submission.id.desc())
                    .all()
                )
                unreviewed = [s for s in subs if not s.feedback]
                for u in unreviewed:
                    pending_reviews.append({
                        "submission_id": u.id,
                        "student_name": a.student.full_name,
                        "usn": a.student.usn,
                        "chapter_name": CHAPTER_DISPLAY_NAMES[u.chapter],
                        "version": u.version,
                        "submitted_at": u.submitted_at
                    })

                # Check if Final Report is approved
                final_sub = (
                    db.query(Submission)
                    .filter(Submission.assignment_id == a.id, Submission.chapter == ChapterEnum.FINAL_REPORT)
                    .order_by(Submission.version.desc())
                    .first()
                )
                final_approved = False
                if final_sub and final_sub.feedback:
                    final_approved = any(fb.status == FeedbackStatusEnum.APPROVED for fb in final_sub.feedback)

                has_assessment = a.assessment is not None
                if final_approved and not has_assessment:
                    pending_assessments_count += 1

                assigned_data.append({
                    "assignment": a,
                    "final_approved": final_approved,
                    "has_assessment": has_assessment,
                    "assessment": a.assessment
                })

        return templates.TemplateResponse(
            request=request,
            name="dashboard/supervisor.html",
            context={
                "csrf_token": csrf_token,
                "current_user": current_user,
                "supervisor": supervisor,
                "assigned_students": assigned_data,
                "assigned_count": assigned_count,
                "max_slots": max_slots,
                "available_slots": available_slots,
                "slot_percentage": slot_percentage,
                "pending_reviews": pending_reviews,
                "pending_reviews_count": len(pending_reviews),
                "pending_assessments_count": pending_assessments_count,
                "active_nav": "dashboard"
            }
        )

    # =========================================================================
    # 3. COORDINATOR / ADMIN DASHBOARD
    # =========================================================================
    elif current_user.role == RoleEnum.ADMIN:
        pending_accounts = db.query(User).filter(User.status == AccountStatusEnum.PENDING).count()
        pending_topics = db.query(Topic).filter(Topic.status == TopicStatusEnum.PROPOSED).count()
        pending_assessments = (
            db.query(Assessment)
            .filter(Assessment.finalized_at == None)
            .count()
        )
        total_students = db.query(Student).count()
        supervisors_count = db.query(Supervisor).count()
        active_assignments = (
            db.query(TopicAssignment)
            .filter(TopicAssignment.status == AssignmentStatusEnum.ACTIVE)
            .all()
        )
        archived_projects_count = db.query(Topic).filter(Topic.status == TopicStatusEnum.ARCHIVED).count()

        # Identify Overdue Students
        overdue_students = []
        for a in active_assignments:
            subs = (
                db.query(Submission)
                .filter(Submission.assignment_id == a.id)
                .all()
            )
            approved_chapters = set()
            for s in subs:
                if s.feedback and any(fb.status == FeedbackStatusEnum.APPROVED for fb in s.feedback):
                    approved_chapters.add(s.chapter)

            current_ch = None
            for ch in CHAPTER_SEQUENCE:
                if ch not in approved_chapters:
                    current_ch = ch
                    break

            if current_ch:
                dl = (
                    db.query(Deadline)
                    .filter(Deadline.session_id == a.session_id, Deadline.chapter == current_ch)
                    .first()
                )
                if dl:
                    dl_due = ensure_utc(dl.due_date)
                    if now > dl_due:
                        diff = now - dl_due
                        overdue_students.append({
                            "student_name": a.student.full_name,
                            "usn": a.student.usn,
                            "department_code": a.student.department.code if a.student.department else "",
                            "topic_title": a.topic.title,
                            "supervisor_name": a.supervisor.full_name,
                            "chapter_name": CHAPTER_DISPLAY_NAMES[current_ch],
                            "due_date": dl.due_date,
                            "overdue_by": f"{diff.days}d {diff.seconds//3600}h",
                            "allow_late": dl.allow_late
                        })

        return templates.TemplateResponse(
            request=request,
            name="dashboard/coordinator.html",
            context={
                "csrf_token": csrf_token,
                "current_user": current_user,
                "pending_accounts_count": pending_accounts,
                "pending_topics_count": pending_topics,
                "pending_assessments_count": pending_assessments,
                "overdue_students_count": len(overdue_students),
                "overdue_students": overdue_students,
                "total_students_count": total_students,
                "supervisors_count": supervisors_count,
                "active_assignments_count": len(active_assignments),
                "archived_projects_count": archived_projects_count,
                "active_nav": "dashboard"
            }
        )
