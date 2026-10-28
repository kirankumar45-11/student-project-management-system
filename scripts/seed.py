"""
Database seed script for SPMS.
Creates the initial Coordinator/Admin account using the configured password in .env
or a securely generated random password.
Hashes the password with bcrypt, sets must_change_password=True,
and reports that the account was created successfully without exposing credentials in logs.
"""
import os
import sys
import secrets
import string
import bcrypt
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.user import User, RoleEnum, AccountStatusEnum

def generate_secure_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*" for c in pwd)):
            return pwd

def seed_admin():
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
        if admin_user:
            print(f"[OK] Admin account already provisioned: {admin_user.username} ({admin_user.email})")
            return

        initial_password = os.getenv("ADMIN_INITIAL_PASSWORD")
        if not initial_password:
            initial_password = generate_secure_password()
            # Save to secure local file that is gitignored so user can read it privately
            secret_file = Path(__file__).resolve().parent.parent / ".admin_initial_secret"
            secret_file.write_text(initial_password.strip(), encoding="utf-8")
            print("[INFO] Temporary initial password saved to local .admin_initial_secret (gitignored).")

        hashed = bcrypt.hashpw(initial_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

        new_admin = User(
            username="admin",
            email="coordinator@spms.local",
            password_hash=hashed,
            role=RoleEnum.ADMIN,
            status=AccountStatusEnum.APPROVED,
            must_change_password=True,
            session_version=1,
            remarks="Initial System Administrator / Coordinator"
        )
        db.add(new_admin)
        db.commit()

        print("[OK] SPMS Initial Coordinator account successfully seeded.")
        print("     Username: admin | Email: coordinator@spms.local | Status: APPROVED | must_change_password: True")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to seed admin account: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_admin()
