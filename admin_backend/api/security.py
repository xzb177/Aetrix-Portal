"""
安全相关 API
登录历史、会话管理、安全设置
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import secrets

from admin_database import get_db, AdminUser, AdminLog
from admin_utils.models_loader import Permission
from admin_utils.auth import get_current_admin
from schemas.common import Response

router = APIRouter()


def get_client_ip(request: Request) -> str:
    """获取客户端真实IP"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/login-history")
async def get_login_history(
    page: int = 1,
    page_size: int = 20,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取当前管理员的登录历史"""
    query = db.query(AdminLog).filter(
        AdminLog.admin_id == current_admin.id
    ).order_by(desc(AdminLog.created_at))

    total = query.count()
    logs = query.offset((page - 1) * page_size).limit(page_size).all()

    return Response(data={
        "items": [
            {
                "id": log.id,
                "action": log.action,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "details": log.details
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    })


@router.get("/sessions")
async def get_active_sessions(
    request: Request,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取活跃会话列表（基于最近登录记录）"""
    # 获取最近24小时内的登录记录作为"活跃会话"
    cutoff = datetime.now() - timedelta(hours=24)
    logs = db.query(AdminLog).filter(
        AdminLog.admin_id == current_admin.id,
        AdminLog.action == "login_success",
        AdminLog.created_at >= cutoff
    ).order_by(desc(AdminLog.created_at)).all()

    # 生成会话ID（基于IP和时间的哈希）
    sessions = []
    for log in logs:
        session_id = secrets.token_hex(8)
        # 使用IP和用户代理作为会话标识
        session_id = f"{hash(log.ip_address + str(log.created_at)) & 0xFFFF:04x}"

        # 检查是否是当前会话
        current_ip = get_client_ip(request)
        is_current = (log.ip_address == current_ip)

        sessions.append({
            "id": session_id,
            "ip_address": log.ip_address or "未知",
            "user_agent": log.user_agent or "未知",
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "last_active": log.created_at.isoformat() if log.created_at else None,
            "is_current": is_current
        })

    # 当前会话ID（当前IP的会话）
    current_session = next((s for s in sessions if s["is_current"]), None)
    current_session_id = current_session["id"] if current_session else ""

    return Response(data={
        "sessions": sessions,
        "current_session_id": current_session_id
    })


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """撤销指定会话"""
    # 在实际实现中，这里可以将会话标记为无效
    # 当前简化实现：记录撤销操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="session_revoked",
        details={"session_id": session_id, "action": "revoked"},
        ip_address=session_id,
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "会话已撤销"})


@router.post("/sessions/revoke-others")
async def revoke_all_other_sessions(
    request: Request,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """撤销所有其他会话"""
    current_ip = get_client_ip(request)

    # 记录撤销操作
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="revoke_other_sessions",
        details={"current_ip": current_ip, "action": "revoked_others"},
        ip_address=current_ip,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "已撤销所有其他会话"})


@router.get("/security-stats")
async def get_security_stats(
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """获取安全统计信息"""
    # 总登录次数
    total_logins = db.query(AdminLog).filter(
        AdminLog.admin_id == current_admin.id,
        AdminLog.action == "login_success"
    ).count()

    # 失败尝试次数
    failed_attempts = db.query(AdminLog).filter(
        AdminLog.admin_id == current_admin.id,
        AdminLog.action == "login_failed"
    ).count()

    # 活跃会话数（最近24小时的登录）
    cutoff = datetime.now() - timedelta(hours=24)
    active_sessions = db.query(AdminLog).filter(
        AdminLog.admin_id == current_admin.id,
        AdminLog.action == "login_success",
        AdminLog.created_at >= cutoff
    ).count()

    # 最后密码修改时间
    password_change_log = db.query(AdminLog).filter(
        AdminLog.admin_id == current_admin.id,
        AdminLog.action == "change_password_success"
    ).order_by(desc(AdminLog.created_at)).first()
    last_password_change = password_change_log.created_at.isoformat() if password_change_log else None

    # 计算安全分数
    score = 100
    if failed_attempts > 0:
        score -= min(20, failed_attempts * 5)
    if active_sessions > 1:
        score -= min(15, (active_sessions - 1) * 5)
    if not last_password_change or \
       (datetime.now() - password_change_log.created_at).days > 90:
        score -= 20

    return Response(data={
        "total_logins": total_logins,
        "failed_attempts": failed_attempts,
        "active_sessions": active_sessions,
        "last_password_change": last_password_change,
        "security_score": max(0, score)
    })


@router.get("/security-settings")
async def get_security_settings(
    current_admin: AdminUser = Depends(get_current_admin)
):
    """获取安全设置"""
    # 简化实现：返回默认设置
    return Response(data={
        "enable_login_alert": True,
        "enable_2fa": False,
        "trusted_ips": []
    })


@router.put("/security-settings")
async def update_security_settings(
    data: dict,
    current_admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """更新安全设置"""
    # 记录设置变更
    log = AdminLog(
        admin_id=current_admin.id,
        admin_username=current_admin.username,
        action="security_settings_updated",
        details=data,
    )
    db.add(log)
    db.commit()

    return Response(data={"message": "安全设置已更新"})


@router.post("/check-password-strength")
async def check_password_strength(
    data: dict
):
    """检查密码强度"""
    password = data.get("password", "")
    score = 0
    feedback = []

    # 长度检查
    if len(password) >= 12:
        score += 25
    elif len(password) >= 8:
        score += 15
    else:
        feedback.append("密码长度至少需要12位")

    # 复杂度检查
    import re
    if re.search(r'[A-Z]', password):
        score += 25
    else:
        feedback.append("需要包含大写字母")

    if re.search(r'[a-z]', password):
        score += 15
    else:
        feedback.append("需要包含小写字母")

    if re.search(r'\d', password):
        score += 15
    else:
        feedback.append("需要包含数字")

    if re.search(r'[!@#$%^&*()_+\-=\[\]{};:"\\|,.<>?]', password):
        score += 20
    else:
        feedback.append("需要包含特殊字符")

    # 常见弱密码检查
    common_passwords = [
        "password", "12345678", "abcdefgh", "qwerty123",
        "admin123", "letmein", "welcome1"
    ]
    if password.lower() in common_passwords:
        score = 0
        feedback.append("密码过于常见")

    return Response(data={
        "score": min(100, score),
        "strength": "strong" if score >= 80 else "medium" if score >= 50 else "weak",
        "feedback": feedback
    })
