import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    # MySQL Database Settings
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "spms_db"
    
    # Runtime Application User (Least Privilege)
    DB_USER: str = "spms_app"
    DB_PASSWORD: str = ""
    
    # Migration User (DDL / Provisioning)
    DB_MIGRATION_USER: str = "spms_migrator"
    DB_MIGRATION_PASSWORD: str = ""
    
    # Security & Environment
    ENVIRONMENT: str = "development"
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: str = "lax"
    SECRET_KEY: str = Field(default="spms-default-insecure-secret-key-change-in-production-1234567890")
    SESSION_MAX_AGE_SECONDS: int = 7200  # 2 hours
    
    # Storage
    UPLOAD_DIR: str = "storage"
    
    # Duplicate Detection
    DUPLICATE_THRESHOLD: float = 0.70
    
    # Optional seed override
    ADMIN_INITIAL_PASSWORD: str = ""
    
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    @property
    def sync_database_url(self) -> str:
        """Runtime connection string using PyMySQL driver."""
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    @property
    def migration_database_url(self) -> str:
        """Migration connection string using spms_migrator user."""
        return f"mysql+pymysql://{self.DB_MIGRATION_USER}:{self.DB_MIGRATION_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

settings = Settings()

# Ensure upload directory exists
upload_path = BASE_DIR / settings.UPLOAD_DIR
upload_path.mkdir(parents=True, exist_ok=True)
for sub in ["submissions", "guidelines", "avatars"]:
    (upload_path / sub).mkdir(parents=True, exist_ok=True)
