import random
import datetime

from backend.tg_bot.identity import resolve
from backend.models import TgBindCode


def _command_list() -> str:
    """返回命令列表文本"""
    return (
        "/start - 开始使用\n"
        "/help - 帮助\n"
        "/bind - 绑定账号\n"
        "/checkin - 每日签到（B2）\n"
        "/points - 查积分（B2）"
    )


def handle_start(db, tg_user: dict, chat_id: int, args: str) -> str:
    """/start：欢迎语，根据是否已绑定返回不同引导"""
    # 查询该 Telegram 用户是否已绑定 WebUser
    tg_user_id = tg_user.get("id")
    web_user = resolve(db, tg_user_id) if tg_user_id else None
    name = tg_user.get("first_name") or "用户"

    if web_user is not None:
        # 已绑定：欢迎回来 + 命令列表
        return f"欢迎回来，{name}！\n\n{_command_list()}"

    # 未绑定：欢迎 + 绑定引导 + 命令列表
    return (
        f"欢迎使用，{name}！\n\n"
        "发送 /bind 获取绑定码，然后在网页个人中心输入完成绑定。\n\n"
        f"{_command_list()}"
    )


def handle_help(db, tg_user: dict, chat_id: int, args: str) -> str:
    """/help：返回命令列表"""
    return _command_list()


def handle_bind(db, tg_user: dict, chat_id: int, args: str) -> str:
    """/bind：生成 6 位数字绑定码并入库（10 分钟有效）"""
    tg_user_id = tg_user.get("id")
    # 已绑定用户无需重复绑定
    if tg_user_id and resolve(db, tg_user_id) is not None:
        return "您已绑定，无需重复绑定"

    # 生成 6 位数字绑定码
    code = f"{random.randint(0, 999999):06d}"
    expires_at = datetime.datetime.now() + datetime.timedelta(minutes=10)

    # 创建绑定码记录并提交
    bind_code = TgBindCode(
        telegram_id=tg_user_id,
        code=code,
        expires_at=expires_at,
    )
    db.add(bind_code)
    db.commit()

    return f"你的绑定码是 {code}（10 分钟有效）。请在网页个人中心输入此码完成绑定。"

