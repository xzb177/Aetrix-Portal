"""
加密工具
用于加密敏感信息，如 API Key
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# 从环境变量获取加密密钥，如果没有则生成一个
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '')
if not ENCRYPTION_KEY:
    # 生产环境必须设置此环境变量！
    ENCRYPTION_KEY = 'CHANGE_THIS_IN_PRODUCTION_USE_ENV_VAR_32BYTES!!'


def _get_cipher():
    """获取加密器"""
    # 使用 PBKDF2HMAC 从密钥派生 Fernet 密钥
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'royalbot_emby_salt',  # 固定 salt，实际应用中应该从配置读取
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(ENCRYPTION_KEY.encode()))
    return Fernet(key)


def encrypt(text: str) -> str:
    """
    加密文本

    Args:
        text: 明文

    Returns:
        密文（Base64 编码）
    """
    if not text:
        return ''
    cipher = _get_cipher()
    encrypted = cipher.encrypt(text.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt(encrypted_text: str) -> str:
    """
    解密文本

    Args:
        encrypted_text: 密文（Base64 编码）

    Returns:
        明文
    """
    if not encrypted_text:
        return ''
    try:
        cipher = _get_cipher()
        decrypted = cipher.decrypt(base64.urlsafe_b64decode(encrypted_text))
        return decrypted.decode()
    except Exception:
        # 如果解密失败，可能是因为使用了旧的明文存储，直接返回
        return encrypted_text
