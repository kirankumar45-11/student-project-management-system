import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db, engine

logger = logging.getLogger("spms.health")

router = APIRouter(tags=["Health"])

@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Health check route verifying pooled MySQL 8.0 connection and returning database version.
    """
    try:
        version = db.execute(text("SELECT VERSION()")).scalar()
        current_db = db.execute(text("SELECT DATABASE()")).scalar()
        current_user = db.execute(text("SELECT CURRENT_USER()")).scalar()

        pool = engine.pool
        return {
            "status": "healthy",
            "database": "MySQL",
            "version": str(version),
            "database_name": str(current_db),
            "connected_user": str(current_user),
            "pool": {
                "size": pool.size(),
                "checkedin": pool.checkedin(),
                "checkedout": pool.checkedout(),
                "overflow": pool.overflow()
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Database connection error: {str(e)}"
        )
