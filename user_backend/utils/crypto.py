"""
加密服务

提供敏感数据加密/解密功能：
- Emby API Key 加密存储
- 其他敏感配置加密
"""
import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from typing import Optional

# 加密密钥（从环境变量读取，或使用派生密钥）
# 生产环境必须通过环境变量设置 CRYPTO_KEY
_CRYPTO_KEY: Optional[bytes] = None
_FERNET: Optional[Fernet] = None


def _get_crypto_key() -> bytes:
    """
    获取加密密钥

    优先级：
    1. 环境变量 CRYPTO_KEY（Base64 编码的 Fernet 密钥）
    2. 数据库配置（system_configs 表）
    3. 从 SECRET_KEY 派生

    Returns:
        加密密钥
    """
    global _CRYPTO_KEY

    if _CRYPTO_KEY is not None:
        return _CRYPTO_KEY

    # 尝试从环境变量读取
    env_key = os.getenv('CRYPTO_KEY')
    if env_key:
        try:
            _CRYPTO_KEY = base64.urlsafe_b64decode(env_key.encode())
            return _CRYPTO_KEY
        except Exception:
            pass

    # 尝试从数据库读取
    try:
        from utils.config import get_config_value
        db_key = get_config_value("crypto_key", "")
        if db_key:
            try:
                _CRYPTO_KEY = base64.urlsafe_b64decode(db_key.encode())
                return _CRYPTO_KEY
            except Exception:
                pass
    except Exception:
        pass

    # 从 SECRET_KEY 派生（不推荐用于生产环境）
    from utils.config import settings
    secret = settings.SECRET_KEY.encode()

    # 使用 PBKDF2 派生密钥
    kdf = PBKDF2(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'royalbot_emby_salt',  # 固定盐值，仅用于兼容现有密钥
        iterations=100000,
    )
    _CRYPTO_KEY = base64.urlsafe_b64encode(kdf.derive(secret))

    return _CRYPTO_KEY


def _get_fernet() -> Fernet:
    """获取 Fernet 实例"""
    global _FERNET

    if _FERNET is None:
        key = _get_crypto_key()
        _FERNET = Fernet(key)

    return _FERNET


def encrypt(plaintext: str) -> str:
    """
    加密文本

    Args:
        plaintext: 明文

    Returns:
        Base64 编码的密文
    """
    if not plaintext:
        return ""

    fernet = _get_fernet()
    encrypted = fernet.encrypt(plaintext.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt(ciphertext: str) -> str:
    """
    解密文本

    Args:
        ciphertext: Base64 编码的密文

    Returns:
        明文
    """
    if not ciphertext:
        return ""

    try:
        fernet = _get_fernet()
        encrypted = base64.urlsafe_b64decode(ciphertext.encode())
        decrypted = fernet.decrypt(encrypted)
        return decrypted.decode()
    except Exception as e:
        # 如果解密失败，可能是未加密的旧数据
        # 尝试直接返回原值
        return ciphertext


def encrypt_api_key(api_key: str) -> str:
    """
    加密 API Key

    Args:
        api_key: API Key 明文

    Returns:
        加密后的 API Key
    """
    return encrypt(api_key)


def decrypt_api_key(encrypted_key: str) -> str:
    """
    解密 API Key

    Args:
        encrypted_key: 加密的 API Key

    Returns:
        API Key 明文
    """
    return decrypt(encrypted_key)


def generate_crypto_key() -> str:
    """
    生成新的加密密钥

    用于初始化系统时生成 CRYPTO_KEY 环境变量

    Returns:
        Base64 编码的 Fernet 密钥
    """
    key = Fernet.generate_key()
    return key.decode()


def hash_identifier(identifier: str) -> str:
    """
    对标识符进行哈希（用于日志记录，避免泄露敏感信息）

    Args:
        identifier: 原始标识符

    Returns:
        哈希后的标识符
    """
    import hashlib
    return hashlib.sha256(identifier.encode()).hexdigest()[:16]
