"""callback_query 处理：抽奖参加按钮（lottery_join:{round_id}）。"""
from __future__ import annotations

import logging

from backend.tg_bot.identity import resolve

logger = logging.getLogger(__name__)


def handle_callback(db, callback_query: dict) -> None:
    """处理 callback_query：抽奖参加按钮。"""
    data = (callback_query.get("data") or "")
    if data.startswith("lottery_join:"):
        _handle_lottery_join(db, callback_query)
        return
    logger.debug("callback_query ignored: %s", data[:64])


def _answer_callback(db, callback_id, text: str, show_alert: bool = False) -> None:
    """调用 answerCallbackQuery 给用户 toast 提示（幂等、可重复调用）。"""
    if not callback_id:
        return
    try:
        from backend.integrations.telegram import token as get_token

        token = get_token(db)
    except Exception:
        logger.exception("get telegram token failed")
        return
    if not token:
        logger.debug("telegram token empty, skip answerCallbackQuery")
        return
    try:
        import httpx

        httpx.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={
                "callback_query_id": callback_id,
                "text": text[:180],
                "show_alert": show_alert,
            },
            timeout=10.0,
        )
    except Exception:
        logger.exception("answerCallbackQuery failed")


def _lottery():
    """惰性导入 lottery 模块（G1 契约），不可用时返回 None。"""
    try:
        from backend import lottery

        return lottery
    except ImportError:
        return None


def _handle_lottery_join(db, callback_query: dict) -> None:
    """处理抽奖参加按钮点击（幂等）。"""
    cb_id = callback_query.get("id")
    try:
        data = callback_query.get("data") or ""
        from_user = callback_query.get("from") or {}
        telegram_id = from_user.get("id")
        msg = callback_query.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")

        # 1. 解析 round_id
        try:
            round_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            _answer_callback(db, cb_id, "请求无效，请重新点击")
            return
        if not cb_id:
            return

        # 2. 功能开关
        lot = _lottery()
        if lot is None:
            _answer_callback(db, cb_id, "🎲 抽奖功能暂未开启")
            return
        try:
            enabled = bool(lot.is_enabled(db))
        except Exception:
            logger.exception("lottery.is_enabled failed")
            enabled = False
        if not enabled:
            _answer_callback(db, cb_id, "🎲 抽奖功能暂未开启")
            return

        # 3. 取 round（兜底链）
        round_obj = None
        if hasattr(lot, "get_round"):
            try:
                round_obj = lot.get_round(db, round_id)
            except Exception:
                logger.exception("lottery.get_round failed")
                round_obj = None
        if round_obj is None and chat_id is not None:
            try:
                active = lot.get_active_round(db, chat_id)
            except Exception:
                logger.exception("lottery.get_active_round failed")
                active = None
            if active is not None and getattr(active, "id", None) == round_id:
                round_obj = active
        if round_obj is None:
            _answer_callback(db, cb_id, "本轮抽奖已结束")
            return

        # 4. 状态与开奖时间校验
        status = str(getattr(round_obj, "status", "open") or "open")
        if status != "open":
            _answer_callback(db, cb_id, "本轮抽奖已结束")
            return
        draw_at = getattr(round_obj, "draw_at", None)
        if draw_at is not None:
            from datetime import datetime

            if isinstance(draw_at, datetime) and draw_at <= datetime.now():
                _answer_callback(db, cb_id, "本轮抽奖已结束")
                return

        # 5. 群组 allowlist
        allowed = None
        if hasattr(lot, "allowed_group_ids"):
            try:
                allowed = lot.allowed_group_ids(db)
            except Exception:
                logger.exception("lottery.allowed_group_ids failed")
                allowed = None
        if allowed is None:
            from backend.integrations import store

            raw = store.get_value(db, "lottery_group_ids", "") or ""
            allowed = {int(p) for p in raw.split(",") if p.strip().isdigit()}
        if allowed and chat_id not in allowed:
            _answer_callback(db, cb_id, "本群暂未开放抽奖")
            return

        # 6. 用户身份
        user = resolve(db, int(telegram_id)) if telegram_id else None
        if user is None:
            _answer_callback(
                db,
                cb_id,
                "请先绑定账号后再参加（发送 /bind 查看指引）",
                show_alert=True,
            )
            return

        # 7. 参加（幂等核心）
        try:
            result = lot.join_round(db, round_obj, user, int(telegram_id))
        except Exception:
            logger.exception("lottery_join failed")
            _answer_callback(db, cb_id, "参加失败，请稍后再试")
            return
        ok = bool(result.get("ok")) if isinstance(result, dict) else bool(result)
        reason = result.get("reason") if isinstance(result, dict) else ""
        if ok:
            _answer_callback(db, cb_id, "🎉 参加成功，祝你好运！")
        elif reason == "already":
            _answer_callback(db, cb_id, "你已参加过本轮抽奖")
        elif reason == "full":
            _answer_callback(db, cb_id, "名额已满，下次再来")
        elif reason in ("closed", "disabled"):
            _answer_callback(db, cb_id, "本轮抽奖已结束")
        else:
            _answer_callback(db, cb_id, "参加失败，请稍后再试")
    except Exception:
        logger.exception("handle lottery_join callback failed")
        _answer_callback(db, cb_id, "系统繁忙，请稍后再试")
