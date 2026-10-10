"""Telegram 消息发送模块"""

import httpx

from backend.integrations.telegram import token as get_telegram_token


def _call(db, method: str, payload: dict) -> tuple[bool, str | None]:
    """
    调用 Telegram Bot API 的通用私有方法

    统一完成：读取 Bot Token（为空则直接失败）→ POST 请求 →
    校验 HTTP 状态码 → 检查响应 ok 字段

    :param db: 数据库会话对象
    :param method: Telegram API 方法名（如 sendMessage）
    :param payload: 请求负载（Telegram API 格式）
    :return: (是否成功, 错误信息)，成功时为 (True, None)
    """
    # 从数据库读取 Bot Token
    bot_token = get_telegram_token(db)

    # Token 为空时直接返回失败
    if not bot_token:
        return False, "token 未配置"

    # 拼接 API 地址
    url = f"https://api.telegram.org/bot{bot_token}/{method}"

    try:
        # 同步 POST 请求，超时 15 秒
        response = httpx.post(url, json=payload, timeout=15.0)
        response.raise_for_status()

        data = response.json()
        # Telegram API 返回 ok=false 时视为失败
        if not data.get("ok", False):
            return False, f"Telegram API 错误: {data.get('description', '未知错误')}"

        return True, None
    except httpx.HTTPStatusError as exc:
        # HTTP 状态码异常
        return False, f"HTTP 状态码错误: {exc.response.status_code}"
    except httpx.TimeoutException:
        # 请求超时
        return False, "请求超时"
    except httpx.RequestError as exc:
        # 网络请求异常
        return False, f"网络请求失败: {exc}"
    except ValueError:
        # 响应 JSON 解析失败
        return False, "响应解析失败"


def send_message(db, chat_id: int, text: str, reply_markup: dict | None = None) -> tuple[bool, str | None]:
    """
    向指定 Telegram 聊天发送消息

    :param db: 数据库会话对象
    :param chat_id: 目标聊天 ID
    :param text: 消息文本内容
    :param reply_markup: 可选的键盘标记（Telegram API 格式）
    :return: (是否成功, 错误信息)，成功时为 (True, None)
    """
    # 构造请求负载
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    return _call(db, "sendMessage", payload)


def delete_message(db, chat_id: int, message_id: int) -> tuple[bool, str | None]:
    """删除一条消息（群里需要 Bot 有删除权限；失败由调用方忽略）。"""
    return _call(db, "deleteMessage", {"chat_id": chat_id, "message_id": message_id})


def edit_message_text(db, chat_id: int, message_id: int, text: str, reply_markup: dict | None = None) -> tuple[bool, str | None]:
    """
    原地编辑指定消息的文本与键盘（不重发新消息）

    用途：抢红包后原地更新按钮消息

    :param db: 数据库会话对象
    :param chat_id: 目标聊天 ID
    :param message_id: 要编辑的消息 ID
    :param text: 新的消息文本内容
    :param reply_markup: 可选的键盘标记（Telegram API 格式）
    :return: (是否成功, 错误信息)，成功时为 (True, None)
    """
    # 构造请求负载
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    return _call(db, "editMessageText", payload)


def answer_callback_query(db, callback_query_id: str, text: str | None = None, show_alert: bool = False) -> tuple[bool, str | None]:
    """
    回复按钮点击的回执请求

    用途：按钮点击回执，可选弹出提示文本

    :param db: 数据库会话对象
    :param callback_query_id: 回调查询 ID
    :param text: 可选的提示文本，非空时才携带
    :param show_alert: 为 True 时以弹窗形式展示提示文本
    :return: (是否成功, 错误信息)，成功时为 (True, None)
    """
    # 构造请求负载
    payload = {
        "callback_query_id": callback_query_id,
    }
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True

    return _call(db, "answerCallbackQuery", payload)


# 三重门·身份门：在群成员列表里才算自己人
_MEMBER_STATUSES = ("creator", "administrator", "member", "restricted")


def get_chat_member(db, chat_id: int, user_id: int) -> tuple[bool | None, str]:
    """查用户在群里的成员状态（三重门·身份门）。

    :return: (is_member, status)
        - (True, status)：在群里，status 为 creator/administrator/member/restricted
        - (False, status)：不在群里（left/kicked）或查无此人
        - (None, "api_error")：TG API 调用失败（网络/限流/token问题），
          调用方应 fail-open（放行但记日志），可用性优先
    """
    import httpx

    from backend.integrations.telegram import token as get_telegram_token

    bot_token = get_telegram_token(db)
    if not bot_token:
        return None, "api_error"
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/getChatMember",
            json={"chat_id": chat_id, "user_id": user_id},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None, "api_error"
    if not data.get("ok"):
        # 用户不在群里时 TG 返回 ok=false（"user not found" / "chat not found"）
        desc = str(data.get("description", "")).lower()
        if "not found" in desc or "chat not found" in desc:
            return False, "not_found"
        return None, "api_error"
    status = str((data.get("result") or {}).get("status", ""))
    return (status in _MEMBER_STATUSES), status
