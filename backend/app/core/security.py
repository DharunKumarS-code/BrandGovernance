"""Phase 9 Stage 2: password hashing + JWT access tokens.

Reuses the existing jwt_secret_key/jwt_algorithm/jwt_expire_minutes
settings (unused until now) and the already-installed passlib[bcrypt] /
python-jose[cryptography] dependencies -- no new packages.
"""

import time

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(*, user_id: str, organisation_id: str, role: str) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    now = int(time.time())
    expires_in = settings.jwt_expire_minutes * 60
    payload = {"sub": user_id, "org": organisation_id, "role": role, "iat": now, "exp": now + expires_in}
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """Raises jose.JWTError for any invalid/expired/malformed/
    wrong-signature token -- callers must catch and turn into a 401,
    never trust a decode failure as "no auth provided"."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


__all__ = ["hash_password", "verify_password", "create_access_token", "decode_access_token", "JWTError"]
