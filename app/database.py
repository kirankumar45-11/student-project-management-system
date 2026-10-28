import logging
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from app.config import settings

logger = logging.getLogger("spms.database")

# Pooled runtime engine (spms_app)
engine = create_engine(
    settings.sync_database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Migration engine (spms_migrator)
migration_engine = create_engine(
    settings.migration_database_url,
    pool_pre_ping=True,
    echo=False
)

Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session per request.
    Commits on successful completion, rolls back on exception, and guarantees closure.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def check_db_connection() -> dict:
    """Verifies MySQL connection and returns engine pool details."""
    with engine.connect() as conn:
        version = conn.execute(text("SELECT VERSION()")).scalar()
        db_name = conn.execute(text("SELECT DATABASE()")).scalar()
        current_user = conn.execute(text("SELECT CURRENT_USER()")).scalar()
        
    pool = engine.pool
    return {
        "status": "healthy",
        "database": "MySQL",
        "version": str(version),
        "database_name": str(db_name),
        "connected_user": str(current_user),
        "pool": {
            "size": pool.size(),
            "checkedin": pool.checkedin(),
            "checkedout": pool.checkedout(),
            "overflow": pool.overflow()
        }
    }
