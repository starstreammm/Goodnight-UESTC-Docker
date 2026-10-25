"""IDAS encryptPassword compatibility, verified against its 20260910 JS build."""
import base64
import secrets
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ALPHABET = 'ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678'


def random_string(length):
    return ''.join(secrets.choice(ALPHABET) for _ in range(length))


def encrypt_password(password: str, salt: str, *, random=random_string) -> str:
    """Return raw Base64; let the HTTP client's form encoder percent-encode it.

    salt is the current form's pwdEncryptSalt, used directly as the AES key.
    Unlike the browser's fallback, missing/invalid salt never sends plaintext.
    The injectable random function is for reproducible protocol tests only.
    """
    key = salt.strip().encode('utf-8')
    if len(key) not in (16, 24, 32):
        raise ValueError('Invalid IDAS password encryption key')
    prefix, iv = random(64), random(16)
    if len(prefix.encode('utf-8')) != 64 or len(iv.encode('utf-8')) != 16:
        raise ValueError('Invalid random prefix or IV length')
    padder = padding.PKCS7(128).padder()
    data = padder.update((prefix + password).encode('utf-8')) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv.encode('utf-8'))).encryptor()
    return base64.b64encode(cipher.update(data) + cipher.finalize()).decode('ascii')
