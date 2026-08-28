"""Security, cryptography, JWT token management, and Role-Based Access Control (RBAC).

Implements:
- PBKDF2 HMAC-SHA256 password hashing with cryptographically secure salt.
- JWT Bearer token generation, decoding, and expiration validation.
- Role & Permission hierarchy (ADMIN, ANALYST, PARTNER_BANK, AUDITOR).
- FastAPI authentication dependencies for route protection.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.models import User

# Configuration & Secrets
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "sih-2026-arvix-fraud-detection-master-secret-key-32b")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Bearer scheme (auto_error=False allows optional auth for backwards compatibility)
bearer_scheme = HTTPBearer(auto_error=False)

# ── Role & Permission Definitions ──────────────────────────────────────

ROLES = {
    "ADMIN": "System Administrator / NPCI Network Admin",
    "ANALYST": "Fraud Operations Specialist / Lead Investigator",
    "PARTNER_BANK": "Partner Bank Fraud Liaison Officer",
    "AUDITOR": "Regulatory & Compliance Auditor",
    "CUSTOMER": "Retail UPI User / Citizen / Public Account",
}

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "ADMIN": {"*"},
    "ANALYST": {
        "transactions:read",
        "transactions:write",
        "alerts:read",
        "alerts:write",
        "cases:read",
        "cases:write",
        "models:score",
        "models:read",
        "audit:read",
    },
    "PARTNER_BANK": {
        "transactions:read",
        "alerts:read",
        "cases:read",
        "cases:write",
    },
    "AUDITOR": {
        "transactions:read",
        "alerts:read",
        "cases:read",
        "audit:read",
        "models:read",
    },
    "CUSTOMER": {
        "transactions:read",
        "profile:manage",
        "disputes:create",
    },
}


def get_permissions_for_role(role: str) -> List[str]:
    """Return the list of permissions associated with a given role."""
    role_upper = (role or "").upper()
    perms = ROLE_PERMISSIONS.get(role_upper, set())
    if "*" in perms:
        # Flatten all known permissions for ADMIN
        all_perms = set()
        for p_set in ROLE_PERMISSIONS.values():
            all_perms.update(p_set)
        all_perms.discard("*")
        all_perms.add("admin:all")
        return sorted(all_perms)
    return sorted(perms)


# ── Password Hashing & Verification ────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a password using salted PBKDF2 HMAC-SHA256."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return f"{salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a stored salt$hash string."""
    try:
        salt, stored_hash = hashed_password.split("$", 1)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000,
        )
        return hmac.compare_digest(key.hex(), stored_hash)
    except Exception:
        return False


# ── JWT Token Management ───────────────────────────────────────────────

def create_access_token(
    user: User,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed JWT token containing user identity and role claims."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    to_encode = {
        "sub": user.user_id,
        "email": user.email,
        "name": user.full_name,
        "role": user.role,
        "partner_bank": user.partner_bank,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token string. Returns payload dict or None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


# ── FastAPI Dependencies ───────────────────────────────────────────────

def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Optional[User]:
    """Returns the authenticated User if valid Bearer token is provided, else None."""
    if not credentials or not credentials.credentials:
        return None

    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == payload["sub"], User.is_active == True).first()
        return user
    finally:
        db.close()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> User:
    """Enforces authentication and returns the User. Raises 401 if invalid or missing."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a valid Bearer token in the Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == payload["sub"]).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account not found.",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated.",
            )
        return user
    finally:
        db.close()


def require_roles(allowed_roles: List[str]):
    """FastAPI dependency factory to enforce specific roles on endpoints."""
    allowed_set = {r.upper() for r in allowed_roles}

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.upper() not in allowed_set and current_user.role.upper() != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: requires one of the roles [{', '.join(allowed_roles)}]. Your role is '{current_user.role}'.",
            )
        return current_user

    return role_checker


def require_permissions(required_permissions: List[str]):
    """FastAPI dependency factory to enforce specific permissions on endpoints."""
    required_set = set(required_permissions)

    def permission_checker(current_user: User = Depends(get_current_user)) -> User:
        user_perms = ROLE_PERMISSIONS.get(current_user.role.upper(), set())
        if "*" in user_perms:
            return current_user

        missing = required_set - user_perms
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: missing required permissions [{', '.join(missing)}].",
            )
        return current_user

    return permission_checker
