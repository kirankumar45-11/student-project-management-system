from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.supervisor import Supervisor
from app.models.topic import TopicAssignment, AssignmentStatusEnum

def verify_and_lock_supervisor_slots(db: Session, supervisor_id: int) -> Supervisor:
    """
    Acquires an exclusive row lock on the supervisor row (SELECT ... FOR UPDATE)
    and verifies active assignments are strictly less than max_slots.
    Raises HTTPException(400) if quota is full.
    """
    supervisor = (
        db.query(Supervisor)
        .filter(Supervisor.id == supervisor_id)
        .with_for_update()
        .first()
    )
    if not supervisor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supervisor with ID {supervisor_id} not found."
        )

    active_count = (
        db.query(TopicAssignment)
        .filter(
            TopicAssignment.supervisor_id == supervisor_id,
            TopicAssignment.status == AssignmentStatusEnum.ACTIVE
        )
        .count()
    )

    if active_count >= supervisor.max_slots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Supervisor '{supervisor.full_name}' has reached their maximum quota ({active_count}/{supervisor.max_slots} slots full)."
        )

    return supervisor
