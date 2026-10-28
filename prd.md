# PRD: Web-Based Student Project Management System (SPMS) - Python

## 1. Goal
Automate the final-year project lifecycle (topic selection, approval, supervision, submission, assessment, archiving) and automatically block duplicate topics.

## 2. Tech Stack (strict)
- Python 3.11+, FastAPI (routers, dependency injection, MVC-style structure)
- MySQL 8.0 via SQLAlchemy 2.x with the PyMySQL driver, parameterized queries only; schema.sql (or Alembic) for migrations
- Jinja2 server-rendered templates (not a separate SPA), Pydantic for validation
- Sessions: signed, HttpOnly, SameSite cookies (Starlette SessionMiddleware); bcrypt for passwords
- CSRF: per-session token validated on all state-changing requests, including uploads (token in form body, never in the URL)
- Login rate limiting (slowapi or equivalent)
- Bootstrap 5.3, Bootstrap Icons, vanilla JavaScript
- Uvicorn (dev), Gunicorn with Uvicorn workers (deploy)
- Tests: pytest with FastAPI TestClient, and Playwright (end-to-end)
- Do NOT use Django, Flask, Java, or any other backend framework

## 3. Roles
Admin/Coordinator, Supervisor, Student

## 4. Features
1. Auth: register/login, role-based access via dependencies, bcrypt hashing, sessions. PENDING/REJECTED accounts cannot log in (clear message). Admin and supervisors must change the default password on first login.
2. Student registration: name, USN (unique, login ID), department, semester/year, email (unique), phone, password; optional photo, GitHub, LinkedIn, skills. Coordinator approves or rejects accounts with remarks, and the user gets a notification.
3. Student profile: view/edit contact details (USN locked). Privacy toggle for showing email/phone to other students. Supervisors and coordinator always see them.
4. Coordinator: manage departments, sessions, supervisors (with max slots), account approvals, guidelines, deadlines.
5. Topics: supervisors publish topics; students propose their own. A student whose topic was rejected can propose again.
6. Duplicate detection: normalize title (lowercase, remove punctuation and stop words); score = 0.6 x Jaccard + 0.4 x Levenshtein similarity; reject at or above a configurable threshold (default 70%), showing the matching title and percentage. Compare against AVAILABLE, PROPOSED, APPROVED, ASSIGNED, ARCHIVED topics (ignore REJECTED). Applies to supervisor-published topics too.
7. Approval workflow: Pending -> Approved/Rejected (with remarks) -> supervisor assigned. Supervisor slot usage is computed from assignments; supervisors at max slots cannot be assigned.
8. Messaging: only the assigned student and supervisor can message each other (server-side check; changing an ID in the URL gives 403). Unread counts, newest at the bottom, timestamps, AJAX polling, pagination, escaped text.
9. Forum: department-scoped, threads and replies, authors delete own posts, coordinator deletes any, pagination.
10. Guidelines: coordinator uploads PDF/DOC/DOCX (10MB max) with title and description, edit and delete; all logged-in users view and download.
11. Notifications: bell dropdown with unread badge, mark as read, mark all as read, full page. Triggers: account approved/rejected, topic approved/rejected, supervisor assigned, new message, new guideline, new forum reply.
12. Submissions: chapters (Synopsis, SRS and Design, Implementation, Final Report) for APPROVED assignments only, PDF/DOC/DOCX, 10MB, UUID filenames, stored outside the app folder, served by an authenticated download route. Chapters open in order.
13. Deadlines: coordinator sets deadlines per session and chapter; late submissions blocked or flagged; countdown and overdue badges.
14. Supervisor feedback: Approved / Needs Revision with comments, only for their own students, version history, notification to the student.
15. GitHub link: validated as https://github.com/user/repo, editable until the final report is approved, then locked; shown to supervisor and in the archive (rel="noopener noreferrer").
16. Assessment: supervisor scores (presentation, report, implementation); coordinator finalizes grades.
17. Archive: final reports stored, searchable by year, department, keyword; archived topics feed the duplicate check.
18. Dashboards: one per role (stat cards, pending items, overdue items, progress bars).

## 5. Database Tables
users, departments, sessions, students, supervisors, topics, topic_assignments, submissions, feedback, messages, forum_posts, assessments, guidelines, deadlines, notifications. Indexes on usn, email, topics.status and all foreign keys. Provide schema.sql with seed data.

## 5a. Database Connection
- MySQL 8.0, utf8mb4, SQLAlchemy 2.x with the PyMySQL driver.
- Connection pool: pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=1800.
- Settings from environment variables (.env) validated at startup (Pydantic Settings): DB_HOST, DB_PORT (default 3306), DB_NAME, DB_USER, DB_PASSWORD, SECRET_KEY, UPLOAD_DIR, DUPLICATE_THRESHOLD. .env is never committed; provide .env.example.
- One database session per request through a FastAPI dependency; commit on success, rollback on error, always close.
- Dedicated least-privilege MySQL user for the app (not root).
- Startup check and /health route verifying the connection.
- Sync sessions with regular routes; never mix blocking DB calls inside async routes.

## 6. UI/UX Requirements
- Mobile-first, responsive at 360px, 768px, 1200px.
- Modern clean look: consistent palette, rounded cards, soft shadows, Poppins or Inter font, Bootstrap Icons.
- Collapsible navbar and off-canvas sidebar on mobile, role-based menu.
- Touch-friendly controls (44px minimum), no horizontal scrolling.
- Light and dark mode: sun/moon toggle on every page, Bootstrap data-bs-theme with CSS variables, defaults to system setting, saved in localStorage, applied before page load (no flicker), accessible contrast.
- Stat cards, status badges, progress bars, responsive tables with search, sort, pagination.
- Inline form validation, toast notifications, loading and empty states.
- Shared base template, one theme.css and one app.js.

## 7. Security
Parameterized queries only, Jinja2 auto-escaping (never mark user input safe), CSRF on all state-changing requests (token in form body, not URL), role checks on every route, upload type/size checks with safe UUID filenames, secrets and DB credentials in .env only, secure session cookies (HttpOnly, SameSite), login rate limiting, no default passwords left active, /docs and /openapi.json restricted to ADMIN or disabled in production.

## 8. Deliverables
Full source, requirements.txt, schema.sql with seed data, .env.example, README with exact steps (install MySQL, create database and user, set .env, install packages, run, deploy), pytest and Playwright tests with real results.