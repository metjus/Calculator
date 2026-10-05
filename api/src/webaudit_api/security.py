"""Passwords, session tokens and encryption of stored API keys."""

from __future__ import annotations

import base64
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

_hasher = PasswordHasher()

SESSION_COOKIE = "wa_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "webaudit"
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_session_token() -> tuple[str, str]:
    """Return (raw token for the cookie, sha256 hash stored in the database)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class KeyBox:
    """Encrypts customer API keys at rest (Fernet, key derived from WEBAUDIT_SECRET_KEY)."""

    def __init__(self, secret_key: str) -> None:
        digest = hashlib.sha256(b"webaudit/api-keys/v1:" + secret_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str | None:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            return None  # secret key changed; the user has to enter the key again
