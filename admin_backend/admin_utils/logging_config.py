"""
统一日志配置
"""
import logging
import sys
from typing import Optional

# 日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 颜色代码
class LogColors:
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""

    COLORS = {
        logging.DEBUG: LogColors.CYAN,
        logging.INFO: LogColors.GREEN,
        logging.WARNING: LogColors.YELLOW,
        logging.ERROR: LogColors.RED,
        logging.CRITICAL: LogColors.MAGENTA,
    }

    def format(self, record):
        log_color = self.COLORS.get(record.levelno, LogColors.RESET)
        record.levelname = f"{log_color}{record.levelname}{LogColors.RESET}"
        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    use_colors: bool = True
) -> None:
    """
    配置应用日志

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径（可选）
        use_colors: 是否使用颜色（仅终端）
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # 创建根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清除已有的处理器
    root_logger.handlers.clear()

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if use_colors and sys.stdout.isatty():
        formatter = ColoredFormatter(LOG_FORMAT, DATE_FORMAT)
    else:
        formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器（如果指定）
    if log_file:
        from pathlib import Path
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的 logger"""
    return logging.getLogger(name)


# 错误码定义
class ErrorCode:
    """统一错误码"""
    # 认证相关
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    PASSWORD_TOO_WEAK = "PASSWORD_TOO_WEAK"
    PASSWORD_SAME_AS_OLD = "PASSWORD_SAME_AS_OLD"

    # 权限相关
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    SUPER_ADMIN_REQUIRED = "SUPER_ADMIN_REQUIRED"

    # 资源相关
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_ALREADY_EXISTS = "RESOURCE_ALREADY_EXISTS"
    RESOURCE_IN_USE = "RESOURCE_IN_USE"

    # 请求相关
    INVALID_REQUEST = "INVALID_REQUEST"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # 系统相关
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DATABASE_ERROR = "DATABASE_ERROR"


class APIError(Exception):
    """API 异常基类"""

    def __init__(
        self,
        message: str,
        code: str = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
        details: Optional[dict] = None
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(APIError):
    """验证错误"""

    def __init__(self, message: str, field: str = None, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            status_code=400,
            details=details or {}
        )
        if field:
            self.details["field"] = field


class NotFoundError(APIError):
    """资源不存在错误"""

    def __init__(self, resource: str = "资源", details: Optional[dict] = None):
        super().__init__(
            message=f"{resource}不存在",
            code=ErrorCode.RESOURCE_NOT_FOUND,
            status_code=404,
            details=details or {}
        )


class PermissionDeniedError(APIError):
    """权限不足错误"""

    def __init__(self, message: str = "权限不足", details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.PERMISSION_DENIED,
            status_code=403,
            details=details or {}
        )


# 初始化日志
setup_logging()
logger = get_logger(__name__)
