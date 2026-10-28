import enum
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.core.datetime_util import utc_now

class RoleEnum(str, enum.Enum):
    ADMIN = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    STUDENT = "STUDENT"

class AccountStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    code = Column(String(16), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    supervisors = relationship("Supervisor", back_populates="department")
    students = relationship("Student", back_populates="department")
    topics = relationship("Topic", back_populates="department")
    forum_threads = relationship("ForumThread", back_populates="department")

class AcademicSession(Base):
    __tablename__ = "academic_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(32), unique=True, nullable=False)  # e.g., "2025-2026"
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    students = relationship("Student", back_populates="session")
    topics = relationship("Topic", back_populates="session")
    deadlines = relationship("Deadline", back_populates="session")
    topic_assignments = relationship("TopicAssignment", back_populates="session")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(RoleEnum), nullable=False, index=True)
    status = Column(Enum(AccountStatusEnum), default=AccountStatusEnum.PENDING, nullable=False, index=True)
    remarks = Column(Text, nullable=True)
    must_change_password = Column(Boolean, default=False, nullable=False)
    session_version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    student_profile = relationship("Student", back_populates="user", uselist=False, cascade="all, delete-orphan")
    supervisor_profile = relationship("Supervisor", back_populates="user", uselist=False, cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
