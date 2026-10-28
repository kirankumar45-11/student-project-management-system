import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.database import SessionLocal, engine, Base
from app.config import settings
from app.core.rate_limiter import limiter

@pytest.fixture(scope="session", autouse=True)
def disable_rate_limiting_in_tests():
    limiter.enabled = False
    yield
    limiter.enabled = True

@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope="function")
def db_session():
    """Provides a transactional database session for unit tests."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
