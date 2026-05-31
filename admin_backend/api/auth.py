"""
认证相关 API - 安全增强版
"""
import re
import secrets
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from admin_database import get_db, AdminUser
from admin_utils.models_loader import AdminLog
from schemas.auth import LoginRequest, LoginResponse, AdminInfo, ChangePasswordRequest
from schemas.common import Response
from admin_utils.auth import verify_password, create_access_token, get_password_hash, get_current_admin
from admin_utils.config import settings

router = APIRouter()

# 登录失败跟踪（Redis 存储，支持多实例）
import json as _json

_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=3,
                socket_connect_timeout=3,
            )
            _redis_client.ping()
        except Exception:
            _redis_client = None
    return _redis_client


def get_client_ip(request: Request) -> str:
    """获取客户端真实IP"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_account_locked(username: str) -> tuple[bool, int]:
    """检查账号是否被锁定"""
    r = _get_redis()
    if not r:
        return False, 0
    lock_until = r.get(f"admin_lock:{username}")
    if lock_until:
        try:
            lock_time = datetime.fromisoformat(lock_until)
            if datetime.now() < lock_time:
                return True, int((lock_time - datetime.now()).total_seconds())
            else:
                r.delete(f"admin_lock:{username}")
        except Exception:
            r.delete(f"admin_lock:{username}")
    return False, 0


def record_failed_attempt(ip: str, username: str):
    """记录登录失败尝试"""
    r = _get_redis()
    if not r:
        return
    key = f"admin_attempts:{ip}:{username}"
    now = datetime.now().isoformat()
    r.lpush(key, now)
    r.ltrim(key, 0, 19)  # 保留最近20条
    r.expire(key, 900)    # 15分钟过期

    # 统计最近15分钟的失败次数
    records = r.lrange(key, 0, 19)
    cutoff = datetime.now() - timedelta(minutes=15)
    count = sum(1 for r_str in records if datetime.fromisoformat(r_str) > cutoff)

    if count >= settings.MAX_LOGIN_ATTEMPTS:
        lock_until = datetime.now() + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
        r.set(f"admin_lock:{username}", lock_until.isoformat(),
              ex=settings.LOCKOUT_DURATION_MINUTES * 60)


def clear_failed_attempts(ip: str, username: str):
    """清除失败尝试记录（登录成功后）"""
    r = _get_redis()
    if not r:
        return
    r.delete(f"admin_attempts:{ip}:{username}")


def validate_password_complexity(password: str) -> tuple[bool, str]:
    """验证密码复杂度"""
    if len(password) < settings.MIN_PASSWORD_LENGTH:
        return False, f"密码长度不能少于{settings.MIN_PASSWORD_LENGTH}位"

    if settings.REQUIRE_PASSWORD_COMPLEXITY:
        # 检查是否包含至少一个大写字母
        if not re.search(r'[A-Z]', password):
            return False, "密码必须包含至少一个大写字母"

        # 检查是否包含至少一个小写字母
        if not re.search(r'[a-z]', password):
            return False, "密码必须包含至少一个小写字母"

        # 检查是否包含至少一个数字
        if not re.search(r'\d', password):
            return False, "密码必须包含至少一个数字"

        # 检查是否包含至少一个特殊字符
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:"\\|,.<>?]', password):
            return False, "密码必须包含至少一个特殊字符"

    # 检查常见弱密码
    common_passwords = [
        "password", "12345678", "abcdefgh", "qwerty123",
        "admin123", "letmein", "welcome1"
    ]
    if password.lower() in common_passwords:
        return False, "密码过于常见，请使用更复杂的密码"

    return True, ""


def sanitize_log_value(value: str) -> str:
    """脱敏日志中的敏感值"""
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


@router.post("/login")
async def login(
    credentials: LoginRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """管理员登录 - 安全增强版"""
    client_ip = get_client_ip(request)

    # 检查账号是否被锁定
    is_locked, remaining_seconds = is_account_locked(credentials.username)
    if is_locked:
        # 记录锁定期间的登录尝试
        log = AdminLog(
            admin_id=None,
            admin_username=credentials.username,
            action="login_attempt_locked",
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            details={"message": "账号已锁定，尝试登录", "ip": client_ip},
        )
        db.add(log)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"账号已被锁定，请在{remaining_seconds // 60}分钟后重试",
        )

    # 查找管理员
    admin = db.query(AdminUser).filter(
        AdminUser.username == credentials.username
    ).first()

    # 验证密码（无论用户是否存在都进行相同的验证，防止用户枚举）
    password_correct = False
    if admin:
        # 调试：检查密码哈希是否存在
        if not admin.password_hash:
            print(f"[登录调试] 用户 {credentials.username} 的密码哈希为空！")
        else:
            # 尝试验证密码
            password_correct = verify_password(credentials.password, admin.password_hash)
            print(f"[登录调试] 用户 {credentials.username} 密码验证: {password_correct}")

    if not admin or not password_correct:
        # 记录失败尝试
        record_failed_attempt(client_ip, credentials.username)

        # 记录失败日志
        log = AdminLog(
            admin_id=admin.id if admin else None,
            admin_username=credentials.username,
            action="login_failed",
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            details={"message": "登录失败", "ip": client_ip},
        )
        db.add(log)
        db.commit()

        # 不泄露具体错误信息（用户是否存在、密码是否正确）
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    # 检查账号状态
    if not admin.is_active:
        log = AdminLog(
            admin_id=admin.id,
            admin_username=admin.username,
            action="login_disabled",
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
        db.add(log)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    # 清除失败尝试记录
    clear_failed_attempts(client_ip, credentials.username)

    # 更新最后登录时间
    admin.last_login = datetime.now()

    # 记录登录日志
    log = AdminLog(
        admin_id=admin.id,
        admin_username=admin.username,
        action="login_success",
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    # 生成访问令牌
    access_token = create_access_token(data={"sub": str(admin.id)})

    # 生成 CSRF token
    csrf_token = secrets.token_urlsafe(32)

    # 获取权限
    from admin_utils.models_loader import Permission
    permissions = Permission.get_permissions(admin.role)

    # 生成会话ID用于额外的会话跟踪
    session_id = secrets.token_urlsafe(16)

    # 构建响应数据
    response_data = {
        "code": 200,
        "message": "登录成功",
        "data": {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "admin_info": {
                "id": admin.id,
                "username": admin.username,
                "role": admin.role,
                "role_display": admin.role.replace("_", " ").title(),
                "permissions": permissions,
                "is_active": admin.is_active,
                "last_login": admin.last_login.isoformat() if admin.last_login else None,
            },
            "csrf_token": csrf_token,
        }
    }

    # 如果启用 Cookie 认证，设置 httpOnly Cookie
    if getattr(settings, 'ENABLE_COOKIE_AUTH', True):
        max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        cookie_domain = getattr(settings, 'COOKIE_DOMAIN', None)

        resp = JSONResponse(content=response_data)

        # 根据请求协议决定是否使用 secure 标志
        # 检查 X-Forwarded-Proto 或 X-Real-Proto 头（Nginx 代理）
        proto = request.headers.get("X-Forwarded-Proto",
                request.headers.get("X-Real-Proto", "http"))
        is_secure = proto.lower() == "https"

        # 设置访问令牌 cookie (httpOnly - 防止 XSS 窃取)
        resp.set_cookie(
            key="admin_access_token",
            value=access_token,
            max_age=max_age,
            path="/",
            domain=cookie_domain,
            secure=is_secure,  # 根据协议动态设置
            httponly=True,  # 防止 JavaScript 访问
            samesite="lax",  # 防止 CSRF
        )

        # 设置 CSRF token cookie (非 httpOnly - 前端需要读取)
        resp.set_cookie(
            key="admin_csrf_token",
            value=csrf_token,
            max_age=max_age,
            path="/",
            domain=cookie_domain,
            secure=is_secure,  # 根据协议动态设置
            httponly=False,  # 前端需要读取
            samesite="lax",
        )

        return resp

    return JSONResponse(content=response_data)


@router.get("/me", response_model=Response[AdminInfo])
async def get_current_admin_info(
    request: Request,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取当前管理员信息"""
    from admin_utils.models_loader import Permission
    permissions = Permission.get_permissions(current_admin.role)

    # 检查会话是否超时
    if current_admin.last_login:
        session_age = datetime.now() - current_admin.last_login
        if session_age > timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES):
            # 会话超时，需要重新登录
            log = AdminLog(
                admin_id=current_admin.id,
                admin_username=current_admin.username,
                action="session_expired",
                ip_address=get_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            db.add(log)
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="会话已过期，请重新登录",
            )

    return Response(data=AdminInfo(
        id=current_admin.id,
        username=current_admin.username,
        role=current_admin.role,
        role_display=current_admin.role.replace("_", " ").title(),
        permissions=permissions,
        is_active=current_admin.is_active,
        last_login=current_admin.last_login.isoformat() if current_admin.last_login else None,
    ))


@router.post("/change-password", response_model=Response[dict])
async def change_password(
    data: ChangePasswordRequest,
    request: Request,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """修改密码 - 带复杂度验证"""
    # 验证旧密码
    if not verify_password(data.old_password, current_admin.password_hash):
        log = AdminLog(
            admin_id=current_admin.id,
            admin_username=current_admin.username,
            action="change_password_failed",
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            details={"message": "旧密码验证失败"},
        )
        db.add(log)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误",
        )

    # 验证新密码复杂度
    is_valid, error_msg = validate_password_complexity(data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # 检查新密码是否与旧密码相同
    if data.old_password == data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与旧密码相同",
        )

    # 更新密码
    current_admin.password_hash = get_password_hash(data.new_password)
    current_admin.updated_at = datetime.now()

    # 记录操作日志（不记录密码）
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="change_password_success",
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "密码修改成功"})


@router.post("/logout")
async def logout(
    request: Request,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """登出"""
    # 记录登出日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="logout",
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    # 构建响应数据
    response_data = {
        "code": 200,
        "message": "登出成功",
        "data": {"message": "登出成功"}
    }

    # 如果启用 Cookie 认证，清除 Cookie
    if getattr(settings, 'ENABLE_COOKIE_AUTH', True):
        cookie_domain = getattr(settings, 'COOKIE_DOMAIN', None)
        resp = JSONResponse(content=response_data)

        resp.delete_cookie(
            key="admin_access_token",
            path="/",
            domain=cookie_domain,
        )
        resp.delete_cookie(
            key="admin_csrf_token",
            path="/",
            domain=cookie_domain,
        )

        return resp

    return JSONResponse(content=response_data)


@router.post("/validate-token", response_model=Response[dict])
async def validate_token(
    current_admin: AdminUser = Depends(get_current_admin)
):
    """验证令牌是否有效"""
    return Response(data={
        "valid": True,
        "admin_id": current_admin.id,
        "username": current_admin.username
    })
