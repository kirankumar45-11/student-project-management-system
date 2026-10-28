from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.core.datetime_util import utc_now

class Supervisor(Base):
    __tablename__ = "supervisors"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    full_name = Column(String(128), nullable=False)
    phone = Column(String(20), nullable=True)
    designation = Column(String(64), default="Assistant Professor", nullable=False)
    max_slots = Column(Integer, default=4, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", back_populates="supervisor_profile")
    department = relationship("Department", back_populates="supervisors")
    assignments = relationship("TopicAssignment", back_populates="supervisor")
    feedback_entries = relationship("Feedback", back_populates="supervisor")
    assessments = relationship("Assessment", back_populates="supervisor")
