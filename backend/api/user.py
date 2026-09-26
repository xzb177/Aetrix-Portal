"""
用户端 API 路由
与管理后台联动，用户可接收管理员操作的通知
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from sqlalchemy import func

from backend.database import get_db
from backend import codes, devices, models, realms
from backend.db_retry import commit_with_retry
from backend.notifications import get_notification_service, AdminEvent
from backend.ratelimit import check_rate_limit
from backend.security import resolve_jwt_user_id

logger = logging.getLogger(__name__)

# 创建路由
user_router = APIRouter(prefix="/api/user", tags=["用户端"])

# 认证方案
security = HTTPBearer(auto_error=False)


# ==================== 依赖注入 ====================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> models.WebUser:
    """获取当前登录用户（JWT access token 鉴权）"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证"
        )

    user_id = resolve_jwt_user_id(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或已过期的凭证"
        )

    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )

    return user


# ==================== 请求/响应模型 ====================

class MessageResponse(BaseModel):
    """站内消息响应"""
    id: int
    title: str
    content: str
    message_type: str
    related_id: Optional[int]
    is_read: bool
    created_at: str
    from_user: Optional[str] = None

    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    """未读消息数响应"""
    unread_count: int


class TicketCreateRequest(BaseModel):
    """工单创建请求"""
    title: str
    category: str = "other"
    message: str


class TicketReplyRequest(BaseModel):
    """工单回复请求（回复无需标题，此前误用创建模型，前端不得不塞占位 title）"""
    message: str


class TicketCreateResponse(BaseModel):
    """工单创建响应"""
    success: bool
    ticket_id: int
    message: str


class TicketResponse(BaseModel):
    """工单响应"""
    id: int
    title: str
    category: str
    status: str
    priority: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class TicketMessageResponse(BaseModel):
    """工单消息响应"""
    id: int
    message: str
    is_admin: bool
    created_at: str
    admin_name: Optional[str] = None

    class Config:
        from_attributes = True


class AnnouncementResponse(BaseModel):
    """公告响应"""
    id: int
    title: str
    content: str
    type: str
    is_pinned: bool
    created_at: str

    class Config:
        from_attributes = True


# ==================== 认证/用户信息 API ====================

# /auth/me 已迁移至 backend/api/emby_portal.py（JWT 鉴权版，见 auth_router）


# ==================== 站内消息 API ====================

@user_router.get("/messages", response_model=List[MessageResponse])
async def get_messages(
    unread_only: bool = False,
    limit: int = 50,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取站内消息列表

    ``limit`` 收口到 1..200：这是用户可控的查询参数，不夹一下就能一次把
    整个收件箱拉走（消息中心自己没有翻页，所以给了上限也不会有人取不到旧消息）。
    """
    notification_service = get_notification_service()

    messages = await notification_service.get_messages(
        user_id=current_user.id,
        limit=max(1, min(limit, 200)),
        unread_only=unread_only,
        db=db
    )

    result = []
    for msg in messages:
        from_name = None
        if msg.from_user:
            from_name = msg.from_user.username

        result.append(MessageResponse(
            id=msg.id,
            title=msg.title,
            content=msg.content,
            message_type=msg.message_type,
            related_id=msg.related_id,
            is_read=msg.is_read,
            created_at=msg.created_at.isoformat(),
            from_user=from_name
        ))

    return result


@user_router.get("/messages/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取未读消息数量"""
    notification_service = get_notification_service()

    count = await notification_service.get_unread_count(
        user_id=current_user.id,
        db=db
    )

    return UnreadCountResponse(unread_count=count)


@user_router.post("/messages/{message_id}/read")
async def mark_message_read(
    message_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """标记消息为已读"""
    notification_service = get_notification_service()

    success = await notification_service.mark_as_read(
        message_id=message_id,
        user_id=current_user.id,
        db=db
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="消息不存在"
        )

    return {"success": True, "message": "消息已标记为已读"}


@user_router.post("/messages/read-all")
async def mark_all_read(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """标记所有消息为已读（批量 UPDATE 下放线程池，实时推送仍 await）"""
    user_id = current_user.id

    def _mark_all() -> None:
        # 批量更新未读消息
        db.query(models.StationMessage).filter(
            models.StationMessage.to_user_id == user_id,
            models.StationMessage.is_read == False
        ).update({
            "is_read": True,
            "read_at": datetime.now()
        })
        db.commit()

    await run_in_threadpool(_mark_all)

    # 通知 WebSocket
    from backend.websocket import send_notification
    await send_notification(
        notification_type="station.unread_count",
        user_id=user_id,
        title="",
        message="",
        data={"unread_count": 0}
    )

    return {"success": True, "message": "所有消息已标记为已读"}


# ==================== 兑换码 API ====================

# ==================== 工单 API ====================

@user_router.get("/tickets", response_model=List[TicketResponse])
def get_my_tickets(
    status_filter: Optional[str] = None,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取我的工单列表"""
    query = db.query(models.Ticket).filter(
        models.Ticket.user_id == current_user.id
    )

    if status_filter:
        query = query.filter(models.Ticket.status == status_filter)

    tickets = query.order_by(models.Ticket.updated_at.desc()).all()

    return [
        TicketResponse(
            id=t.id,
            title=t.title,
            category=t.category,
            status=t.status,
            priority=t.priority,
            created_at=t.created_at.isoformat(),
            updated_at=t.updated_at.isoformat()
        )
        for t in tickets
    ]


@user_router.post("/tickets", response_model=TicketCreateResponse)
async def create_ticket(
    request: TicketCreateRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新工单 - 与后台工单系统联动（落库下放线程池，通知仍 await）"""
    user_id = current_user.id
    username = current_user.username   # 提交后回读属性=隐式回查，先在循环上取成纯值

    def _create() -> int:
        ticket = models.Ticket(
            user_id=user_id,
            title=request.title,
            category=request.category,
            status="open",
            priority="medium"
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        ticket_id = ticket.id

        # 创建工单消息
        message = models.TicketMessage(
            ticket_id=ticket_id,
            user_id=user_id,
            message=request.message,
            is_admin=False
        )
        db.add(message)
        db.commit()
        return ticket_id

    ticket_id = await run_in_threadpool(_create)

    # 通知管理员有新工单（站内消息 + 实时推送）
    try:
        from backend.notifications import notify_staff_users

        await notify_staff_users(
            db,
            title="🎫 新工单待处理",
            content=f"{username} 提交了工单《{request.title}》\n{request.message[:120]}",
            message_type="ticket",
            related_id=ticket_id,
        )
    except Exception as exc:  # 通知失败不应影响工单创建
        logger.warning("工单管理员通知失败: %s", exc)

    return TicketCreateResponse(
        success=True,
        ticket_id=ticket_id,
        message="工单创建成功"
    )


@user_router.get("/tickets/{ticket_id}", response_model=TicketResponse)
def get_ticket_detail(
    ticket_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取工单详情"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id,
        models.Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    return TicketResponse(
        id=ticket.id,
        title=ticket.title,
        category=ticket.category,
        status=ticket.status,
        priority=ticket.priority,
        created_at=ticket.created_at.isoformat(),
        updated_at=ticket.updated_at.isoformat()
    )


@user_router.get("/tickets/{ticket_id}/messages", response_model=List[TicketMessageResponse])
def get_ticket_messages(
    ticket_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取工单消息列表"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id,
        models.Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    messages = db.query(models.TicketMessage).filter(
        models.TicketMessage.ticket_id == ticket_id
    ).order_by(models.TicketMessage.created_at.asc()).all()

    result = []
    for msg in messages:
        admin_name = None
        if msg.is_admin and msg.admin:
            admin_name = msg.admin.username

        result.append(TicketMessageResponse(
            id=msg.id,
            message=msg.message,
            is_admin=msg.is_admin,
            created_at=msg.created_at.isoformat(),
            admin_name=admin_name
        ))

    return result


@user_router.post("/tickets/{ticket_id}/messages")
async def reply_ticket(
    ticket_id: int,
    request: TicketReplyRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """回复工单（落库下放线程池；通知与刷新时间戳仍走原来的顺序）"""
    user_id = current_user.id
    username = current_user.username
    content = (request.message or "").strip()

    def _reply() -> dict:
        ticket = db.query(models.Ticket).filter(
            models.Ticket.id == ticket_id,
            models.Ticket.user_id == user_id
        ).first()

        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="工单不存在"
            )

        if ticket.status == "closed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="工单已关闭，无法回复"
            )

        if not content:
            raise HTTPException(status_code=400, detail="回复内容不能为空")
        if len(content) > 2000:
            raise HTTPException(status_code=400, detail="回复内容过长（最多 2000 字）")

        # 创建消息
        message = models.TicketMessage(
            ticket_id=ticket.id,
            user_id=user_id,
            message=content,
            is_admin=False
        )
        db.add(message)

        # 更新工单状态和时间
        ticket.status = "open"
        ticket.updated_at = datetime.now()

        db.commit()
        return {"ticket_id": ticket.id, "title": ticket.title}

    info = await run_in_threadpool(_reply)

    def _touch() -> None:
        """通知之后刷新一次时间戳（原来是拿同一个会话直接写，现在也在工作线程）"""
        row = db.query(models.Ticket).filter(models.Ticket.id == info["ticket_id"]).first()
        if row is not None:
            row.updated_at = datetime.now()
            db.commit()

    # 通知管理员（站内消息 + WebSocket 实时推送），与新建工单走同一链路
    try:
        from backend.notifications import notify_staff_users

        await notify_staff_users(
            db,
            title="💬 工单有新回复",
            content=f"{username} 在「{info['title']}」中回复：{content[:60]}",
            message_type="ticket",
            related_id=info["ticket_id"],
        )
        await run_in_threadpool(_touch)
    except Exception as exc:  # 通知失败不应影响回复本身
        logger.warning("工单回复通知发送失败: %s", exc)

    return {"success": True, "message": "回复成功"}


@user_router.post("/tickets/{ticket_id}/close")
def close_ticket(
    ticket_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """关闭工单"""
    ticket = db.query(models.Ticket).filter(
        models.Ticket.id == ticket_id,
        models.Ticket.user_id == current_user.id
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="工单不存在"
        )

    ticket.status = "closed"
    ticket.updated_at = datetime.now()
    db.commit()

    return {"success": True, "message": "工单已关闭"}


# ==================== 公告 API ====================

@user_router.get("/announcements", response_model=List[AnnouncementResponse])
def get_announcements(
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    """获取系统公告 - 与后台公告管理联动"""
    query = db.query(models.Announcement)

    if active_only:
        query = query.filter(models.Announcement.is_active == True)

    announcements = query.order_by(
        models.Announcement.is_pinned.desc(),
        models.Announcement.created_at.desc()
    ).limit(20).all()

    return [
        AnnouncementResponse(
            id=a.id,
            title=a.title,
            content=a.content,
            type=a.type,
            is_pinned=a.is_pinned,
            created_at=a.created_at.isoformat()
        )
        for a in announcements
    ]


# ==================== 求片 API ====================

# 每日求片上限（防止刷单），可在系统配置中通过 media_seek_daily_limit 覆盖
DEFAULT_DAILY_SEEK_LIMIT = 5

# 用户主动撤回的求片：不再展示、也不再参与去重，但仍计入当天的提交数
WITHDRAWN_STATUS = "withdrawn"


class MediaSeekRequest(BaseModel):
    """求片请求"""
    movie_name: str
    year: Optional[str] = None
    type: Optional[str] = None
    note: Optional[str] = None
    # 这部片要进哪个服的库（用户端会让他选/自动带出）；留空时后端自己推导
    realm_id: Optional[int] = None


def _resolve_seek_realm(db: Session, user: models.WebUser,
                        requested: Optional[int] = None) -> Optional[int]:
    """求片登记给哪个服

    - 用户明确选了服：校验存在后用它；
    - 没选：只看得到一个服的会员就默认这个服（大多数用户不用做选择）；
    - 持有多个服或多个都看不清：留空（``NULL``）——「未标注」是诚实的结果，
      不替用户猜一个服，后台也看得出来这条没定。
    """
    if requested is not None:
        if not realms.get_realm(db, requested):
            raise HTTPException(status_code=400, detail=f"服不存在: #{requested}")
        return int(requested)

    now = datetime.now()
    rows = (db.query(models.UserSubscription.realm_id)
            .filter(
                models.UserSubscription.user_id == user.id,
                models.UserSubscription.status == "active",
                models.UserSubscription.end_date > now,
                models.UserSubscription.realm_id.isnot(None),
            )
            .all())
    realms_held = {int(r[0]) for r in rows if r[0]}
    if len(realms_held) == 1:
        return realms_held.pop()
    return None


def _seek_daily_limit(db: Session) -> int:
    cfg = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == "media_seek_daily_limit"
    ).first()
    if cfg and str(cfg.value).isdigit():
        return max(1, int(cfg.value))
    return DEFAULT_DAILY_SEEK_LIMIT


@user_router.get("/media-seek/lookup")
def lookup_media(
    name: str,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """求片前库存检查：片名是否已在自建媒体库中

    返回命中的库内条目（含海报与详页 id），用于：
    - 已在库 → 直接引导播放，不占用求片额度
    - 未在库 → 前端提示可提交求片
    """
    from backend.emby_server import models as em

    keyword = (name or "").strip()
    if len(keyword) < 1:
        return {"in_library": False, "items": []}

    items = (
        db.query(em.MediaItem)
        .filter(em.MediaItem.name.ilike(f"%{keyword}%"))
        .order_by(em.MediaItem.date_added.desc())
        .limit(6)
        .all()
    )

    return {
        "in_library": len(items) > 0,
        "items": [
            {
                "id": i.guid,
                "name": i.name,
                "type": i.item_type,
                "year": i.production_year,
                "poster_url": f"/emby/Items/{i.guid}/Images/Primary"
                if (i.poster_path or i.primary_image_url) else None,
            }
            for i in items
        ],
    }


def _create_media_seek_sync(
    db: Session,
    user: models.WebUser,
    name: str,
    request: "MediaSeekRequest",
) -> int:
    """同步落库：去重 / 每日额度 / 写入求片（整段放在线程池里跑，见 create_media_seek）

    校验失败照原样抛 HTTPException——线程里抛出的异常会由 await 处原样抛给客户端，
    状态码与文案和以前一致（400 / 409 / 429 的语义没有变）。
    """
    # 去重：同名且仍在处理中的请求不再重复提交（已撤回的不算「在处理中」，可以重新求）
    exists = db.query(models.MovieRequest).filter(
        models.MovieRequest.user_id == user.id,
        func.lower(models.MovieRequest.movie_name) == name.lower(),
        models.MovieRequest.status.in_(["pending", "approved"]),
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail=f"《{name}》已在处理中，请耐心等待（可在列表中看到进度）")

    # 每日额度：统计**今天提交过多少条**（含后来撤回的）。
    # 撤回不退还额度——否则「提交 → 撤回 → 再提交」可以无限刷新额度，
    # 同时每次提交都会给全体管理员推一条站内消息，那就成了通知刷屏器。
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.query(models.MovieRequest).filter(
        models.MovieRequest.user_id == user.id,
        models.MovieRequest.created_at >= today_start,
    ).count()
    limit = _seek_daily_limit(db)
    if today_count >= limit:
        raise HTTPException(status_code=429, detail=f"今日求片已达上限（{limit} 条），请明天再提交")

    media_request = models.MovieRequest(
        user_id=user.id,
        movie_name=name,
        year=request.year,
        type=request.type,
        note=request.note,
        status="pending",
        # 求片是「给哪个服求」的：用户选/单服自动带出，读不出就未标注
        realm_id=_resolve_seek_realm(db, user, request.realm_id),
    )
    db.add(media_request)
    db.commit()
    db.refresh(media_request)
    return media_request.id


@user_router.post("/media-seek")
async def create_media_seek(
    request: MediaSeekRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建求片请求 - 与后台求片管理联动

    校验：片名非空 / 同名未完成请求去重 / 每日额度上限。
    """
    name = (request.movie_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写片名")
    if len(name) > 255:
        raise HTTPException(status_code=400, detail="片名过长")

    # 去重 / 额度 / 落库整段下放线程池：同步 SQLAlchemy 跑在事件循环上时，
    # 卡住的是**所有人**的请求（求片页是用户会连着点的地方）。
    request_id = await run_in_threadpool(
        _create_media_seek_sync, db, current_user, name, request
    )

    # 通知管理员有新求片请求（落站内消息 + WebSocket 推送）
    try:
        from backend.notifications import notify_staff_users

        await notify_staff_users(
            db,
            title="📥 新的求片请求",
            content=f"{current_user.username} 请求《{name}》",
            message_type="media_seek",
            related_id=request_id,
        )
    except Exception as exc:  # 通知失败不应影响求片提交
        logger.warning("求片通知发送失败: %s", exc)

    return {"success": True, "request_id": request_id, "message": "求片请求已提交"}


@user_router.delete("/media-seek/{request_id}")
def withdraw_media_seek(
    request_id: int,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """撤回自己的求片（仅限尚未被处理的请求）

    撤回是**改状态**（``withdrawn``）而不是删行：用户列表里不再出现它，
    但今天的提交数依然算得进去（见 create_media_seek 里的额度说明）。
    删行会让额度被无限刷新，也会让后台的审计记录凭空少一条。
    """
    req = db.query(models.MovieRequest).filter(
        models.MovieRequest.id == request_id,
        models.MovieRequest.user_id == current_user.id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="求片记录不存在")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="该请求已被处理，无法撤回")

    req.status = WITHDRAWN_STATUS
    req.updated_at = datetime.now()
    db.commit()
    return {"success": True, "message": "已撤回"}


@user_router.get("/media-seek")
def get_my_media_seeks(
    status_filter: Optional[str] = None,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取我的求片列表（支持状态筛选），并附带今日剩余额度

    主动撤回的条目不再列出来（用户看不到自己已经撤销的东西才符合直觉），
    但额度仍按今天的提交总数算。
    """
    query = db.query(models.MovieRequest).filter(
        models.MovieRequest.user_id == current_user.id,
        models.MovieRequest.status != WITHDRAWN_STATUS,
    )
    if status_filter:
        query = query.filter(models.MovieRequest.status == status_filter)

    requests = query.order_by(models.MovieRequest.created_at.desc()).limit(200).all()
    realm_names = {r.id: r.name for r in realms.list_realms(db)}

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.query(models.MovieRequest).filter(
        models.MovieRequest.user_id == current_user.id,
        models.MovieRequest.created_at >= today_start,
    ).count()
    limit = _seek_daily_limit(db)

    return {
        "requests": [
            {
                "id": r.id,
                "movie_name": r.movie_name,
                "year": r.year,
                "type": r.type,
                "note": r.note,
                "status": r.status,
                "admin_note": r.admin_note,
                # 这部片求给哪个服（用户自己就能看到，不用问管理员）
                "realm_id": r.realm_id,
                "realm_name": realm_names.get(r.realm_id, "") if r.realm_id else "",
                "created_at": r.created_at.isoformat()
            }
            for r in requests
        ],
        "quota": {"used_today": used, "daily_limit": limit, "remaining": max(0, limit - used)},
    }


# ==================== 订阅 API ====================

@user_router.get("/subscriptions")
def get_my_subscriptions(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取我的订阅列表 - 与后台订阅管理联动

    生效状态按 end_date 现算（status 字段不会随时间自动翻转），
    与后台订阅总览 / 用户 VIP 派生使用同一口径。
    """
    subscriptions = db.query(models.UserSubscription).filter(
        models.UserSubscription.user_id == current_user.id
    ).order_by(models.UserSubscription.created_at.desc()).all()

    now = datetime.now()
    plans = {
        p.id: p for p in db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id.in_([s.plan_id for s in subscriptions if s.plan_id])
        ).all()
    } if subscriptions else {}
    realm_names = {r.id: r.name for r in realms.list_realms(db)}

    result = []
    for sub in subscriptions:
        plan = plans.get(sub.plan_id)
        is_current = bool(
            sub.status == "active" and sub.end_date and sub.end_date > now
        )
        result.append({
            "id": sub.id,
            "plan_name": plan.name if plan else "未知套餐",
            # 会员属于哪个服：多服运营下用户会同时持有多个服的会员，必须分开看
            "realm_id": sub.realm_id,
            "realm_name": realm_names.get(sub.realm_id, "") if sub.realm_id else "",
            "start_date": sub.start_date.isoformat() if sub.start_date else None,
            "end_date": sub.end_date.isoformat() if sub.end_date else None,
            "status": "active" if is_current else "expired",
            "is_current": is_current,
            "auto_renew": sub.auto_renew,
            "days_left": max(0, (sub.end_date - now).days) if sub.end_date else 0,
        })

    return result


@user_router.get("/subscription-plans")
def get_subscription_plans(
    realm_id: int | None = None,
    db: Session = Depends(get_db)
):
    """获取可用订阅套餐 - 与后台套餐管理联动

    套餐是一个服一个的：默认只列当前服（``realm_id=0`` 列全部服），
    带着所属服的名称，用户端才能说清“这是哪个服的会员”。
    """
    scope_id = None if realm_id == 0 else (realm_id or realms.active_realm_id(db))
    query = realms.scope(db.query(models.SubscriptionPlan),
                         models.SubscriptionPlan.realm_id, scope_id)
    plans = query.filter(
        models.SubscriptionPlan.is_active == True
    ).order_by(models.SubscriptionPlan.sort_order).all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": float(p.price),
            "duration_days": p.duration_days,
            "features": p.features,
            "is_popular": p.is_popular,
            "realm_id": p.realm_id,
            "realm_name": (p.realm.name if p.realm else ""),
        }
        for p in plans
    ]


# ==================== 会员卡码核销 ====================


class RedeemCodeRequest(BaseModel):
    code: str


@user_router.post("/membership/redeem/preview")
async def preview_membership_code(
    req: RedeemCodeRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """预检卡码：不核销，仅告知类型与天数

    用 POST 而非 GET，避免卡码出现在访问日志与浏览器历史中；
    限速与核销同口径，防止靠枚举探测卡码。
    """
    allowed, _ = check_rate_limit(f"code_preview:{current_user.id}", 20, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")

    return codes.preview_code(db, req.code, current_user.username)


@user_router.post("/membership/redeem")
def redeem_membership_code(
    req: RedeemCodeRequest,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """核销会员卡码：注册码 / 续期码 / 白名单码

    同步 `def`：整条链路（限速 / 查码 / 原子占位 / 发天数 / 提交）都是同步 SQLAlchemy，
    没有一个 await。留成 `async def` 就是让占位与发天数的那段写库压在事件循环上
    （见 docs/performance.md 的「事务范围」与 check_blocking_routes 的说明）。
    """
    allowed, _ = check_rate_limit(f"code_redeem:{current_user.id}", 10, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")

    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    result = codes.redeem_code(db, current_user, req.code)
    if not result.get("success"):
        # 失败路径要把事务收干净：redeem_code 里可能已经动过会话（占位 / 封禁），
        # 不回滚就交给 get_db 的 close() 会让错误更难查
        db.rollback()
        raise HTTPException(status_code=400, detail=result.get("message") or "卡码无效")
    # 卡码消耗与会员天数由这里统一提交（codes 里不再自己 commit）：
    # 两阶段提交不一致会导致「码烧了、会员没到账」或反过来（见 backend/codes.py 的说明）
    commit_with_retry(db, label="卡码核销")
    return result


# ==================== 我的设备（播放器） ====================


@user_router.get("/emby/devices")
async def get_my_devices(
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的播放设备：用于查看已在哪些客户端登录，并清理不再使用的设备"""
    now = datetime.now()
    cutoff = now - timedelta(days=devices.ACTIVE_DEVICE_DAYS)
    rows = devices.list_devices(db, current_user.id)

    items = []
    for device in rows:
        dto = devices.device_dto(device)
        dto["is_online_recent"] = bool(
            not device.is_blocked
            and (device.last_seen_at is None or device.last_seen_at >= cutoff)
        )
        items.append(dto)

    limit = devices.device_limit(db)
    active_count = sum(1 for d in items if d["is_online_recent"])
    return {
        "limit": limit,
        "count": len(items),
        "active_count": active_count,
        "remaining": max(0, limit - active_count) if limit else None,
        "auto_evict": devices.device_auto_evict(db),
        "active_days": devices.ACTIVE_DEVICE_DAYS,
        "devices": items,
    }


@user_router.delete("/emby/devices/{device_id}")
async def remove_my_device(
    device_id: str,
    current_user: models.WebUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """移除设备并吊销其令牌（对应客户端需重新登录）"""
    ok = devices.remove_device(db, current_user.id, device_id, revoke_tokens=True)
    if not ok:
        raise HTTPException(status_code=404, detail="设备不存在")
    return {"success": True, "message": "设备已移除，对应客户端需重新登录"}


# ==================== 已移除的遗留端点 ====================
#
# 以下端点已于 v2.5.0 删除，它们读取的是「外部 Emby 服务器」时代的遗留模型
# （models.EmbyServer / models.UserEmbyAccount）：统一后端已完全自建（/api/user/emby/*），
# 这两张表不再有任何写入方，接口只会返回空数据，容易误导调用方。
#   - GET /api/user/emby-servers
#   - GET /api/user/emby-account


# ==================== 导出 ====================

__all__ = ["user_router"]
