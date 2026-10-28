import enum
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Enum, ForeignKey, 
    Boolean, Computed
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.core.datetime_util import utc_now

class TopicStatusEnum(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ASSIGNED = "ASSIGNED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"

class TopicProposedRoleEnum(str, enum.Enum):
    STUDENT = "STUDENT"
    SUPERVISOR = "SUPERVISOR"

class TopicRequestStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

class AssignmentStatusEnum(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"

class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    normalized_title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=False)
    domain = Column(String(64), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    session_id = Column(Integer, ForeignKey("academic_sessions.id", ondelete="RESTRICT"), nullable=False)
    proposed_by_role = Column(Enum(TopicProposedRoleEnum), nullable=False)
    proposed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum(TopicStatusEnum), default=TopicStatusEnum.PROPOSED, nullable=False, index=True)
    rejection_remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    department = relationship("Department", back_populates="topics")
    session = relationship("AcademicSession", back_populates="topics")
    proposer = relationship("User")
    requests = relationship("TopicRequest", back_populates="topic", cascade="all, delete-orphan")
    assignments = relationship("TopicAssignment", back_populates="topic")

class TopicRequest(Base):
    __tablename__ = "topic_requests"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    topic_id = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum(TopicRequestStatusEnum), default=TopicRequestStatusEnum.PENDING, nullable=False)
    student_remarks = Column(Text, nullable=True)
    coordinator_remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    topic = relationship("Topic", back_populates="requests")
    student = relationship("Student", back_populates="topic_requests")

class TopicAssignment(Base):
    __tablename__ = "topic_assignments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    topic_id = Column(Integer, ForeignKey("topics.id", ondelete="RESTRICT"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="RESTRICT"), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("supervisors.id", ondelete="RESTRICT"), nullable=False)
    session_id = Column(Integer, ForeignKey("academic_sessions.id", ondelete="RESTRICT"), nullable=False)
    github_url = Column(String(255), nullable=True)
    github_url_locked = Column(Boolean, default=False, nullable=False)
    status = Column(Enum(AssignmentStatusEnum), default=AssignmentStatusEnum.ACTIVE, nullable=False)
    assigned_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)

    # Generated columns for MySQL DB-level uniqueness constraint
    active_student_guard = Column(
        Integer, 
        Computed("IF(status = 'ACTIVE', student_id, NULL)", persisted=True),
        unique=True
    )
    active_topic_guard = Column(
        Integer,
        Computed("IF(status = 'ACTIVE', topic_id, NULL)", persisted=True),
        unique=True
    )

    topic = relationship("Topic", back_populates="assignments")
    student = relationship("Student", back_populates="assignments")
    supervisor = relationship("Supervisor", back_populates="assignments")
    session = relationship("AcademicSession", back_populates="topic_assignments")
    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")
    assessment = relationship("Assessment", back_populates="assignment", uselist=False, cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="assignment", cascade="all, delete-orphan")
