"""Encrypted copies for explicit authenticated password viewing; login uses scrypt."""
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from app.config import load_config


class PasswordVaultError(RuntimeError):
    """The configured encryption key is missing or cannot decrypt stored data."""


def initialize_key(*, has_passwords):
    """Create a private key only for storage that has no encrypted passwords yet."""
    path = Path(load_config()['security']['password_key_file'])
    if not path.exists():
        if has_passwords:
            raise PasswordVaultError('密码查看密钥缺失，请恢复原密钥文件；不要重新生成密钥')
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass  # Another initializer created the same deployment key.
        else:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
    _cipher()


def _cipher():
    try:
        return Fernet(Path(load_config()['security']['password_key_file']).read_bytes())
    except (OSError, ValueError) as error:
        raise PasswordVaultError('密码查看密钥不可用，请检查 security.password_key_file') from error


def encrypt_password(password):
    """Encrypt the exact supplied password, preserving whitespace and Unicode."""
    return _cipher().encrypt(password.encode('utf-8')).decode('ascii')


def decrypt_password(ciphertext):
    """Authenticate and decrypt a stored copy; an incorrect key fails visibly."""
    try:
        return _cipher().decrypt(ciphertext.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError, ValueError) as error:
        raise PasswordVaultError('密码密文无法解密，请恢复与数据库配套的原密钥文件') from error
