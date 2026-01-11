"""
统一错误处理中间件
"""
import traceback
import uuid
from typing import Callable
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.exc import IntegrityError, OperationalError, DatabaseError
from pydantic import ValidationError

from admin_utils.logging_config import get_logger, ErrorCode

logger = get_logger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """统一错误处理中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求并捕获异常"""
        # 生成请求 ID 用于追踪
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        try:
            response = await call_next(request)
            # 添加请求 ID 到响应头
            response.headers["X-Request-ID"] = request_id
            return response

        except ValidationError as e:
            # Pydantic 验证错误
            logger.warning(
                f"Validation error [{request_id}]: {e.errors()}",
                extra={"request_id": request_id, "path": str(request.url.path)}
            )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "code": ErrorCode.VALIDATION_ERROR,
                    "message": "请求参数验证失败",
                    "details": e.errors(),
                    "request_id": request_id
                }
            )

        except ValueError as e:
            # 值错误
            logger.warning(
                f"Value error [{request_id}]: {str(e)}",
                extra={"request_id": request_id, "path": str(request.url.path)}
            )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "code": ErrorCode.INVALID_REQUEST,
                    "message": str(e),
                    "request_id": request_id
                }
            )

        except IntegrityError as e:
            # 数据库完整性错误 - 区分不同类型
            error_code_orig = getattr(e.orig, '__class__.__name__', 'Unknown')

            # 检查是否是 NOT NULL 约束违反
            if 'NotNullViolation' in str(e.orig) or 'not-null constraint' in str(e.orig).lower():
                logger.error(
                    f"Database NOT NULL violation [{request_id}]: {str(e)}",
                    extra={"request_id": request_id, "path": str(request.url.path)},
                    exc_info=True
                )
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "code": ErrorCode.DATABASE_ERROR,
                        "message": "数据库约束错误，请联系管理员",
                        "request_id": request_id
                    }
                )

            # 检查是否是唯一约束违反
            elif 'UniqueViolation' in str(e.orig) or 'unique constraint' in str(e.orig).lower():
                logger.warning(
                    f"Database unique constraint error [{request_id}]: {str(e)}",
                    extra={"request_id": request_id, "path": str(request.url.path)}
                )
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={
                        "code": ErrorCode.RESOURCE_ALREADY_EXISTS,
                        "message": "数据冲突，资源已存在",
                        "request_id": request_id
                    }
                )

            # 检查是否是外键约束违反
            elif 'ForeignKeyViolation' in str(e.orig) or 'foreign key constraint' in str(e.orig).lower():
                logger.warning(
                    f"Database foreign key error [{request_id}]: {str(e)}",
                    extra={"request_id": request_id, "path": str(request.url.path)}
                )
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "code": ErrorCode.VALIDATION_ERROR,
                        "message": "关联数据不存在",
                        "request_id": request_id
                    }
                )

            # 其他完整性错误
            else:
                logger.warning(
                    f"Database integrity error [{request_id}]: {str(e)}",
                    extra={"request_id": request_id, "path": str(request.url.path)}
                )
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={
                        "code": ErrorCode.RESOURCE_ALREADY_EXISTS,
                        "message": "数据冲突",
                        "request_id": request_id
                    }
                )

        except OperationalError as e:
            # 数据库操作错误
            logger.error(
                f"Database operational error [{request_id}]: {str(e)}",
                extra={"request_id": request_id, "path": str(request.url.path)},
                exc_info=True
            )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "code": ErrorCode.DATABASE_ERROR,
                    "message": "数据库服务暂时不可用",
                    "request_id": request_id
                }
            )

        except DatabaseError as e:
            # 其他数据库错误
            logger.error(
                f"Database error [{request_id}]: {str(e)}",
                extra={"request_id": request_id, "path": str(request.url.path)},
                exc_info=True
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "code": ErrorCode.DATABASE_ERROR,
                    "message": "数据库错误",
                    "request_id": request_id
                }
            )

        except Exception as e:
            # 未捕获的异常
            logger.error(
                f"Unhandled error [{request_id}]: {str(e)}\n{traceback.format_exc()}",
                extra={
                    "request_id": request_id,
                    "path": str(request.url.path),
                    "method": request.method
                },
                exc_info=True
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "code": ErrorCode.INTERNAL_ERROR,
                    "message": "服务器内部错误",
                    "request_id": request_id
                }
            )


async def http_exception_handler(request: Request, exc) -> JSONResponse:
    """HTTP 异常处理器"""
    request_id = getattr(request.state, "request_id", "unknown")

    logger.warning(
        f"HTTP exception [{request_id}]: {exc.status_code} - {exc.detail}",
        extra={"request_id": request_id, "path": str(request.url.path)}
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": getattr(exc, "code", "HTTP_ERROR"),
            "message": exc.detail,
            "request_id": request_id
        }
    )
