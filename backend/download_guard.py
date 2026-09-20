"""网关级下载策略兜底

站点关闭下载（`allow_download=false`）时，仅在 `/Download` 单条路由上判断是不够的：
Emby 客户端还会走 `/Items/{id}/File` 这类等价路径。这里在 ASGI 层做统一兜底，
避免将来新增下载类路由时漏判造成绕过。

实现要点：
- 纯 ASGI 中间件，**不是** BaseHTTPMiddleware —— 后者会包裹响应体，
  可能影响本站的大文件流式播放（StreamingResponse / FileResponse）。
- 路径不匹配时原样透传（零开销），匹配时才查库判策略。
- 未认证 / 解析不到用户时放行，交回原路由返回 401，不改变原有错误语义。
- 管理员始终放行，与路由内 `ensure_download_allowed` 口径一致。
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def is_download_path(path: str) -> bool:
    """下载类路径判定（大小写不敏感，兼容尾斜杠）"""
    p = (path or "").rstrip("/").lower()
    return p.endswith("/download") or p.endswith("/file")


def _is_privileged(user) -> bool:
    for attr in ("is_staff", "is_admin", "is_superuser"):
        if getattr(user, attr, False):
            return True
    return False


class DownloadGuardMiddleware:
    """下载策略网关级兜底中间件"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not is_download_path(scope.get("path", "")):
            return await self.app(scope, receive, send)

        blocked = self._blocked_message(scope)
        if blocked is None:
            return await self.app(scope, receive, send)

        response = JSONResponse({"detail": blocked}, status_code=403)
        return await response(scope, receive, send)

    # ---- 内部 ----

    @staticmethod
    def _blocked_message(scope) -> str | None:
        """返回 403 文案；None 表示放行。"""
        try:
            from backend.database import SessionLocal
            from backend.emby_server.auth import resolve_request_user
            from backend.subscriptions import DOWNLOAD_GATE_MESSAGE, download_allowed
        except Exception:  # pragma: no cover - 导入失败时不影响主流程
            logger.exception("下载策略兜底初始化失败，已放行")
            return None

        db = SessionLocal()
        try:
            if download_allowed(db):
                return None

            # 只读 header / query，不消费 body，原 receive 仍交给下游路由
            request = Request(scope, receive=None)
            user = resolve_request_user(db, request)
            if user is None:
                # 拿不到身份就交回原路由处理（通常是 401），不改错误语义
                return None

            if _is_privileged(user):
                return None
            return DOWNLOAD_GATE_MESSAGE
        except Exception:  # pragma: no cover
            logger.exception("下载策略兜底判定失败，已放行")
            return None
        finally:
            db.close()
