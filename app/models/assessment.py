from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.database import Base
from app.core.datetime_util import utc_now

class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("topic_assignments.id", ondelete="CASCADE"), unique=True, nullable=False)
    supervisor_id = Column(Integer, ForeignKey("supervisors.id", ondelete="RESTRICT"), nullable=False)
    presentation_score = Column(Numeric(5, 2), default=0.00, nullable=False)
    report_score = Column(Numeric(5, 2), default=0.00, nullable=False)
    implementation_score = Column(Numeric(5, 2), default=0.00, nullable=False)
    total_score = Column(Numeric(5, 2), default=0.00, nullable=False)
    supervisor_remarks = Column(Text, nullable=True)
    coordinator_final_grade = Column(String(8), nullable=True)
    finalized_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    assignment = relationship("TopicAssignment", back_populates="assessment")
    supervisor = relationship("Supervisor", back_populates="assessments")
    finalizer = relationship("User", foreign_keys=[finalized_by_user_id])
