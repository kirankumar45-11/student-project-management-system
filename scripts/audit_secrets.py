import os
import re
from pathlib import Path

def audit():
    root = Path(__file__).resolve().parent.parent
    ignored_dirs = {".venv", ".pytest_cache", "screenshots", "storage", ".git", "__pycache__"}
    flagged_code_secrets = []
    flagged_log_passwords = []

    # Patterns
    secret_assignment_pattern = re.compile(
        r'(SECRET_KEY|DB_PASSWORD|MYSQL_PASSWORD|ADMIN_PASSWORD)\s*=\s*[\'"][^\'"]+[\'"]', 
        re.IGNORECASE
    )
    password_log_pattern = re.compile(
        r'(one-time password is|initial password is|generated password is|password:\s*[^a-zA-Z\s]|user password is)', 
        re.IGNORECASE
    )

    print("[AUDIT] Scanning all codebase files and log files for exposed passwords and secrets...")

    # 1. Scan codebase and any workspace files (including .log files)
    for path in root.rglob("*"):
        if path.is_file():
            if any(part in ignored_dirs for part in path.parts):
                continue
            if path.name in {".env", ".admin_initial_secret"}:
                continue
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf", ".docx", ".doc", ".pyc"}:
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for idx, line in enumerate(content.splitlines(), 1):
                # Search for hardcoded credentials
                if secret_assignment_pattern.search(line):
                    if not any(token in line for token in ["os.getenv", "Field(", "your_", "<", "placeholder", "None", ".env", "default="]):
                        flagged_code_secrets.append((path.relative_to(root), idx, line.strip()))

                # Search for password leakage in log files or print statements
                if path.suffix.lower() == ".log" or "logger." in line or "print(" in line:
                    if password_log_pattern.search(line):
                        flagged_log_passwords.append((path.relative_to(root), idx, line.strip()))

    print(f"[AUDIT SUMMARY]")
    print(f"  Hardcoded code secrets found: {len(flagged_code_secrets)}")
    for f, l, txt in flagged_code_secrets:
        print(f"    [SECRET] {f}:{l}: {txt}")

    print(f"  Log file / print statement password leaks found: {len(flagged_log_passwords)}")
    for f, l, txt in flagged_log_passwords:
        print(f"    [LOG LEAK] {f}:{l}: {txt}")

    if not flagged_code_secrets and not flagged_log_passwords:
        print("[AUDIT SUCCESS] ZERO passwords or secrets found across codebase and log files!")
        return 0
    else:
        print("[AUDIT WARNING] Potential secrets or passwords detected.")
        return 1

if __name__ == "__main__":
    exit(audit())
