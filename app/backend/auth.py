from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import os
import logging
import secrets
from database import get_db
import models

logger = logging.getLogger(__name__)

# The insecure placeholder that used to be the hardcoded fallback. Treated as
# "unset" so it can never sign real tokens, even if it lingers in an env file.
_INSECURE_DEFAULT = "your-secret-key-change-in-production-2025"
_PRODUCTION_ENVS = {"production", "prod", "staging"}


def _load_secret_key() -> str:
    """Resolve the JWT signing key without ever shipping a hardcoded secret.

    - Configured ``JWT_SECRET_KEY`` -> use it.
    - Missing (or the known insecure placeholder) in a production/staging
      ``ENVIRONMENT`` -> fail fast, rather than sign tokens with a guessable key
      (which would let anyone forge a valid session).
    - Missing in dev/test -> generate an ephemeral random key for this process
      (tokens simply don't survive a restart), so local/CI runs work without
      configuration and without a shared secret in source.
    """
    key = os.environ.get("JWT_SECRET_KEY")
    env = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if key and key != _INSECURE_DEFAULT:
        return key
    if env in _PRODUCTION_ENVS:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set to a secure value but ENVIRONMENT="
            f"{env!r}. Refusing to start: set JWT_SECRET_KEY to a strong random "
            "secret (e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
        )
    logger.warning(
        "JWT_SECRET_KEY not configured — using an ephemeral development key. "
        "Tokens will not survive a restart; set JWT_SECRET_KEY for stable sessions."
    )
    return secrets.token_urlsafe(48)


# Security configuration
SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> models.User:
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    email: str = payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    return user
