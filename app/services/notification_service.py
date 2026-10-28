from typing import Optional
from sqlalchemy.orm import Session
from app.models.guideline import Notification

def create_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    link: Optional[str] = None
) -> Notification:
    """Helper to store a persistent notification row in the database."""
    notif = Notification(
        user_id=user_id,
        title=title[:128],
        message=message,
        link=link[:255] if link else None
    )
    db.add(notif)
    return notif
