"""封装 Telegram Bot API 消息发送（复用单个 httpx.Client，线程安全、永不抛异常）。"""
from __future__ import annotations

import html
import logging

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"


class TgSender:
    """Telegram 消息发送器；token 仅出现在请求 URL 中，绝不写入日志。"""

    def __init__(self, bot_token: str) -> None:
        self._token = bot_token
        self._client = httpx.Client(timeout=10)

    def _url(self, method: str) -> str:
        return f"{_API_BASE}/bot{self._token}/{method}"

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
        disable_preview: bool = True,
    ) -> bool:
        """发送 HTML 消息；失败记 warning 返回 False，永不抛异常。"""
        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            resp = self._client.post(self._url("sendMessage"), json=payload)
        except Exception as exc:
            # 只记异常类型，避免异常信息里携带含 token 的 URL
            logger.warning("sendMessage 网络异常 chat_id=%s err=%s", chat_id, type(exc).__name__)
            return False
        if resp.status_code >= 400:
            logger.warning("sendMessage 失败 chat_id=%s status=%s", chat_id, resp.status_code)
            return False
        return True

    def close(self) -> None:
        """关闭底层 httpx.Client。"""
        try:
            self._client.close()
        except Exception:
            logger.warning("关闭 TgSender client 异常", exc_info=True)

    @staticmethod
    def build_url_keyboard(button_text: str, url: str) -> dict:
        """构造单按钮 URL 键盘。"""
        return {"inline_keyboard": [[{"text": button_text, "url": url}]]}

    @staticmethod
    def escape(text: str) -> str:
        """HTML 转义用户可控内容（回复文本必须先过本方法）。"""
        return html.escape(text)
