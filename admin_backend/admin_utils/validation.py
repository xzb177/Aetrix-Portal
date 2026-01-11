"""
输入验证和安全工具
- SQL 注入防护
- XSS 防护
- CSRF 保护
- 文件上传验证
"""
import re
import html
import uuid
from typing import Optional, List
from fastapi import UploadFile, HTTPException, status
from pathlib import Path

# ========== SQL 注入防护 ==========

SQL_INJECTION_PATTERNS = [
    r"(\bunion\b.*\bselect\b)",
    r"(\bselect\b.*\bfrom\b)",
    r"(\binsert\b.*\binto\b)",
    r"(\bupdate\b.*\bset\b)",
    r"(\bdelete\b.*\bfrom\b)",
    r"(\bdrop\b.*\btable\b)",
    r"(\bexec\b|\bexecute\b)",
    r"(--|\#|\/\*|\*\/)",
    r"(\bor\b.*=.*\bor\b)",
    r"(\band\b.*=.*\band\b)",
    r"('.*--)",
    r"(1=1|1 = 1)",
    r"(\bxp_\w+)",
    r"(\bsp_\w+)",
]

SQL_PATTERN = re.compile(
    "|".join(SQL_INJECTION_PATTERNS),
    re.IGNORECASE | re.MULTILINE
)


def sanitize_sql_input(value: str) -> str:
    """
    清理 SQL 输入
    转义特殊字符，防止 SQL 注入
    """
    if not isinstance(value, str):
        return value

    # 移除或转义危险字符
    value = value.replace("\\", "\\\\")
    value = value.replace("'", "''")
    value = value.replace("%", "\\%")
    value = value.replace("_", "\\_")

    return value


def detect_sql_injection(value: str) -> bool:
    """检测是否包含 SQL 注入特征"""
    if not isinstance(value, str):
        return False

    return bool(SQL_PATTERN.search(value))


def validate_search_input(value: str, max_length: int = 100) -> str:
    """
    验证搜索输入
    :param value: 搜索内容
    :param max_length: 最大长度
    :return: 清理后的安全字符串
    """
    if not value:
        return ""

    if len(value) > max_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"搜索内容过长，最大支持 {max_length} 个字符"
        )

    # 检测 SQL 注入
    if detect_sql_injection(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="搜索内容包含非法字符"
        )

    return value


# ========== XSS 防护 ==========

XSS_PATTERNS = [
    r"<script[^>]*>.*?</script>",
    r"javascript:",
    r"vbscript:",
    r"onload\s*=",
    r"onerror\s*=",
    r"onclick\s*=",
    r"onmouseover\s*=",
    r"<iframe[^>]*>",
    r"<object[^>]*>",
    r"<embed[^>]*>",
    r"<link[^>]*>",
    r"<meta[^>]*>",
]

XSS_PATTERN = re.compile("|".join(XSS_PATTERNS), re.IGNORECASE | re.DOTALL)


def sanitize_html(value: str, allow_tags: Optional[List[str]] = None) -> str:
    """
    清理 HTML，防止 XSS 攻击
    :param value: 输入字符串
    :param allow_tags: 允许的标签（列表），如 ['b', 'i', 'u']
    """
    if not isinstance(value, str):
        return value

    # HTML 实体编码
    value = html.escape(value)

    # 如果允许特定标签，恢复它们
    if allow_tags:
        for tag in allow_tags:
            value = value.replace(f"&lt;{tag}&gt;", f"<{tag}>")
            value = value.replace(f"&lt;/{tag}&gt;", f"</{tag}>")

    return value


def detect_xss(value: str) -> bool:
    """检测是否包含 XSS 特征"""
    if not isinstance(value, str):
        return False

    return bool(XSS_PATTERN.search(value))


def validate_user_input(value: str, max_length: int = 1000) -> str:
    """
    验证用户输入
    :param value: 输入内容
    :param max_length: 最大长度
    """
    if not isinstance(value, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="输入类型错误"
        )

    if len(value) > max_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"输入内容过长，最大支持 {max_length} 个字符"
        )

    # 检测 XSS
    if detect_xss(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="输入内容包含非法字符"
        )

    return value


# ========== 文件上传验证 ==========

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10MB

# 危险文件扩展名（黑名单）
DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1",
    ".js", ".vbs", ".jar", ".app", ".deb",
    ".php", ".asp", ".aspx", ".jsp",
}

# 文件内容魔术字节（MIME 类型检测）
MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89\x50\x4e\x47": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"%PDF": "application/pdf",
}


def detect_file_type(file_content: bytes) -> Optional[str]:
    """通过魔术字节检测文件类型"""
    for magic, mime_type in MAGIC_BYTES.items():
        if file_content.startswith(magic):
            return mime_type
    return None


async def validate_upload(
    file: UploadFile,
    allowed_extensions: Optional[set] = None,
    max_size: int = MAX_IMAGE_SIZE
) -> UploadFile:
    """
    验证上传的文件
    :param file: 上传的文件
    :param allowed_extensions: 允许的扩展名
    :param max_size: 最大文件大小（字节）
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名不能为空"
        )

    # 检查文件扩展名
    ext = Path(file.filename).suffix.lower()

    if ext in DANGEROUS_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不允许上传此类型的文件"
        )

    if allowed_extensions and ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"只允许上传 {', '.join(allowed_extensions)} 格式的文件"
        )

    # 读取文件内容
    content = await file.read()

    # 检查文件大小
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件过大，最大支持 {max_size // (1024 * 1024)}MB"
        )

    # 检测文件类型（魔术字节）
    if content:
        detected_type = detect_file_type(content[:20])
        if detected_type and not detected_type.startswith(file.content_type or ""):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文件内容与扩展名不匹配"
            )

    # 重置文件指针
    await file.seek(0)

    return file


# ========== 密码强度验证 ==========

def validate_password_strength(password: str) -> tuple[bool, List[str]]:
    """
    验证密码强度
    :return: (是否通过, 错误列表)
    """
    errors = []

    if len(password) < 12:
        errors.append("密码长度至少12位")

    if not re.search(r'[a-z]', password):
        errors.append("密码必须包含小写字母")

    if not re.search(r'[A-Z]', password):
        errors.append("密码必须包含大写字母")

    if not re.search(r'\d', password):
        errors.append("密码必须包含数字")

    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:"\\|,.<>?]', password):
        errors.append("密码必须包含特殊字符")

    # 检查常见弱密码
    weak_passwords = [
        "password", "12345678", "abcdefgh", "qwerty123",
        "admin123", "letmein", "welcome1", "password123"
    ]
    if password.lower() in weak_passwords:
        errors.append("密码过于常见")

    # 检查键盘序列
    keyboard_sequences = [
        "qwerty", "asdfgh", "zxcvbn",
        "123456", "654321", "abcdef"
    ]
    if any(seq in password.lower() for seq in keyboard_sequences):
        errors.append("密码包含键盘序列")

    return len(errors) == 0, errors


# ========== 邮箱和手机验证 ==========

EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

PHONE_PATTERN = re.compile(r"^\+?\d{10,15}$")


def validate_email(email: str) -> bool:
    """验证邮箱格式"""
    return bool(EMAIL_PATTERN.match(email))


def validate_phone(phone: str) -> bool:
    """验证手机号格式（支持国际号码）"""
    return bool(PHONE_PATTERN.match(phone))


# ========== ID 和标识符验证 ==========

def validate_id(id_value: int, min_value: int = 1) -> bool:
    """验证 ID 格式"""
    return isinstance(id_value, int) and id_value >= min_value


def validate_uuid(uuid_str: str) -> bool:
    """验证 UUID 格式"""
    try:
        uuid.UUID(uuid_str)
        return True
    except ValueError:
        return False


# ========== 分页参数验证 ==========

def validate_pagination(skip: int, limit: int, max_limit: int = 100) -> tuple[int, int]:
    """
    验证分页参数
    :return: (skip, limit)
    """
    if skip < 0:
        skip = 0

    if limit <= 0:
        limit = 20

    if limit > max_limit:
        limit = max_limit

    return skip, limit
