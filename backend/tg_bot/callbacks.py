"""callback_query 处理（B3 已实现：抢红包按钮）。"""

from __future__ import annotations

import html
import logging
from datetime import datetime

from backend import models
from . import redpacket_common, sender
from .identity import resolve

logger = logging.getLogger(__name__)


def handle_callback(db, callback_query: dict) -> None:
    packet_id = redpacket_common.parse_claim_data(callback_query.get("data"))
    if packet_id is None:
        logger.debug("tg unknown callback data: %s", callback_query.get("data"))
        return

    cq_id = callback_query.get("id")
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")

    def _answer(text: str, show_alert: bool = False) -> None:
        if not cq_id:
            return
        sender.answer_callback_query(db, cq_id, text, show_alert)

    if not redpacket_common.enabled(db):
        _answer("🧧 红包功能已关闭")
        return

    user = resolve(db, int((callback_query.get("from") or {}).get("id") or 0))
    if user is None:
        _answer("请先绑定 Telegram 后再抢红包（发送 /bind 获取绑定码）", show_alert=True)
        return

    packet = db.query(models.RedPacket).filter(models.RedPacket.id == packet_id).first()
    if packet is None:
        _answer("红包不存在")
        return

    sender_user = db.query(models.WebUser).filter(models.WebUser.id == packet.sender_id).first()
    sender_name = html.escape(str(sender_user.username)) if sender_user and sender_user.username else "未知"

    def _update_message(text: str, reply_markup: dict) -> None:
        if not chat_id or not message_id:
            logger.warning("tg redpacket message update skipped: chat_id=%s message_id=%s", chat_id, message_id)
            return
        ok, err = sender.edit_message_text(db, chat_id, message_id, text, reply_markup)
        if not ok:
            logger.warning("tg redpacket message update failed: chat_id=%s message_id=%s err=%s", chat_id, message_id, err)

    now = datetime.now()
    if packet.expires_at and packet.expires_at < now:
        _answer("🧧 红包已过期")
        _update_message(redpacket_common.finished_text(packet, sender_name, "expired"), {"inline_keyboard": []})
        return

    if packet.remaining_count <= 0:
        _answer("🧧 红包已被抢完")
        _update_message(redpacket_common.finished_text(packet, sender_name, "empty"), {"inline_keyboard": []})
        return

    from backend import welfare_redpacket

    try:
        result = welfare_redpacket.claim_packet(db, user, packet_id)
    except ValueError as e:
        err = str(e)
        logger.warning("tg redpacket claim rejected: packet=%s user=%s err=%s", packet_id, user.id, err)
        _answer(f"🧧 {err}")
        if "已被抢完" in err:
            _update_message(redpacket_common.finished_text(packet, sender_name, "empty"), {"inline_keyboard": []})
        elif "已过期" in err:
            _update_message(redpacket_common.finished_text(packet, sender_name, "expired"), {"inline_keyboard": []})
        return
    except Exception:
        logger.exception("tg redpacket claim failed: packet=%s user=%s", packet_id, user.id)
        _answer("🧧 抢红包失败，请稍后再试")
        return

    amount = result["amount"]
    _answer(f"🧧 恭喜抢到 {amount} 积分！")
    logger.info(
        "tg redpacket claimed: packet=%s user=%s amount=%s remaining=%s",
        packet_id,
        user.id,
        amount,
        packet.remaining_count,
    )
    if packet.remaining_count <= 0:
        _update_message(redpacket_common.finished_text(packet, sender_name, "empty"), {"inline_keyboard": []})
    else:
        _update_message(redpacket_common.packet_text(packet, sender_name), redpacket_common.claim_markup(packet_id))
