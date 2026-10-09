"""Telegram 消息发送模块"""

import httpx

from backend.integrations.telegram import token as get_telegram_token


def send_message(db, chat_id: int, text: str, reply_markup: dict | None = None) -> tuple[bool, str | None]:
    """
    向指定 Telegram 聊天发送消息

    :param db: 数据库会话对象
    :param chat_id: 目标聊天 ID
    :param text: 消息文本内容
    :param reply_markup: 可选的键盘标记（Telegram API 格式）
    :return: (是否成功, 错误信息)，成功时为 (True, None)
    """
    # 从数据库读取 Bot Token
    bot_token = get_telegram_token(db)

    # Token 为空时直接返回失败
    if not bot_token:
        return False, "token 未配置"

    # 构造请求负载
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    # 拼接发送消息的 API 地址
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

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

