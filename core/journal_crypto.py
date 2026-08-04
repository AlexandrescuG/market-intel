"""
journal_crypto.py — AES-256-GCM шифрование для инвестор-паролей.

Ключ берётся из env JOURNAL_ENCRYPT_KEY (base64url, 32 байта).
Нон — 12 случайных байт, хранится вместе с шифротекстом (prefix).
"""
from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    raw = os.environ.get("JOURNAL_ENCRYPT_KEY", "")
    if raw:
        try:
            key = base64.urlsafe_b64decode(raw + "==")
            if len(key) == 32:
                return key
        except Exception:
            pass
    # fallback для dev — детерминированный ключ из hostname+salt
    # НЕ использовать в проде без JOURNAL_ENCRYPT_KEY
    import hashlib, socket
    seed = (socket.gethostname() + "_sbf_journal_dev_key").encode()
    return hashlib.sha256(seed).digest()


def encrypt_password(plaintext: str) -> tuple[str, str]:
    """
    Возвращает (encrypted_b64, iv_b64).
    encrypted_b64 содержит только ciphertext+tag (без nonce).
    """
    key = _get_key()
    iv = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode(), None)
    return (
        base64.b64encode(ciphertext).decode(),
        base64.b64encode(iv).decode(),
    )


def decrypt_password(encrypted_b64: str, iv_b64: str) -> str:
    key = _get_key()
    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(encrypted_b64)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext, None).decode()
