# Student Project Management System (SPMS)

A robust, enterprise-grade, monolithic web application built for engineering departments to automate, govern, and evaluate final-year student capstone projects.

📄 **Workflow & Roles Documentation**: See [SPMS_Project_Flow_and_Roles_Guide.pdf](SPMS_Project_Flow_and_Roles_Guide.pdf) for a step-by-step role and state machine guide.

---

## 1. System Architecture & Tech Stack

SPMS is designed as a secure, full-stack monolithic architecture without separate frontend build pipelines:
- **Backend Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10+)
- **Templating Engine**: [Jinja2](https://palletsprojects.com/p/jinja/) with Bootstrap 5.3 & Bootstrap Icons
- **Database Engine**: [MySQL 8.0+](https://www.mysql.com/) with native virtual generated columns, transactions, and foreign key cascades
- **ORM & Driver**: [SQLAlchemy 2.0](https://www.sqlalchemy.org/) + [PyMySQL](https://github.com/PyMySQL/PyMySQL)
- **Security & Cryptography**: Direct Bcrypt (work factor 12), itsdangerous signed tokens, CSRF validation on all state-changing endpoints, Content-Security-Policy & security headers
- **Testing & E2E Verification**: [Pytest](https://pytest.org/) & [Playwright](https://playwright.dev/python/) with cross-viewport verification (360px mobile, 768px tablet, 1280px desktop) in light and dark modes

---

## 2. Prerequisites

- **Python**: Version 3.10, 3.11, 3.12, or 3.13
- **Database**: MySQL Server 8.0 or higher
- **Operating System**: Windows 10/11, macOS, or Linux (Ubuntu 22.04+ / Debian 12+)

---

## 3. Database Installation & User Provisioning

SPMS strictly adheres to the **Principle of Least Privilege**, utilizing two distinct MySQL database users:
1. `spms_migrator`: Used exclusively for schema provisioning and structural migrations (`CREATE`, `ALTER`, `DROP`, `REFERENCES`, `INDEX`).
2. `spms_app`: Runtime application user restricted to CRUD data operations (`SELECT`, `INSERT`, `UPDATE`, `DELETE`).

### Step A: Install MySQL 8.0

- **Windows**: Download and run the official [MySQL Community Installer](https://dev.mysql.com/downloads/installer/). Ensure MySQL Server 8.0 is running as a Windows Service (`MySQL80`).
- **Linux (Ubuntu / Debian)**:
  ```bash
  sudo apt update
  sudo apt install -y mysql-server
  sudo systemctl enable --now mysql
  ```

### Step B: Database & User Provisioning Script

Log into MySQL as `root`:
```bash
mysql -u root -p
```

Execute the following SQL commands (replace `<MIGRATION_PASSWORD>` and `<APP_PASSWORD>` with secure passwords):

```sql
-- 1. Create dedicated database with UTF8MB4 encoding
CREATE DATABASE IF NOT EXISTS spms_db 
  CHARACTER SET utf8mb4 
  COLLATE utf8mb4_unicode_ci;

-- 2. Create Migration User (Specific DDL and DML privileges)
CREATE USER IF NOT EXISTS 'spms_migrator'@'localhost' IDENTIFIED BY '<MIGRATION_PASSWORD>';
GRANT CREATE, ALTER, DROP, REFERENCES, INDEX, SELECT, INSERT, UPDATE, DELETE ON spms_db.* TO 'spms_migrator'@'localhost';

-- 3. Create Runtime Application User (Least Privilege CRUD only)
CREATE USER IF NOT EXISTS 'spms_app'@'localhost' IDENTIFIED BY '<APP_PASSWORD>';
GRANT SELECT, INSERT, UPDATE, DELETE ON spms_db.* TO 'spms_app'@'localhost';

-- 4. Apply privilege changes
FLUSH PRIVILEGES;
EXIT;
```

---

## 4. Local Environment Setup

### Step 1: Clone and Navigate to Repository
```bash
git clone https://github.com/kirankumar45-11/student-project-management-system.git
cd student-project-management-system
```

### Step 2: Create and Activate Virtual Environment

- **Windows (PowerShell)**:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```
- **Linux / macOS**:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### Step 3: Install Dependencies
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

### Step 4: Configure Environment Variables

Create `.env` by copying `.env.example`:
- **Windows**:
  ```powershell
  Copy-Item .env.example .env
  ```
- **Linux / macOS**:
  ```bash
  cp .env.example .env
  ```

Generate a secure 64-character hex secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Edit `.env` and fill in your database credentials and secret key:
```ini
DB_HOST=localhost
DB_PORT=3306
DB_NAME=spms_db
DB_USER=spms_app
DB_PASSWORD=<YOUR_MYSQL_APP_PASSWORD>

DB_MIGRATION_USER=spms_migrator
DB_MIGRATION_PASSWORD=<YOUR_MYSQL_MIGRATION_PASSWORD>

ENVIRONMENT=development
SECRET_KEY=<PASTE_GENERATED_64_CHAR_HEX_KEY>
SESSION_MAX_AGE_SECONDS=7200
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_SAMESITE=lax
LOGIN_RATE_LIMIT=10/minute

UPLOAD_DIR=storage
DUPLICATE_THRESHOLD=0.70
ADMIN_INITIAL_PASSWORD=
```

---

## 5. Database Migration and Seeding

### 1. Apply Schema Migrations
Applies [schema.sql](file:///c:/Users/ASUS/Desktop/student-project-management-system-python/schema.sql) with table definitions, foreign keys, and active-assignment uniqueness guards:
```bash
python scripts/migrate.py
```

### 2. Seed Initial Admin Account
Provisions the initial Coordinator administrator:
```bash
python scripts/seed.py
```
*(The generated initial password is saved to local `.admin_initial_secret`, which is gitignored to prevent log leaks).*

### 3. Seed Realistic Demo Dataset (Optional)
Populates departments (CSE, ISE), supervisors (Dr. Alan Turing, Dr. Grace Hopper), students, deadlines, and a completed archived project for instant demonstration:
```bash
python scripts/seed_demo.py
```
*(Demo account credentials are saved to `.demo_credentials` which is gitignored).*

### 4. Clean Reset (When Needed)
To cleanly purge leftover test data and re-apply schema from scratch:
```bash
python scripts/reset_db.py
```

> [!WARNING]
> **Data Loss Warning**: `scripts/reset_db.py` completely drops all 17 database tables, permanently erasing **all data including the coordinator admin account**. After executing a database reset, you must re-seed accounts:
> - For clean demonstration accounts: run `python scripts/seed_demo.py` (creates demo coordinator, supervisors, students, topics, and archive).
> - For a fresh production deployment: run `python scripts/seed.py` (provisions the single initial admin account).

---

## 6. Running the Development Server

Start the FastAPI application with Uvicorn and live auto-reload:
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- **Application URL**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Health Check Endpoint**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- **API Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) *(available only when `ENVIRONMENT=development`)*

To stop the server, press `Ctrl + C`.

---

## 7. Running the Automated Test Suite

### Full Pytest Suite (Unit, Integration, Concurrency & Security)
Execute the complete test suite against real MySQL 8.0:
```bash
python -m pytest -v tests/
```

### Responsive Multi-Viewport Playwright E2E Suite
Run end-to-end browser tests capturing Mobile (360px), Tablet (768px), and Desktop (1280px) in light and dark modes:
```bash
python scripts/capture_phase6_viewports.py
```

### Security & Password Audit
Verify that no passwords, tokens, or hardcoded secrets appear in source files or logs:
```bash
python scripts/audit_secrets.py
```

---

## 8. Production Deployment

In production, set `ENVIRONMENT=production`, `SESSION_COOKIE_SECURE=true`, and configure an SSL termination reverse proxy (Nginx or Caddy) in front of the application.

### Linux (Gunicorn with Uvicorn Workers)
Install Gunicorn inside virtualenv:
```bash
pip install gunicorn
```

Run multi-worker production server:
```bash
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --access-logfile - \
  --error-logfile -
```

### Windows (Uvicorn Production Service)
FastAPI is an asynchronous ASGI framework. Run multi-worker Uvicorn directly:
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 9. Key Security Features

1. **CSRF Protection**: 100% of state-changing `POST` routes enforce cryptographic CSRF token verification.
2. **Role-Based Access Control**: Strict multi-tier authorization matrix separating Students, Supervisors, and Coordinators; ID tampering attempts result in HTTP `403 Forbidden`.
3. **Storage Security**: Submissions and guidelines are stored outside the web root (`storage/submissions/`) using UUID filenames. Direct static file access is blocked; authenticated streaming routes enforce ownership.
4. **Content-Security-Policy & Security Headers**: Strict HTTP headers including `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and parameterized CSP.
5. **Rate Limiting**: Integrated `slowapi` rate limiting on `/auth/login` to prevent credential brute-forcing.
6. **Student Privacy in Archive**: Public project archive completely omits student PII (no USN, no email, no phone number). Only completed projects with approved final reports can be accessed by approved users.
