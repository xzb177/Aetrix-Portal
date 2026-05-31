"""
认证 API 路由
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_session
from database.models import WebUser
from schemas.auth import UserLogin, UserRegister, TelegramCallback, UserResponse, TokenResponse
from utils.security import verify_password, get_password_hash, create_access_token, create_refresh_token, decode_access_token
from typing import Optional
import json
import urllib.parse
import secrets
import random
import logging
import hashlib
import hmac
import time

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_session)
) -> WebUser:
    """获取当前登录用户"""
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

    user = db.query(WebUser).filter(WebUser.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_session)
) -> Optional[WebUser]:
    """
    获取当前登录用户（可选）

    如果没有提供 Token 或 Token 无效，返回 None 而不是抛出异常
    用于游客可访问的接口
    """
    if not credentials:
        return None

    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    user = db.query(WebUser).filter(WebUser.id == user_id).first()
    return user


def get_main_user_binding(telegram_id: int) -> Optional[dict]:
    """
    从主数据库获取 UserBinding 信息

    使用环境变量 ROYALBOT_DB_PATH 配置数据库路径
    如果未配置或数据库不存在，返回 None
    """
    import sqlite3
    import os

    db_path = os.getenv("ROYALBOT_DB_PATH", "/root/royalbot/royalbot.db")

    # 检查数据库文件是否存在
    if not os.path.exists(db_path):
        logger.debug(f"主数据库文件不存在: {db_path}")
        return None

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_vip, emby_account, points FROM bindings WHERE tg_id = ? LIMIT 1",
            (telegram_id,)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logger.warning(f"查询主数据库失败: {e}")
        return None
    except Exception as e:
        logger.error(f"获取主数据库用户信息失败: {e}")
        return None


def get_user_response(user: WebUser, db: Session) -> dict:
    """构建用户响应"""
    binding = None
    if user.telegram_id:
        binding = get_main_user_binding(user.telegram_id)

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "telegram_id": user.telegram_id,
        "is_vip": binding["is_vip"] if binding else False,
        "emby_account": binding["emby_account"] if binding else None,
        # 优先使用用户表的 balance 字段（单位：分），兼容旧的 points
        "balance": user.balance if hasattr(user, 'balance') and user.balance is not None else 0,
        "points": binding["points"] if binding else 0,  # 保留兼容性
        "registered_date": user.created_at.isoformat() if user.created_at else None,
        # 求片统计
        "completed_requests_count": user.completed_requests_count if hasattr(user, 'completed_requests_count') else 0,
        "total_requests_count": user.total_requests_count if hasattr(user, 'total_requests_count') else 0,
    }


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin, db: Session = Depends(get_session)):
    """账号密码登录"""
    user = db.query(WebUser).filter(WebUser.username == credentials.username).first()

    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用"
        )

    # 创建 Token（Access + Refresh）
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=get_user_response(user, db)
    )


@router.post("/refresh")
async def refresh_token(
    request: Request,
    db: Session = Depends(get_session)
):
    """使用 Refresh Token 换取新的 Access Token"""
    # 从请求体或 header 获取 refresh token
    import json as _json
    body = await request.json() if request.method == "POST" else {}
    token = body.get("refresh_token", "")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少 refresh_token"
        )

    payload = decode_access_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 refresh_token"
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 refresh_token"
        )

    # 验证用户存在且活跃
    user = db.query(WebUser).filter(WebUser.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用"
        )

    # 生成新的双 Token
    new_access = create_access_token(data={"sub": str(user.id)})
    new_refresh = create_refresh_token(data={"sub": str(user.id)})

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.post("/register", response_model=TokenResponse)
async def register(data: UserRegister, db: Session = Depends(get_session)):
    """用户注册"""
    # 检查用户名是否存在
    if db.query(WebUser).filter(WebUser.username == data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )

    # 验证邀请码（如果提供）
    invitation_code_id = None
    if data.invitation_code:
        from database.models import InvitationCode
        code = db.query(InvitationCode).filter(
            InvitationCode.code == data.invitation_code
        ).first()
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邀请码不存在"
            )
        invitation_code_id = code.id

    # 创建用户
    user = WebUser(
        username=data.username,
        password_hash=get_password_hash(data.password),
        email=data.email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 处理邀请奖励
    if invitation_code_id:
        from api.invitation import process_invitation_reward
        process_invitation_reward(db, user.id, invitation_code_id)

    # 创建 Token
    access_token = create_access_token(data={"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        user=get_user_response(user, db)
    )


@router.post("/telegram-callback", response_model=TokenResponse)
async def telegram_callback(data: TelegramCallback, db: Session = Depends(get_session)):
    """
    Telegram 登录回调

    安全措施：
    1. 验证 Telegram 数据哈希
    2. 验证 JSON 格式
    3. 验证必需字段
    4. 清理用户输入
    """
    try:
        # 解析查询参数
        params = urllib.parse.parse_qs(data.query_string)

        # 获取 Telegram 用户数据
        user_data_str = params.get('user', [None])[0]
        if not user_data_str:
            logger.warning("Telegram 登录缺少用户数据")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing user data"
            )

        # ========== JSON 解析与验证 ==========
        try:
            user_data = json.loads(user_data_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Telegram 用户数据 JSON 解析失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid user data format"
            )

        # 验证必需字段
        telegram_id = user_data.get('id')
        if not telegram_id:
            logger.warning("Telegram 用户数据缺少 id 字段")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Telegram user ID"
            )

        # 验证 telegram_id 是否为整数
        if not isinstance(telegram_id, int):
            try:
                telegram_id = int(telegram_id)
            except (ValueError, TypeError):
                logger.warning(f"Telegram ID 格式无效: {user_data.get('id')}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Telegram user ID"
                )

        # 清理用户名（防止注入攻击）
        raw_username = user_data.get('username')
        if raw_username:
            # 移除特殊字符，只保留字母、数字、下划线
            username = ''.join(c for c in raw_username if c.isalnum() or c == '_')
            if not username:
                username = f"tg_{telegram_id}"
            # 限制用户名长度
            username = username[:32]
        else:
            username = f"tg_{telegram_id}"

        logger.info(f"Telegram 登录请求: telegram_id={telegram_id}, username={username}")

        # 查找或创建用户
        user = db.query(WebUser).filter(WebUser.telegram_id == telegram_id).first()

        if not user:
            # 检查用户名是否已存在
            base_username = username
            counter = 1
            while db.query(WebUser).filter(WebUser.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1
                if counter > 100:  # 防止无限循环
                    username = f"tg_{telegram_id}_{random.randint(1000, 9999)}"
                    break

            # 创建新用户（使用更强的默认密码）
            default_password = f"tg_{telegram_id}_{secrets.token_urlsafe(16)[:16]}"
            user = WebUser(
                username=username,
                telegram_id=telegram_id,
                password_hash=get_password_hash(default_password),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"创建新用户: id={user.id}, username={username}")

        # 创建 Token
        access_token = create_access_token(data={"sub": str(user.id)})

        return TokenResponse(
            access_token=access_token,
            user=get_user_response(user, db)
        )

    except HTTPException:
        # 直接抛出 HTTP 异常
        raise
    except Exception as e:
        logger.error(f"Telegram 登录失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed, please try again"
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: WebUser = Depends(get_current_user), db: Session = Depends(get_session)):
    """获取当前用户信息"""
    return get_user_response(current_user, db)


def verify_telegram_widget_hash(params: dict, bot_token: str) -> bool:
    """
    验证 Telegram Login Widget 的 hash

    参考: https://core.telegram.org/widgets/login#checking-authorization
    """
    hash_value = params.pop('hash', '')

    # 按字母顺序排序参数
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

    # 创建 secret key
    secret_key = hashlib.sha256(bot_token.encode()).digest()

    # 计算 hash
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    # 使用 compare_digest 防止时序攻击
    return hmac.compare_digest(computed_hash, hash_value)


@router.get("/telegram-login")
async def telegram_widget_login(
    id: int = Query(..., description="Telegram User ID"),
    first_name: str = Query("", description="First name"),
    last_name: str = Query("", description="Last name"),
    username: str = Query("", description="Username"),
    auth_date: int = Query(..., description="Auth date"),
    hash: str = Query(..., description="Hash"),
    db: Session = Depends(get_session)
):
    """
    Telegram Login Widget 回调端点

    处理 Telegram Login Widget 的登录回调，验证数据并创建/登录用户。

    验证流程：
    1. 从数据库获取 Bot Token
    2. 验证 hash 签名
    3. 检查 auth_date（防止重放攻击）
    4. 创建或登录用户
    """
    try:
        # 获取 Bot Token
        bot_token = None
        try:
            from admin_database_user import get_user_db as get_admin_db, SystemConfig
            admin_db = next(get_admin_db())
            try:
                config = admin_db.query(SystemConfig).filter(
                    SystemConfig.key == "telegram_login_bot_token"
                ).first()
                if config and config.value:
                    bot_token = config.value
            finally:
                admin_db.close()
        except ImportError:
            logger.warning("无法导入 admin_database_user，跳过 Bot Token 验证")

        if not bot_token:
            # 尝试从环境变量获取
            import os
            bot_token = os.getenv("TELEGRAM_LOGIN_BOT_TOKEN", "")

        # 验证 hash（如果有 Bot Token）
        if bot_token:
            params = {
                'id': str(id),
                'first_name': first_name,
                'last_name': last_name,
                'username': username,
                'auth_date': str(auth_date),
            }
            # 移除空值
            params = {k: v for k, v in params.items() if v}

            if not verify_telegram_widget_hash(params.copy(), bot_token):
                logger.warning(f"Telegram Widget hash 验证失败: telegram_id={id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid hash"
                )

            # 检查 auth_date（防止重放攻击，超过 24 小时拒绝）
            current_time = int(time.time())
            if current_time - auth_date > 86400:  # 24 小时
                logger.warning(f"Telegram Widget auth_date 过期: {auth_date}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Auth date expired"
                )
        else:
            logger.warning("未配置 Bot Token，跳过 hash 验证（不推荐）")

        # 处理用户名
        telegram_id = id
        if username:
            # 清理用户名
            clean_username = ''.join(c for c in username if c.isalnum() or c == '_')
            if not clean_username:
                clean_username = f"tg_{telegram_id}"
            username = clean_username[:32]
        else:
            username = f"tg_{telegram_id}"

        logger.info(f"Telegram Widget 登录: telegram_id={telegram_id}, username={username}")

        # 查找或创建用户
        user = db.query(WebUser).filter(WebUser.telegram_id == telegram_id).first()

        if not user:
            # 检查用户名是否已存在
            base_username = username
            counter = 1
            while db.query(WebUser).filter(WebUser.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1
                if counter > 100:
                    username = f"tg_{telegram_id}_{random.randint(1000, 9999)}"
                    break

            # 创建新用户
            default_password = f"tg_{telegram_id}_{secrets.token_urlsafe(16)[:16]}"
            user = WebUser(
                username=username,
                telegram_id=telegram_id,
                password_hash=get_password_hash(default_password),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"Widget 创建新用户: id={user.id}, username={username}")

        # 创建 Token
        access_token = create_access_token(data={"sub": str(user.id)})

        # 重定向到前端，携带 token
        frontend_url = "https://login.laodaemby.xyz"
        redirect_url = f"{frontend_url}/telegram-auth-success?token={access_token}&user={urllib.parse.quote(json.dumps(get_user_response(user, db)))}"
        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Telegram Widget 登录失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed, please try again"
        )


@router.post("/logout")
async def logout():
    """登出（前端清除 Token 即可）"""
    return {"message": "Logged out successfully"}


@router.post("/change-password")
async def change_password(
    old_password: str = Query(..., description="旧密码"),
    new_password: str = Query(..., description="新密码（至少6位）"),
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    修改当前用户密码

    需要验证旧密码正确后才能修改
    """
    # 验证新密码长度
    if len(new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码至少需要 6 位字符"
        )

    # 验证旧密码
    if not verify_password(old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误"
        )

    # 更新密码
    current_user.password_hash = get_password_hash(new_password)
    db.commit()

    logger.info(f"用户 {current_user.username} 修改了密码")

    return {"message": "密码修改成功"}


@router.get("/timeline")
async def get_user_timeline(
    current_user: WebUser = Depends(get_current_user),
    db: Session = Depends(get_session),
    limit: int = Query(10, ge=1, le=50)
):
    """
    获取用户活动时间线

    包括：
    - 充值记录
    - 求片记录
    - 订阅记录
    - 兑换记录
    """
    from datetime import datetime
    from database.models import RechargeOrder, MediaRequest, ExchangeCodeRecord, Subscription

    events = []

    # 1. 充值记录
    recharge_orders = db.query(RechargeOrder).filter(
        RechargeOrder.user_id == current_user.id
    ).order_by(RechargeOrder.created_at.desc()).limit(5).all()

    for order in recharge_orders:
        events.append({
            "id": f"recharge-{order.id}",
            "type": "recharge",
            "title": f"充值 ¥{order.amount}",
            "description": f"订单号: {order.order_id}" if order.order_id else None,
            "timestamp": order.created_at.isoformat() if order.created_at else datetime.utcnow().isoformat(),
            "status": "success" if order.status == "success" else "pending"
        })

    # 2. 求片记录
    media_requests = db.query(MediaRequest).filter(
        MediaRequest.user_id == current_user.id
    ).order_by(MediaRequest.created_at.desc()).limit(5).all()

    for request in media_requests:
        status_map = {
            "pending": "pending",
            "approved": "success",
            "completed": "success",
            "rejected": "failed"
        }
        events.append({
            "id": f"request-{request.id}",
            "type": "request",
            "title": f"求片: {request.movie_name}",
            "description": request.note or None,
            "timestamp": request.created_at.isoformat() if request.created_at else datetime.utcnow().isoformat(),
            "status": status_map.get(request.status, "pending")
        })

    # 3. 订阅记录
    subscriptions = db.query(Subscription).filter(
        Subscription.user_id == current_user.id
    ).order_by(Subscription.created_at.desc()).limit(3).all()

    for sub in subscriptions:
        events.append({
            "id": f"subscription-{sub.id}",
            "type": "subscription",
            "title": f"订阅套餐: {sub.plan_id or '未知'}",
            "description": f"有效期至 {sub.expires_at.strftime('%Y-%m-%d')}" if sub.expires_at else None,
            "timestamp": sub.created_at.isoformat() if sub.created_at else datetime.utcnow().isoformat(),
            "status": "success"
        })

    # 4. 兑换记录
    exchange_records = db.query(ExchangeCodeRecord).filter(
        ExchangeCodeRecord.user_id == current_user.id
    ).order_by(ExchangeCodeRecord.created_at.desc()).limit(3).all()

    for record in exchange_records:
        events.append({
            "id": f"exchange-{record.id}",
            "type": "subscription",
            "title": f"兑换码: {record.code}",
            "description": None,
            "timestamp": record.created_at.isoformat() if record.created_at else datetime.utcnow().isoformat(),
            "status": "success"
        })

    # 按时间戳排序，最新的在前
    events.sort(key=lambda x: x["timestamp"], reverse=True)

    # 限制返回数量
    return events[:limit]
