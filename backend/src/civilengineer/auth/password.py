"""
Password hashing and verification via bcrypt.
Also provides LLM API key encryption/decryption using Fernet.
"""

from __future__ import annotations

import base64

import bcrypt
from cryptography.fernet import Fernet

from civilengineer.core.config import get_settings

# bcrypt cost factor 12 — tuned to ~250ms on modern hardware
_ROUNDS = 12


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt(rounds=_ROUNDS)
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# Password strength validation
_COMMON_PASSWORDS_SAMPLE = frozenset({
    "password", "12345678", "password1", "qwerty123", "letmein",
    "welcome1", "monkey123", "dragon123", "master123", "abc12345",
})


def validate_password_strength(password: str) -> list[str]:
    """
    Returns a list of validation failure messages (empty = valid).
    """
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit.")
    if password.lower() in _COMMON_PASSWORDS_SAMPLE:
        errors.append("Password is too common.")
    return errors


# ------------------------------------------------------------------
# Fernet encryption for LLM API keys
# ------------------------------------------------------------------

def _get_fernet() -> Fernet:
    settings = get_settings()
    key = settings.ENCRYPTION_KEY.encode()
    # Fernet requires a 32-byte URL-safe base64-encoded key.
    # If the key is not valid Fernet format, derive one from it.
    try:
        return Fernet(key)
    except Exception:
        # Derive a valid Fernet key from arbitrary bytes
        import hashlib
        raw = hashlib.sha256(key).digest()
        fernet_key = base64.urlsafe_b64encode(raw)
        return Fernet(fernet_key)


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an LLM API key for storage in PostgreSQL."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt a stored LLM API key."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
