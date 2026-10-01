"""
Password hashing and session-token primitives.

Passwords are hashed with Argon2id. Session tokens are 256-bit random values;
only their SHA-256 digest is stored, so a database leak does not yield usable
sessions. Access codes for restricted microsites reuse the password hasher.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Verified against when the email is unknown, so response time does not reveal
# whether an account exists.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def password_problems(password: str, *, min_length: int) -> list[str]:
    """Human-readable reasons a proposed password is too weak (empty list = acceptable)."""
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"Use at least {min_length} characters.")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        problems.append("Mix at least three of: lowercase, uppercase, digits, symbols.")
    return problems
