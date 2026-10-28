from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.core.datetime_util import utc_now

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    session_id = Column(Integer, ForeignKey("academic_sessions.id", ondelete="RESTRICT"), nullable=False)
    usn = Column(String(32), unique=True, nullable=False, index=True)
    full_name = Column(String(128), nullable=False)
    semester = Column(Integer, default=8, nullable=False)
    academic_year = Column(String(32), nullable=False)
    phone = Column(String(20), nullable=False)
    profile_pic = Column(String(255), nullable=True)
    github_url = Column(String(255), nullable=True)
    linkedin_url = Column(String(255), nullable=True)
    skills = Column(Text, nullable=True)
    show_contact_to_students = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", back_populates="student_profile")
    department = relationship("Department", back_populates="students")
    session = relationship("AcademicSession", back_populates="students")
    assignments = relationship("TopicAssignment", back_populates="student")
    topic_requests = relationship("TopicRequest", back_populates="student")
