"""
Fernet-based encryption helpers for sensitive data at rest.

Derives a stable Fernet key from the application SECRET_KEY so
encrypted values remain readable across server restarts.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def _derive_fernet_key() -> bytes:
    """Derive a URL-safe base64-encoded 32-byte key from SECRET_KEY."""
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string and return the Fernet token as a UTF-8 string."""
    fernet = Fernet(_derive_fernet_key())
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str | None:
    """Decrypt a Fernet token back to the original string.

    Returns None if decryption fails (e.g. key changed, corrupted data).
    """
    try:
        fernet = Fernet(_derive_fernet_key())
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as e:
        logger.warning("Failed to decrypt value: %s", e)
        return None
