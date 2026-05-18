"""
crypto.py — AES-256 (Fernet) encryption / decryption helper.
"""

import os
import logging
from cryptography.fernet import Fernet
from config import KEY_PATH, DATA_DIR

logger = logging.getLogger(__name__)


class CryptoManager:
    """Symmetric encryption wrapper.  Key is auto-generated on first run."""

    def __init__(self, key_path: str) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        self._cipher = Fernet(self._load_or_create(key_path))
        logger.info("Encryption ready (key: %s)", key_path)

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _load_or_create(path: str) -> bytes:
        if not os.path.exists(path):
            key = Fernet.generate_key()
            with open(path, "wb") as fh:
                fh.write(key)
            logger.info("New encryption key generated → %s", path)
        with open(path, "rb") as fh:
            return fh.read()

    # ── Public API ────────────────────────────────────────────────────────────

    def encrypt(self, plaintext: str) -> str:
        return self._cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._cipher.decrypt(token.encode()).decode()


# Singleton — import and use directly
crypto = CryptoManager(KEY_PATH)
