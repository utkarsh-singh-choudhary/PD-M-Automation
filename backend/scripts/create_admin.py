"""
Creates the first Admin account, or promotes an existing Employee row to
Admin and sets/resets their password.

Why this script exists: employee creation (POST /api/employees) is
Admin-only by design (app/routers/employees.py), which is correct for
ongoing use but leaves no way to create the very first Admin account
through the API. This script is the one-time (or occasional
password-reset) escape hatch — it uses the exact same bcrypt hashing as
normal login (app.core.security.hash_password), so the account it creates
logs in through the normal /api/auth/login flow with no special-casing.

Usage (run from the backend/ directory, with DATABASE_URL pointing at the
real DB — i.e. the same .env the API/scheduler use):

    python scripts/create_admin.py --email admin@yourcompany.com --name "Admin Name"

You'll be prompted for a password interactively (not passed as a CLI arg,
so it never ends up in shell history). Re-running with the same --email
updates that employee's password and role instead of creating a duplicate,
so this also doubles as a password-reset tool for any account, not just
the first one.

In Docker: `docker compose exec backend python scripts/create_admin.py --email ... --name ...`
"""

import argparse
import getpass
import sys

sys.path.insert(0, ".")  # so `app.*` imports resolve when run as `python scripts/create_admin.py`

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.models import Employee, Role


def main():
    parser = argparse.ArgumentParser(description="Create or promote the first Admin account.")
    parser.add_argument("--email", required=True, help="Login email for the admin account")
    parser.add_argument("--name", required=True, help="Display name")
    parser.add_argument("--employee-code", default=None, help="Optional employee code")
    args = parser.parse_args()

    password = getpass.getpass("Set password for this account: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match. Nothing was changed.")
        sys.exit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters. Nothing was changed.")
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.query(Employee).filter(Employee.email == args.email).first()
        if existing:
            existing.hashed_password = hash_password(password)
            existing.role = Role.ADMIN
            existing.active = True
            db.commit()
            print(f"Updated existing employee '{existing.name}' <{existing.email}> "
                  f"-> role=ADMIN, password reset.")
        else:
            emp = Employee(
                name=args.name,
                email=args.email,
                employee_code=args.employee_code,
                role=Role.ADMIN,
                hashed_password=hash_password(password),
                active=True,
                notification_email_enabled=True,
            )
            db.add(emp)
            db.commit()
            print(f"Created new Admin '{emp.name}' <{emp.email}>. You can now log in at /login.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
