from __future__ import annotations

import html
import secrets
from datetime import datetime, timedelta

from backend.integrations import store
from backend.models import TgBindCode
from backend.tg_bot import login_token
from backend.tg_bot.identity import resolve


def _command_list() -> str:
    return (
        "可用命令：\n"
        "/start  欢迎与快捷入口\n"
        "/help   帮助\n"
        "/bind   绑定 Telegram\n"
        "/checkin  每日签到\n"
        "/points   查积分\n"
        "/lottery  抽奖（即将上线）"
    )


def _bind_guide_text() -> str:
    return (
        "公益服功能（签到/积分/兑换/抽奖）需要先绑定 Telegram。\n"
        "发送 /bind 获取 6 位绑定码，按指引完成绑定即可使用。"
    )


def handle_start(db, tg_user: dict, chat_id: int, args: str) -> str | tuple[str, dict | None]:
    site_name = store.get_value(db, "site_name", "Aetrix")
    name = html.escape(str(tg_user.get("first_name") or "朋友"))
    text = f"✨ 欢迎回到{site_name} ✨\n\n👋 亲爱的 {name}，你的积分、抽奖、签到，都在这里等你。"
    telegram_id = tg_user.get("id")
    web_user = resolve(db, int(telegram_id)) if telegram_id else None
    if web_user:
        # 已绑定：当前账号 + 命令列表，并尝试生成一键登录按钮
        username = html.escape(str(web_user.username or ""))
        text += f"\n• 当前账号：{username}\n\n{_command_list()}"
        url = login_token.build_login_url(db, web_user)
        if url:
            return (text, {"inline_keyboard": [[{"text": "🚀 一键免密进入控制面板", "url": url}]]})
        return text
    # 未绑定：引导先完成 Telegram 绑定
    text += (
        "\n• 公益服功能（签到/积分/红包/抽奖）需要先绑定 Telegram，1 分钟搞定：\n"
        "  ① 在网页端登录 → 个人中心 → 绑定 Telegram 获取 6 位绑定码\n"
        "  ② 把绑定码发给我即可完成绑定\n\n"
    )
    text += _command_list()
    return text


def handle_help(db, tg_user: dict, chat_id: int, args: str) -> str:
    return (
        "帮助：\n"
        "本机器人用于接收签到、积分、抽奖等公益服通知与快捷操作。\n\n"
        f"{_command_list()}\n"
        "如遇问题，请在网页端联系客服。"
    )


def handle_bind(db, tg_user: dict, chat_id: int, args: str) -> str:
    telegram_id = tg_user.get("id")
    if not telegram_id:
        return "暂时无法获取你的 Telegram ID，请稍后再试"
    if resolve(db, int(telegram_id)):
        return "你的账号已绑定，无需重复绑定；如需更换绑定请联系客服解绑。"
    # bot 发起绑定流程：生成 6 位一次性绑定码，用户在网页端个人中心输入
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    bind = TgBindCode(
        telegram_id=int(telegram_id),
        code=code,
        expires_at=datetime.now() + timedelta(minutes=10),
    )
    db.add(bind)
    db.commit()
    return (
        f"你的绑定码：{code}\n"
        "请在网页端登录后进入 个人中心 → 绑定 Telegram，输入该绑定码完成绑定。\n"
        "绑定码 10 分钟内有效，仅可使用一次。"
    )


def handle_checkin(db, tg_user: dict, chat_id: int, args: str) -> str:
    from backend.api.economy import _do_checkin_core
    from fastapi import HTTPException

    user = resolve(db, int(tg_user.get("id") or 0))
    if user is None:
        return _bind_guide_text()
    try:
        award = _do_checkin_core(db, user)
    except HTTPException as e:
        return e.detail
    except Exception:
        return "签到失败，请稍后再试"
    if award["points_awarded"] > 0:
        text = f"📅 签到成功 +{award['points_awarded']} 积分（连续 {award['streak']} 天）"
    else:
        text = f"📅 签到成功（连续 {award['streak']} 天，积分仅限公益服用户）"
    if award.get("vitality_gained", 0) > 0:
        text += f"\n⚡ 活力值 +{award['vitality_gained']}"
    return text


def handle_points(db, tg_user: dict, chat_id: int, args: str) -> str:
    user = resolve(db, int(tg_user.get("id") or 0))
    if user is None:
        return _bind_guide_text()
    points = int(user.points or 0)
    text = f"✨ 当前积分：{points}"
    try:
        from backend import vitality as _vitality

        cfg = _vitality.get_vitality_config(db)
        if cfg.get("enabled") and getattr(user, "is_welfare", False):
            v = int(getattr(user, "vitality", None) or 0)
            text += f"\n⚡ 活力值 {v}/{cfg.get('max', 14)}"
    except Exception:
        pass
    return text


def handle_redeem(db, tg_user: dict, chat_id: int, args: str) -> str:
    from backend.api.economy import _redeem_exchange_core
    from fastapi import HTTPException

    user = resolve(db, int(tg_user.get("id") or 0))
    if user is None:
        return _bind_guide_text()
    code_str = (args or "").strip()
    if not code_str:
        return "用法：/redeem 兑换码\n例如：/redeem ABCD1234"
    try:
        result = _redeem_exchange_core(db, user, code_str)
    except HTTPException as e:
        return e.detail
    except Exception:
        return "兑换失败，请稍后再试"
    return "🎁 " + str(result.get("message", "兑换成功"))
