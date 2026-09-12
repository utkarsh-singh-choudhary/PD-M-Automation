from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.core.security import (
    verify_password, create_access_token, generate_refresh_token, hash_refresh_token,
)
from app.core.audit import record_audit
from app.core.auth import get_current_user
from app.core.rate_limit import is_rate_limited, record_failed_attempt, clear_attempts
from app.models.models import Employee, RefreshToken

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    name: str
    employee_id: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _issue_refresh_token(db: Session, employee_id: str, request: Request) -> str:
    raw_token = generate_refresh_token()
    db.add(RefreshToken(
        employee_id=employee_id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        user_agent=(request.headers.get("user-agent") or "")[:500],
        ip_address=request.client.host if request.client else None,
    ))
    return raw_token


@router.post("/login", response_model=LoginOut)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"

    # Brute-force protection (High Priority item). Checked before touching
    # the DB or bcrypt so a lockout can't be used to fingerprint valid
    # emails via response-time differences either.
    limited, retry_after = is_rate_limited(client_ip, form.username)
    if limited:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed login attempts. Try again in {retry_after} seconds.",
        )

    user = db.query(Employee).filter(Employee.email == form.username.strip().lower()).first()
    if not user or not user.hashed_password or not verify_password(form.password, user.hashed_password):
        record_failed_attempt(client_ip, form.username)
        # Audit trail should capture failed auth too, not just successful
        # logins (Medium: "Audit logging needs to become more complete") -
        # entity_id is intentionally omitted when the email doesn't match
        # any employee, so this can't be used to enumerate valid accounts
        # from the audit log itself.
        record_audit(
            db, action="LOGIN_FAILED", entity_type="Employee",
            entity_id=user.id if user else None,
            new_value={"attempted_email": form.username.strip().lower()},
            ip_address=client_ip,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.active:
        record_audit(db, action="LOGIN_FAILED", entity_type="Employee", entity_id=user.id,
                     new_value={"reason": "inactive_account"}, ip_address=client_ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is inactive")

    clear_attempts(client_ip, form.username)
    token = create_access_token(subject=user.id, role=user.role.value)
    refresh_token = _issue_refresh_token(db, user.id, request)
    record_audit(db, action="LOGIN", entity_type="Employee", entity_id=user.id, actor_id=user.id,
                 ip_address=client_ip)
    db.commit()

    return LoginOut(access_token=token, refresh_token=refresh_token, role=user.role.value,
                     name=user.name, employee_id=user.id)


@router.post("/refresh", response_model=TokenOut)
def refresh(payload: RefreshIn, db: Session = Depends(get_db)):
    """
    Exchanges a still-valid, unrevoked refresh token for a new short-lived
    access token. This is what lets a technician stay logged in for a full
    shift without the access token itself being a long-lived bearer
    credential (High Priority: "JWT session security can be improved").
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if not row or row.revoked_at is not None or row.expires_at < datetime.utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is invalid, expired, or revoked")

    user = db.query(Employee).get(row.employee_id)
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    access_token = create_access_token(subject=user.id, role=user.role.value)
    return TokenOut(access_token=access_token)


@router.post("/logout")
def logout(payload: RefreshIn, db: Session = Depends(get_db), user: Employee = Depends(get_current_user)):
    """
    Revokes the given refresh token server-side, so "logout" actually ends
    the session instead of just deleting a cookie client-side while the
    underlying token stays valid until natural expiry. The short-lived
    access token already in flight will still work until it naturally
    expires (at most JWT_EXPIRE_MINUTES) - that's the accepted tradeoff of
    stateless access tokens; revoking the refresh token stops the session
    from being renewed further.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    row = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash, RefreshToken.employee_id == user.id,
    ).first()
    if row and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.commit()
        record_audit(db, action="LOGOUT", entity_type="Employee", entity_id=user.id, actor_id=user.id)
    return {"success": True}
