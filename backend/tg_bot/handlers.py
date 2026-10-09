from __future__ import annotations

import html
from datetime import datetime

from backend.integrations import store
from backend.models import SubscriptionPlan, TgBindCode, UserSubscription, WebUser
from backend.tg_bot import login_token
from backend.tg_bot import redpacket_common
from backend.tg_bot.identity import resolve


def _command_list() -> str:
    return (
        "可用命令：\n"
        "/start  欢迎与快捷入口\n"
        "/help   帮助\n"
        "/bind   绑定 Telegram\n"
        "/checkin  每日签到\n"
        "/points   查积分\n"
        "/redpacket  发红包：/redpacket <总积分> <个数>\n"
        "/lottery  抽奖（即将上线）"
    )


def _bind_guide_text() -> str:
    return (
        "🔗 如何绑定账号\n"
        "1️⃣ 登录网站 Dashboard\n"
        '2️⃣ 点击"绑定 Telegram"按钮\n'
        "3️⃣ 复制弹窗中显示的绑定码\n"
        "4️⃣ 回到这里发送：/bind 绑定码\n"
        "\n"
        "绑定后可收到：\n"
        "• 求片进度通知\n"
        "• 订阅到期提醒\n"
        "• 签到领积分"
    )


def _bind_success_text(db, user) -> str:
    username = html.escape(str(user.username or ""))
    now = datetime.now()
    sub = (
        db.query(UserSubscription)
        .filter(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
            UserSubscription.end_date > now,
        )
        .order_by(UserSubscription.end_date.desc())
        .first()
    )
    plan_name = "无"
    if sub:
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first()
        if plan:
            plan_name = html.escape(str(plan.name))
    has_sub = sub is not None
    return (
        "✅ 绑定成功！\n"
        f"👤 用户名：{username}\n"
        f"📦 订阅服务：{plan_name}\n"
        f"{'✅' if has_sub else '❌'} 订阅状态：{'有' if has_sub else '无'}有效订阅\n"
        "您将收到：\n"
        "• 求片进度通知\n"
        "• 订阅到期提醒\n"
        "• 系统公告推送"
    )


def verify_bind_code(db, tg_user_id: int, chat_id: int, code: str) -> str | None:
    now = datetime.now()
    record = (
        db.query(TgBindCode)
        .filter(
            TgBindCode.code == code.strip(),
            TgBindCode.user_id.isnot(None),
            TgBindCode.telegram_id.is_(None),
            TgBindCode.used_at.is_(None),
            TgBindCode.expires_at > now,
        )
        .order_by(TgBindCode.id.desc())
        .first()
    )
    if not record:
        return None
    user = db.query(WebUser).filter(WebUser.id == record.user_id).first()
    if not user:
        return None
    other = (
        db.query(WebUser)
        .filter(WebUser.telegram_id == tg_user_id, WebUser.id != user.id)
        .first()
    )
    if other:
        return "该 Telegram 账号已被其他用户绑定"
    user.telegram_id = tg_user_id
    record.telegram_id = tg_user_id
    record.used_at = now
    db.commit()
    return _bind_success_text(db, user)


def handle_start(db, tg_user: dict, chat_id: int, args: str) -> str | tuple[str, dict | None]:
    site_name = store.get_value(db, "site_name", "Aetrix")
    name = html.escape(str(tg_user.get("first_name") or "朋友"))
    text = f"✨ 欢迎回到{site_name} ✨\n\n👋 亲爱的 {name}，你的积分、抽奖、签到，都在这里等你。"
    telegram_id = tg_user.get("id")
    web_user = resolve(db, int(telegram_id)) if telegram_id else None
    if web_user:
        username = html.escape(str(web_user.username or ""))
        text += f"\n• 当前账号：{username}\n\n{_command_list()}"
        url = login_token.build_login_url(db, web_user)
        if url:
            return (text, {"inline_keyboard": [[{"text": "🚀 一键免密进入控制面板", "url": url}]]})
        return text
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
        "\n\n"
        f"{_bind_guide_text()}"
    )


def handle_bind(db, tg_user: dict, chat_id: int, args: str) -> str:
    telegram_id = tg_user.get("id")
    if not telegram_id:
        return "暂时无法获取你的 Telegram ID，请稍后再试"
    if resolve(db, int(telegram_id)):
        return "你的账号已绑定，无需重复绑定；如需更换绑定请联系客服解绑。"
    if not args.strip():
        return _bind_guide_text()
    msg = verify_bind_code(db, int(telegram_id), chat_id, args.strip())
    return msg if msg else "绑定码无效或已过期，请在网页端重新获取绑定码"


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
    return "🎁 " + str(result.get("message", "兑换成功"))


def handle_redpacket(db, tg_user: dict, chat_id: int, args: str) -> str | tuple[str, dict | None]:
    # 1. 总开关：关闭时直接提示
    if not redpacket_common.enabled(db):
        return "🧧 红包功能已关闭"
    # 2. 身份：未绑定则引导绑定
    user = resolve(db, int(tg_user.get("id") or 0))
    if user is None:
        return _bind_guide_text()
    # 3. 参数：取前两个并转 int，数量不对或转换失败则提示用法
    parts = args.split()[:2]
    if len(parts) != 2:
        return "用法：/redpacket <总积分> <个数>\n例如：/redpacket 100 10（100 积分分成 10 个）"
    try:
        total, count = int(parts[0]), int(parts[1])
    except ValueError:
        return "用法：/redpacket <总积分> <个数>\n例如：/redpacket 100 10（100 积分分成 10 个）"
    # 4. 发红包：复用后端校验与扣减逻辑
    from backend import welfare_redpacket
    try:
        packet = welfare_redpacket.send_packet(db, user, total, count)
    except ValueError as e:
        return f"🧧 {e}"
    except Exception:
        return "🧧 发红包失败，请稍后再试"
    # 5. 成功：返回红包正文与领取按钮
    sender_name = html.escape(str(user.username or "朋友"))
    text = redpacket_common.packet_text(packet, sender_name)
    return (text, redpacket_common.claim_markup(packet.id))
