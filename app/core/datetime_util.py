from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """Returns the current UTC datetime as a timezone-aware datetime object."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Ensures that a datetime is timezone-aware and set to UTC.
    If the datetime is naive (such as those retrieved from MySQL DATETIME columns),
    it is assigned timezone.utc without altering its numerical timestamp components.
    If the datetime is already timezone-aware, it is converted to UTC.
    Returns None if dt is None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
