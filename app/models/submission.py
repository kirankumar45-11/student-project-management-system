import enum
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.core.datetime_util import utc_now

class ChapterEnum(str, enum.Enum):
    SYNOPSIS = "SYNOPSIS"
    SRS_DESIGN = "SRS_DESIGN"
    IMPLEMENTATION = "IMPLEMENTATION"
    FINAL_REPORT = "FINAL_REPORT"

CHAPTER_DISPLAY_NAMES = {
    ChapterEnum.SYNOPSIS: "Synopsis",
    ChapterEnum.SRS_DESIGN: "SRS and Design",
    ChapterEnum.IMPLEMENTATION: "Implementation",
    ChapterEnum.FINAL_REPORT: "Final Report"
}

class FeedbackStatusEnum(str, enum.Enum):
    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"

class Deadline(Base):
    __tablename__ = "deadlines"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("academic_sessions.id", ondelete="CASCADE"), nullable=False)
    chapter = Column(Enum(ChapterEnum), nullable=False)
    title = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(DateTime, nullable=False)
    allow_late = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    session = relationship("AcademicSession", back_populates="deadlines")

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("topic_assignments.id", ondelete="CASCADE"), nullable=False)
    chapter = Column(Enum(ChapterEnum), nullable=False)
    version = Column(Integer, default=1, nullable=False)
    file_path = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    submitted_at = Column(DateTime, default=utc_now)
    is_late = Column(Boolean, default=False, nullable=False)

    assignment = relationship("TopicAssignment", back_populates="submissions")
    feedback = relationship("Feedback", back_populates="submission", cascade="all, delete-orphan")

class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("supervisors.id", ondelete="RESTRICT"), nullable=False)
    status = Column(Enum(FeedbackStatusEnum), nullable=False)
    comments = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    submission = relationship("Submission", back_populates="feedback")
    supervisor = relationship("Supervisor", back_populates="feedback_entries")
