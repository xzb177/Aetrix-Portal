"""群抽奖 G1 核心服务。

职责：
- 群抽奖轮次的创建、参与、开奖、发奖与结果核验；
- 开关与群组白名单走 SystemConfig（lottery_enabled / lottery_group_ids）；
- 开奖算法为纯函数 compute_winners：score = sha256(f"{seed}:{entry_id}") 升序分配；
- 奖品发放复用经济系统原语 _add_points 与门户福利原语 portal.grant_welfare，
  均在函数内懒导入，避免循环依赖。
"""

import hashlib
import secrets
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import models

logger = logging.getLogger(__name__)

_PRIZE_TYPES = ("days", "points", "whitelist")


def _get_str_config(db: Session, key: str, default: str) -> str:
    """读取 SystemConfig 字符串配置，缺失时返回默认值。"""
    cfg = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    return cfg.value if cfg else default


def is_enabled(db: Session) -> bool:
    """群抽奖总开关：lottery_enabled 为 "1" 或 "true"（去空格、忽略大小写）时开启，默认 "1"。"""
    val = _get_str_config(db, "lottery_enabled", "1").strip().lower()
    return val in ("1", "true")


def allowed_group_ids(db: Session) -> set[int]:
    """读取允许发起抽奖的群 id 集合（lottery_group_ids，逗号分隔）；空集合表示不限制。"""
    val = _get_str_config(db, "lottery_group_ids", "")
    ids: set[int] = set()
    for part in val.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            # 非法片段跳过
            continue
    return ids


def create_round(
    db: Session,
    title: str,
    chat_id: int,
    prizes: list[dict],
    draw_at: datetime | None = None,
    max_participants: int = 0,
    created_by: int | None = None,
) -> models.LotteryRound:
    """创建抽奖轮次及其奖品列表。

    prizes 每项为 dict(name, type, value, quantity)，type 仅允许 days/points/whitelist；
    sort 按列表顺序从 0 递增。seed 明文入库（开奖后才公开，不展示），
    seed_hash 存其 sha256 供核验。
    """
    if not title or not title.strip():
        raise ValueError("标题不能为空")
    if not prizes:
        raise ValueError("奖品列表不能为空")
    for p in prizes:
        if p.get("type") not in _PRIZE_TYPES:
            raise ValueError(f"不支持的奖品类型：{p.get('type')}")

    seed = secrets.token_hex(32)
    round = models.LotteryRound(
        title=title,
        chat_id=chat_id,
        seed=seed,
        seed_hash=hashlib.sha256(seed.encode()).hexdigest(),
        status="open",
        draw_at=draw_at,
        max_participants=max_participants or 0,
        created_by=created_by,
    )
    db.add(round)
    db.flush()  # 取得 round.id 供奖品外键使用
    for sort, p in enumerate(prizes):
        db.add(
            models.LotteryRoundPrize(
                round_id=round.id,
                name=p.get("name"),
                type=p.get("type"),
                value=p.get("value", 0),
                quantity=p.get("quantity", 0),
                sort=sort,
            )
        )
    db.commit()
    db.refresh(round)
    return round


def get_active_round(db: Session, chat_id: int) -> models.LotteryRound | None:
    """返回该群当前进行中的轮次（status='open'，按 id 倒序取第一条），没有则 None。"""
    return (
        db.query(models.LotteryRound)
        .filter(models.LotteryRound.chat_id == chat_id, models.LotteryRound.status == "open")
        .order_by(models.LotteryRound.id.desc())
        .first()
    )


def get_round(db: Session, round_id: int) -> models.LotteryRound | None:
    """按 id 取抽奖轮次，没有则 None（供 TG 参加按钮回调等按 id 取活动）。"""
    return (
        db.query(models.LotteryRound)
        .filter(models.LotteryRound.id == round_id)
        .first()
    )


def join_round(
    db: Session,
    round: models.LotteryRound,
    user: models.WebUser,
    telegram_id: int,
) -> dict[str, Any]:
    """用户参与本轮抽奖。

    不抛异常，用 dict 表达结果，方便调用方（TG 回调）直接映射文案：
    - 成功：{"ok": True, "entry": entry}
    - 失败：{"ok": False, "reason": "already" | "full" | "closed" | "disabled"}
      （已参加过 / 名额已满 / 活动已结束或未开始 / 功能总开关关闭）
    并发重复参加由 uq_lottery_round_entry 唯一约束兜底，同样返回 already。
    """
    if not is_enabled(db):
        return {"ok": False, "reason": "disabled"}
    if round.status != "open":
        return {"ok": False, "reason": "closed"}
    exists = (
        db.query(models.LotteryRoundEntry.id)
        .filter(
            models.LotteryRoundEntry.round_id == round.id,
            models.LotteryRoundEntry.user_id == user.id,
        )
        .first()
    )
    if exists:
        return {"ok": False, "reason": "already"}
    if round.max_participants and round.max_participants > 0:
        current = (
            db.query(models.LotteryRoundEntry)
            .filter(models.LotteryRoundEntry.round_id == round.id)
            .count()
        )
        if current >= round.max_participants:
            return {"ok": False, "reason": "full"}

    entry = models.LotteryRoundEntry(
        round_id=round.id,
        user_id=user.id,
        telegram_id=telegram_id,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        # 并发窗口：预检查通过后另一请求先插入，唯一约束兜底；必须先 rollback
        db.rollback()
        return {"ok": False, "reason": "already"}
    return {"ok": True, "entry": entry}


def compute_winners(seed: str, entry_ids: list[int], prizes: list[dict]) -> dict[int, list[int]]:
    """纯函数，不碰数据库：按 score 升序分配奖品。

    score = sha256(f"{seed}:{entry_id}")，entry 按 (score, entry_id) 升序排列保证确定性；
    按 prizes 列表顺序，每个 prize 取 quantity 个尚未中奖者；
    quantity<=0 的奖品跳过（不占名额）；entry 不足时按实际人数分配（不报错）。
    返回 {prize_id: [entry_id, ...]}。
    """
    scored = [
        (hashlib.sha256(f"{seed}:{eid}".encode()).hexdigest(), eid)
        for eid in entry_ids
    ]
    scored.sort(key=lambda item: (item[0], item[1]))
    ordered_ids = [eid for _, eid in scored]

    result: dict[int, list[int]] = {}
    cursor = 0
    for p in prizes:
        quantity = p.get("quantity", 0) or 0
        if quantity <= 0:
            continue
        winners: list[int] = []
        while quantity > 0 and cursor < len(ordered_ids):
            winners.append(ordered_ids[cursor])
            cursor += 1
            quantity -= 1
        result[p["id"]] = winners
    return result


def draw_round(db: Session, round_id: int) -> list[models.LotteryRoundWinner]:
    """执行开奖。

    状态机：open/drawing -> drawing -> done。done 幂等直接返回已有结果（按 id 排序）；
    drawing 视为上次开奖中断，可重入（先清理遗留 winner 行再重算）。
    entry 为空或 prize 为空时正常结束：status='done'、drawn_at 落库、返回 []。

    注意：drawing 重入是给"开奖进程崩溃"准备的恢复路径，不是给并发调用准备的——
    调用方（定时任务/管理后台）必须保证同一轮次同一时刻只有一个开奖者在跑。
    """
    round = db.query(models.LotteryRound).filter(models.LotteryRound.id == round_id).first()
    if not round:
        raise ValueError("抽奖轮次不存在")
    if round.status == "done":
        return (
            db.query(models.LotteryRoundWinner)
            .filter(models.LotteryRoundWinner.round_id == round_id)
            .order_by(models.LotteryRoundWinner.id.asc())
            .all()
        )
    if round.status == "cancelled":
        raise ValueError("已取消的轮次不能开奖")

    # 先占状态，防并发重复开奖
    round.status = "drawing"
    db.commit()

    # 清理上次中断遗留的 winner 行，保证幂等
    db.query(models.LotteryRoundWinner).filter(models.LotteryRoundWinner.round_id == round_id).delete()

    entry_ids = [
        row.id
        for row in db.query(models.LotteryRoundEntry.id)
        .filter(models.LotteryRoundEntry.round_id == round_id)
        .order_by(models.LotteryRoundEntry.id.asc())
        .all()
    ]
    prizes = (
        db.query(models.LotteryRoundPrize)
        .filter(models.LotteryRoundPrize.round_id == round_id)
        .order_by(models.LotteryRoundPrize.sort.asc(), models.LotteryRoundPrize.id.asc())
        .all()
    )

    result = compute_winners(round.seed, entry_ids, [{"id": p.id, "quantity": p.quantity} for p in prizes])

    for prize_id, entry_id_list in result.items():
        for entry_id in entry_id_list:
            db.add(models.LotteryRoundWinner(round_id=round_id, entry_id=entry_id, prize_id=prize_id))

    round.status = "done"
    round.drawn_at = datetime.now()
    db.commit()

    logger.info(
        "群抽奖开奖完成 round_id=%s 参与人数=%s 中奖记录=%s",
        round_id,
        len(entry_ids),
        sum(len(v) for v in result.values()),
    )

    return (
        db.query(models.LotteryRoundWinner)
        .filter(models.LotteryRoundWinner.round_id == round_id)
        .order_by(models.LotteryRoundWinner.id.asc())
        .all()
    )


def distribute_round(db: Session, round_id: int) -> dict[str, Any]:
    """按开奖结果发放奖品。

    幂等：distributed 已为 True 的跳过；单个发奖失败回滚并记入 errors，不中断整轮。
    返回 {"round_id", "total", "distributed", "skipped", "errors"}。
    """
    # 函数内懒导入，避免循环依赖
    from backend.api.economy import _add_points
    from backend.emby_server import portal

    round = db.query(models.LotteryRound).filter(models.LotteryRound.id == round_id).first()
    if not round:
        raise ValueError("抽奖轮次不存在")
    if round.status != "done":
        raise ValueError("尚未开奖")

    winners = (
        db.query(models.LotteryRoundWinner)
        .filter(models.LotteryRoundWinner.round_id == round_id)
        .order_by(models.LotteryRoundWinner.id.asc())
        .all()
    )
    prizes_by_id = {
        p.id: p
        for p in db.query(models.LotteryRoundPrize).filter(models.LotteryRoundPrize.round_id == round_id).all()
    }
    entries_by_id = {
        e.id: e
        for e in db.query(models.LotteryRoundEntry).filter(models.LotteryRoundEntry.round_id == round_id).all()
    }

    total = len(winners)
    distributed = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for w in winners:
        if w.distributed:
            skipped += 1
            continue
        prize = prizes_by_id.get(w.prize_id)
        entry = entries_by_id.get(w.entry_id)
        if prize is None or entry is None:
            errors.append({"winner_id": w.id, "error": "奖品或参与记录缺失"})
            continue
        user = db.query(models.WebUser).filter(models.WebUser.id == entry.user_id).first()
        if user is None:
            errors.append({"winner_id": w.id, "error": "用户不存在"})
            continue
        try:
            if prize.type == "points":
                if (prize.value or 0) <= 0:
                    errors.append({"winner_id": w.id, "error": f"积分奖品 value 非正：{prize.value}"})
                    continue
                _add_points(db, user, prize.value, "lottery_win", f"群抽奖中奖：{prize.name}", f"lottery:{round_id}")
            elif prize.type == "days":
                if (prize.value or 0) <= 0:
                    # days=0 在 grant_welfare 语义里是永久，days 奖品不许借道发放永久资格
                    errors.append({"winner_id": w.id, "error": f"天数奖品 value 非正：{prize.value}"})
                    continue
                portal.grant_welfare(db, user, channel="lottery_win", days=prize.value)
            elif prize.type == "whitelist":
                # days=0 表示永不过期（已核实 grant_welfare 源码）
                portal.grant_welfare(db, user, channel="lottery_win", days=0)
            else:
                errors.append({"winner_id": w.id, "error": f"未知奖品类型：{prize.type}"})
                continue
        except Exception as exc:
            # 单个失败不中断整轮
            db.rollback()
            errors.append({"winner_id": w.id, "error": str(exc)})
            continue
        w.distributed = True
        w.distributed_at = datetime.now()
        db.commit()
        distributed += 1
        logger.info(
            "群抽奖发奖成功 round_id=%s winner_id=%s prize=%s type=%s",
            round_id,
            w.id,
            prize.name,
            prize.type,
        )

    return {
        "round_id": round_id,
        "total": total,
        "distributed": distributed,
        "skipped": skipped,
        "errors": errors,
    }


def verify_round(db: Session, round_id: int) -> dict[str, Any]:
    """生成轮次核验报告。

    包含 seed 明文与 seed_hash、算法说明、参与者列表（telegram_id 打码）、
    中奖列表（现场用与 compute_winners 相同的公式重算 score），可供外部复算验证。
    """
    round = db.query(models.LotteryRound).filter(models.LotteryRound.id == round_id).first()
    if not round:
        raise ValueError("抽奖轮次不存在")

    entries = (
        db.query(models.LotteryRoundEntry)
        .filter(models.LotteryRoundEntry.round_id == round_id)
        .order_by(models.LotteryRoundEntry.id.asc())
        .all()
    )
    winners = (
        db.query(models.LotteryRoundWinner)
        .filter(models.LotteryRoundWinner.round_id == round_id)
        .order_by(models.LotteryRoundWinner.id.asc())
        .all()
    )
    prizes_by_id = {
        p.id: p
        for p in db.query(models.LotteryRoundPrize).filter(models.LotteryRoundPrize.round_id == round_id).all()
    }

    def mask_telegram(telegram_id: int) -> str:
        s = str(telegram_id)
        if len(s) <= 4:
            return "*" * len(s)
        return "****" + s[-4:]

    entries_out = [
        {
            "entry_id": e.id,
            "user_id": e.user_id,
            "telegram_id_masked": mask_telegram(e.telegram_id),
        }
        for e in entries
    ]
    winners_out = []
    for w in winners:
        score = hashlib.sha256(f"{round.seed}:{w.entry_id}".encode()).hexdigest()
        prize = prizes_by_id.get(w.prize_id)
        winners_out.append(
            {
                "entry_id": w.entry_id,
                "prize_name": prize.name if prize else None,
                "score": score,
            }
        )

    return {
        "round_id": round.id,
        "title": round.title,
        "status": round.status,
        "seed_hash": round.seed_hash,
        "seed": round.seed,
        "algorithm": "sha256(seed:entry_id)升序",
        "entries": entries_out,
        "winners": winners_out,
    }

