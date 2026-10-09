"""TG 红包共享逻辑（B3）：总开关、callback_data 编解码、按钮与消息文案。"""
from __future__ import annotations

from backend.integrations import store

# callback_data 前缀，按钮回调形如 "redpacket_claim:<packet_id>"
CALLBACK_PREFIX = "redpacket_claim:"
# 总开关配置键（SystemConfig），"1"=开启，默认开启
CONFIG_KEY = "redpacket_bot_enabled"


def enabled(db) -> bool:
    """红包总开关是否开启（默认开启）。"""
    return store.get_value(db, CONFIG_KEY, "1") == "1"


def parse_claim_data(data: str | None) -> int | None:
    """解析按钮 callback_data，返回 packet_id；格式不对返回 None。"""
    if not data or not data.startswith(CALLBACK_PREFIX):
        return None
    raw = data[len(CALLBACK_PREFIX):]
    if not raw or not raw.isdigit():
        return None
    return int(raw)


def claim_markup(packet_id: int) -> dict:
    """抢红包 inline 按钮的 reply_markup。"""
    return {
        "inline_keyboard": [
            [{"text": "🧧 抢红包", "callback_data": f"{CALLBACK_PREFIX}{packet_id}"}]
        ]
    }


def packet_text(packet, sender_name: str) -> str:
    """红包进行中的按钮消息正文。packet 是 backend.models.RedPacket 对象。
    包含：🧧 表情、发送者名、总额 X 积分 / 共 N 个、剩余 M 个（剩余 Y 积分）、"24 小时后过期，先到先得"。
    纯文本多行，不要 markdown。"""
    return (
        f"🧧 {sender_name} 的红包\n"
        f"总额 {packet.total_amount} 积分 / 共 {packet.total_count} 个\n"
        f"剩余 {packet.remaining_count} 个（剩余 {packet.remaining_amount} 积分）\n"
        f"24 小时后过期，先到先得"
    )


def finished_text(packet, sender_name: str, reason: str) -> str:
    """红包终态的按钮消息正文。reason: "empty"（已抢完）/ "expired"（已过期）。
    包含：🧧 表情、发送者名、总额 X 积分 / 共 N 个；empty → "🎉 红包已抢完"；expired → "⌛ 红包已过期"。
    注意：过期退款由后端定时任务 refund_expired 执行，这里不宣称已退款。"""
    if reason == "empty":
        status = "🎉 红包已抢完"
    else:
        status = "⌛ 红包已过期"
    return (
        f"🧧 {sender_name} 的红包\n"
        f"总额 {packet.total_amount} 积分 / 共 {packet.total_count} 个\n"
        f"{status}"
    )
