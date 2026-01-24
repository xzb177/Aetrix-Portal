"""
运营中控台 API (Admin Ops)

功能：
1. Feature Flags 开关面板
2. 风控（限速、黑名单）
3. 观测（事件记录、告警）
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import json
import asyncio

from admin_database_user import get_user_db, SystemConfig
from admin_utils.auth import get_current_admin
from admin_database import AdminLog


router = APIRouter(prefix="/admin-ops", tags=["运营中控台"])


# ==================== 数据模型 ====================

class FeatureFlagItem(BaseModel):
    """Feature Flag 配置项"""
    key: str
    value: str
    label: str
    description: str
    type: Literal["boolean", "number", "text"]
    default: str
    category: str = "Feature Flags"


class FeatureFlagsResponse(BaseModel):
    """Feature Flags 响应"""
    flags: List[FeatureFlagItem]
    last_updated: Optional[datetime] = None


class RateLimitRule(BaseModel):
    """限速规则"""
    id: Optional[int] = None
    name: str
    endpoint: str  # 注册/邀请/求片/充值查询
    limit: int  # 请求数量
    window: int  # 时间窗口（秒）
    scope: Literal["user", "ip", "anon"] = "user"
    enabled: bool = True


class BlacklistEntry(BaseModel):
    """黑名单条目"""
    id: Optional[int] = None
    type: Literal["ip", "user_id", "anon_id"]
    value: str
    reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    enabled: bool = True


class EventRecord(BaseModel):
    """事件记录"""
    id: int
    event_type: str
    user_id: Optional[int]
    ip: Optional[str]
    details: Dict[str, Any]
    created_at: datetime


class EventStats(BaseModel):
    """事件统计"""
    date: str
    total_events: int
    by_type: Dict[str, int]
    error_rate: float
    top_errors: List[Dict[str, Any]]


class AlertConfig(BaseModel):
    """告警配置"""
    id: Optional[int] = None
    name: str
    event_type: str  # 错误事件类型
    threshold: int  # 阈值（次数）
    window_minutes: int  # 时间窗口（分钟）
    enabled: bool = True
    telegram_notify: bool = True


# ==================== Feature Flags 定义 ====================

FEATURE_FLAGS = {
    "feature_route_config": {
        "label": "线路配置中心",
        "description": "启用后，管理后台可访问线路管理页面，支持多域名、灰度分流等功能",
        "default": "false",
        "type": "boolean",
    },
    "feature_invite": {
        "label": "邀请功能",
        "description": "启用后，用户可使用邀请码邀请好友并获得奖励",
        "default": "true",
        "type": "boolean",
    },
    "feature_request": {
        "label": "求片功能",
        "description": "启用后，用户可提交求片请求",
        "default": "true",
        "type": "boolean",
    },
    "feature_payment": {
        "label": "支付功能",
        "description": "启用后，用户可进行充值和订阅支付",
        "default": "true",
        "type": "boolean",
    },
    "feature_easter_egg": {
        "label": "彩蛋功能",
        "description": "启用后，个人中心的 Holo-ID 卡片长按可触发调试模式",
        "default": "true",
        "type": "boolean",
    },
    "maintenance_mode": {
        "label": "维护模式",
        "description": "启用后，用户端显示维护页面，仅管理员可访问",
        "default": "false",
        "type": "boolean",
    },
    "maintenance_message": {
        "label": "维护公告",
        "description": "维护模式下显示的公告信息",
        "default": "系统维护中，请稍后再访问",
        "type": "text",
    },
    "ops_refresh_interval": {
        "label": "配置刷新间隔（分钟）",
        "description": "前端拉取 Feature Flags 的间隔时间",
        "default": "5",
        "type": "number",
    },
}


# ==================== 1. Feature Flags API ====================

@router.get("/feature-flags", response_model=FeatureFlagsResponse)
async def get_feature_flags(
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """获取所有 Feature Flags 配置"""
    flags = []
    last_updated = None

    for key, definition in FEATURE_FLAGS.items():
        # 从数据库获取当前值
        config = db.query(SystemConfig).filter(
            SystemConfig.key == key
        ).first()

        value = definition["default"]
        if config:
            value = config.value
            if config.updated_at:
                last_updated = max(last_updated or config.updated_at, config.updated_at)

        flags.append(FeatureFlagItem(
            key=key,
            value=value,
            label=definition["label"],
            description=definition["description"],
            type=definition["type"],
            default=definition["default"],
            category="Feature Flags"
        ))

    # 按默认顺序排序
    flags.sort(key=lambda x: list(FEATURE_FLAGS.keys()).index(x.key))

    return FeatureFlagsResponse(flags=flags, last_updated=last_updated)


@router.put("/feature-flags/{key}")
async def update_feature_flag(
    key: str,
    value: str = Query(..., description="新值"),
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """更新单个 Feature Flag"""
    if key not in FEATURE_FLAGS:
        raise HTTPException(status_code=404, detail=f"Feature Flag {key} 不存在")

    definition = FEATURE_FLAGS[key]

    # 验证值类型
    if definition["type"] == "boolean":
        if value.lower() not in ["true", "false"]:
            raise HTTPException(status_code=400, detail="布尔值必须是 true 或 false")
        value = value.lower()
    elif definition["type"] == "number":
        try:
            int(value)
        except ValueError:
            raise HTTPException(status_code=400, detail="必须是数字")

    # 查找或创建配置
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if config:
        old_value = config.value
        config.value = value
        config.updated_at = datetime.utcnow()
    else:
        old_value = definition["default"]
        config = SystemConfig(
            key=key,
            value=value,
            category="Feature Flags",
            description=definition["description"],
            updated_at=datetime.utcnow()
        )
        db.add(config)

    db.commit()

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        action="update_feature_flag",
        details=f"更新 Feature Flag: {key} 从 {old_value} -> {value}",
        created_at=datetime.utcnow()
    )
    db.add(log)
    db.commit()

    return {"key": key, "value": value, "message": "更新成功"}


@router.post("/feature-flags/batch")
async def batch_update_feature_flags(
    updates: Dict[str, str],
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """批量更新 Feature Flags"""
    results = []

    for key, value in updates.items():
        if key not in FEATURE_FLAGS:
            continue

        definition = FEATURE_FLAGS[key]

        # 验证值类型
        if definition["type"] == "boolean":
            if value.lower() not in ["true", "false"]:
                continue
            value = value.lower()
        elif definition["type"] == "number":
            try:
                int(value)
            except ValueError:
                continue

        # 更新或创建配置
        config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if config:
            config.value = value
            config.updated_at = datetime.utcnow()
        else:
            config = SystemConfig(
                key=key,
                value=value,
                category="Feature Flags",
                description=definition["description"],
                updated_at=datetime.utcnow()
            )
            db.add(config)

        results.append({"key": key, "value": value})

    db.commit()

    # 记录操作日志
    log = AdminLog(
        admin_id=current_admin.id,
        action="batch_update_feature_flags",
        details=f"批量更新 {len(results)} 个 Feature Flags",
        created_at=datetime.utcnow()
    )
    db.add(log)
    db.commit()

    return {"updated": len(results), "results": results}


# ==================== 公开的 Feature Flags API（供前端拉取）====================

@router.get("/public/feature-flags")
async def get_public_feature_flags(
    db: Session = Depends(get_user_db)
):
    """公开接口：获取所有 Feature Flags（供前端拉取，无需鉴权）"""
    flags = {}

    for key, definition in FEATURE_FLAGS.items():
        # 从数据库获取当前值
        config = db.query(SystemConfig).filter(
            SystemConfig.key == key
        ).first()

        value = definition["default"]
        if config:
            value = config.value

        # 转换类型
        if definition["type"] == "boolean":
            flags[key] = value.lower() == "true"
        elif definition["type"] == "number":
            flags[key] = int(value)
        else:
            flags[key] = value

    return flags


# ==================== 2. 风控 API ====================

@router.get("/rate-limits", response_model=List[RateLimitRule])
async def get_rate_limits(
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """获取所有限速规则"""
    # 从配置中读取
    configs = db.query(SystemConfig).filter(
        SystemConfig.category == "rate_limit"
    ).all()

    rules = []
    for config in configs:
        try:
            rule_data = json.loads(config.value)
            rules.append(RateLimitRule(
                id=config.id,
                **rule_data
            ))
        except:
            pass

    return rules


@router.put("/rate-limits")
async def upsert_rate_limit(
    rule: RateLimitRule,
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """创建或更新限速规则"""
    config_key = f"rate_limit_{rule.endpoint}"

    config = db.query(SystemConfig).filter(
        SystemConfig.key == config_key
    ).first()

    rule_data = {
        "name": rule.name,
        "endpoint": rule.endpoint,
        "limit": rule.limit,
        "window": rule.window,
        "scope": rule.scope,
        "enabled": rule.enabled
    }

    if config:
        config.value = json.dumps(rule_data)
        config.updated_at = datetime.utcnow()
    else:
        config = SystemConfig(
            key=config_key,
            value=json.dumps(rule_data),
            category="rate_limit",
            description=f"限速规则: {rule.name}",
            updated_at=datetime.utcnow()
        )
        db.add(config)

    db.commit()

    # 记录日志
    log = AdminLog(
        admin_id=current_admin.id,
        action="upsert_rate_limit",
        details=f"更新限速规则: {rule.name}",
        created_at=datetime.utcnow()
    )
    db.add(log)
    db.commit()

    return {"message": "限速规则已保存"}


@router.get("/blacklist", response_model=List[BlacklistEntry])
async def get_blacklist(
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """获取黑名单"""
    configs = db.query(SystemConfig).filter(
        SystemConfig.category == "blacklist"
    ).all()

    entries = []
    for config in configs:
        try:
            entry_data = json.loads(config.value)
            entries.append(BlacklistEntry(
                id=config.id,
                **entry_data
            ))
        except:
            pass

    return entries


@router.post("/blacklist")
async def add_blacklist_entry(
    entry: BlacklistEntry,
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """添加黑名单条目"""
    config_key = f"blacklist_{entry.type}_{entry.value}"

    entry_data = {
        "type": entry.type,
        "value": entry.value,
        "reason": entry.reason,
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
        "enabled": entry.enabled
    }

    config = SystemConfig(
        key=config_key,
        value=json.dumps(entry_data),
        category="blacklist",
        description=f"黑名单: {entry.type} - {entry.value}",
        updated_at=datetime.utcnow()
    )
    db.add(config)
    db.commit()

    # 记录日志
    log = AdminLog(
        admin_id=current_admin.id,
        action="add_blacklist",
        details=f"添加黑名单: {entry.type} - {entry.value}",
        created_at=datetime.utcnow()
    )
    db.add(log)
    db.commit()

    return {"message": "黑名单条目已添加"}


@router.delete("/blacklist/{config_id}")
async def remove_blacklist_entry(
    config_id: int,
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """删除黑名单条目"""
    config = db.query(SystemConfig).filter(
        SystemConfig.id == config_id,
        SystemConfig.category == "blacklist"
    ).first()

    if not config:
        raise HTTPException(status_code=404, detail="黑名单条目不存在")

    db.delete(config)
    db.commit()

    # 记录日志
    log = AdminLog(
        admin_id=current_admin.id,
        action="remove_blacklist",
        details=f"删除黑名单: {config.key}",
        created_at=datetime.utcnow()
    )
    db.add(log)
    db.commit()

    return {"message": "黑名单条目已删除"}


# ==================== 3. 观测 API ====================

@router.get("/stats/today", response_model=EventStats)
async def get_today_stats(
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """获取今日统计"""
    today = datetime.utcnow().date()

    # 从配置中读取统计数据（存储在 SystemConfig 中）
    stats_config = db.query(SystemConfig).filter(
        SystemConfig.key == f"event_stats_{today.isoformat()}"
    ).first()

    if stats_config:
        try:
            stats_data = json.loads(stats_config.value)
            return EventStats(**stats_data)
        except:
            pass

    # 默认返回空统计
    return EventStats(
        date=today.isoformat(),
        total_events=0,
        by_type={},
        error_rate=0.0,
        top_errors=[]
    )


@router.get("/stats/recent-errors")
async def get_recent_errors(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """获取最近的错误列表"""
    # 从 AdminLog 中读取错误相关的日志
    logs = db.query(AdminLog).filter(
        AdminLog.action.contains("error") |
        AdminLog.action.contains("fail") |
        AdminLog.action.contains("exception")
    ).order_by(AdminLog.created_at.desc()).limit(limit).all()

    errors = []
    for log in logs:
        errors.append({
            "id": log.id,
            "action": log.action,
            "details": log.details,
            "created_at": log.created_at.isoformat()
        })

    return errors


@router.get("/alerts", response_model=List[AlertConfig])
async def get_alert_configs(
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """获取告警配置"""
    configs = db.query(SystemConfig).filter(
        SystemConfig.category == "alert"
    ).all()

    alerts = []
    for config in configs:
        try:
            alert_data = json.loads(config.value)
            alerts.append(AlertConfig(
                id=config.id,
                **alert_data
            ))
        except:
            pass

    # 默认告警配置
    if not alerts:
        alerts = [
            AlertConfig(
                name="支付失败告警",
                event_type="payment_fail",
                threshold=10,
                window_minutes=5,
                enabled=True,
                telegram_notify=True
            ),
            AlertConfig(
                name="登录失败告警",
                event_type="login_fail",
                threshold=20,
                window_minutes=5,
                enabled=True,
                telegram_notify=True
            )
        ]

    return alerts


@router.put("/alerts")
async def upsert_alert_config(
    alert: AlertConfig,
    db: Session = Depends(get_user_db),
    current_admin = Depends(get_current_admin)
):
    """创建或更新告警配置"""
    config_key = f"alert_{alert.event_type}_{alert.name}"

    alert_data = {
        "name": alert.name,
        "event_type": alert.event_type,
        "threshold": alert.threshold,
        "window_minutes": alert.window_minutes,
        "enabled": alert.enabled,
        "telegram_notify": alert.telegram_notify
    }

    config = db.query(SystemConfig).filter(
        SystemConfig.key == config_key
    ).first()

    if config:
        config.value = json.dumps(alert_data)
        config.updated_at = datetime.utcnow()
    else:
        config = SystemConfig(
            key=config_key,
            value=json.dumps(alert_data),
            category="alert",
            description=f"告警配置: {alert.name}",
            updated_at=datetime.utcnow()
        )
        db.add(config)

    db.commit()

    # 记录日志
    log = AdminLog(
        admin_id=current_admin.id,
        action="upsert_alert",
        details=f"更新告警配置: {alert.name}",
        created_at=datetime.utcnow()
    )
    db.add(log)
    db.commit()

    return {"message": "告警配置已保存"}


# ==================== 事件记录 API（供其他服务调用）====================

@router.post("/events")
async def record_event(
    event_type: str = Query(..., description="事件类型"),
    user_id: Optional[int] = Query(None, description="用户ID"),
    ip: Optional[str] = Query(None, description="IP地址"),
    details: str = Query(None, description="事件详情JSON"),
    db: Session = Depends(get_user_db)
):
    """
    记录事件（供其他服务调用）

    事件类型：
    - login, login_fail, register
    - invite_create, invite_use
    - request_create, request_complete
    - payment_create, payment_success, payment_fail
    - route_selected
    - error, exception
    """
    try:
        details_data = json.loads(details) if details else {}
    except:
        details_data = {}

    # 存储到 SystemConfig 中（按日期分组）
    today = datetime.utcnow().date()
    stats_key = f"event_stats_{today.isoformat()}"

    config = db.query(SystemConfig).filter(
        SystemConfig.key == stats_key
    ).first()

    if config:
        try:
            stats_data = json.loads(config.value)
            stats_data["total_events"] = stats_data.get("total_events", 0) + 1
            stats_data["by_type"][event_type] = stats_data.get("by_type", {}).get(event_type, 0) + 1

            # 记录错误
            if "error" in event_type or "fail" in event_type:
                error_entry = {
                    "type": event_type,
                    "user_id": user_id,
                    "ip": ip,
                    "details": details_data,
                    "timestamp": datetime.utcnow().isoformat()
                }
                if "top_errors" not in stats_data:
                    stats_data["top_errors"] = []
                stats_data["top_errors"].insert(0, error_entry)
                stats_data["top_errors"] = stats_data["top_errors"][:20]  # 只保留最近20条

            config.value = json.dumps(stats_data)
            config.updated_at = datetime.utcnow()
        except:
            # 如果解析失败，重新创建
            stats_data = {
                "date": today.isoformat(),
                "total_events": 1,
                "by_type": {event_type: 1},
                "error_rate": 0.0,
                "top_errors": []
            }
            if "error" in event_type or "fail" in event_type:
                stats_data["top_errors"] = [{
                    "type": event_type,
                    "user_id": user_id,
                    "ip": ip,
                    "details": details_data,
                    "timestamp": datetime.utcnow().isoformat()
                }]
            config.value = json.dumps(stats_data)
    else:
        # 创建新的统计记录
        stats_data = {
            "date": today.isoformat(),
            "total_events": 1,
            "by_type": {event_type: 1},
            "error_rate": 0.0,
            "top_errors": []
        }
        if "error" in event_type or "fail" in event_type:
            stats_data["top_errors"] = [{
                "type": event_type,
                "user_id": user_id,
                "ip": ip,
                "details": details_data,
                "timestamp": datetime.utcnow().isoformat()
            }]

        config = SystemConfig(
            key=stats_key,
            value=json.dumps(stats_data),
            category="event_stats",
            description=f"事件统计: {today.isoformat()}",
            updated_at=datetime.utcnow()
        )
        db.add(config)

    db.commit()

    # 检查是否需要触发告警
    await _check_and_send_alerts(db, event_type, user_id, details_data)

    return {"message": "事件已记录"}


async def _check_and_send_alerts(
    db: Session,
    event_type: str,
    user_id: Optional[int],
    details: Dict[str, Any]
):
    """检查告警规则并发送通知"""
    # 获取所有启用的告警配置
    alert_configs = db.query(SystemConfig).filter(
        SystemConfig.category == "alert"
    ).all()

    for config in alert_configs:
        try:
            alert_data = json.loads(config.value)
            if not alert_data.get("enabled", True):
                continue

            if alert_data["event_type"] != event_type:
                continue

            # 检查阈值
            # 这里简化处理，实际应该使用更复杂的计数逻辑
            # 可以考虑使用 Redis 来实现滑动窗口计数

            if alert_data.get("telegram_notify", True):
                await _send_telegram_alert(
                    db,
                    alert_data["name"],
                    event_type,
                    user_id,
                    details
                )
        except Exception as e:
            print(f"检查告警失败: {e}")


async def _send_telegram_alert(
    db: Session,
    alert_name: str,
    event_type: str,
    user_id: Optional[int],
    details: Dict[str, Any]
):
    """发送 Telegram 告警"""
    try:
        # 获取 Telegram 配置
        bot_token_config = db.query(SystemConfig).filter(
            SystemConfig.key == "telegram_bot_token"
        ).first()
        notify_chats_config = db.query(SystemConfig).filter(
            SystemConfig.key == "telegram_notify_chats"
        ).first()

        if not bot_token_config or not notify_chats_config:
            return

        import httpx

        bot_token = bot_token_config.value
        chat_ids = notify_chats_config.value.split(",")

        message = f"🚨 【告警触发】{alert_name}\n"
        message += f"事件类型: {event_type}\n"
        if user_id:
            message += f"用户ID: {user_id}\n"
        message += f"时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"详情: {json.dumps(details, ensure_ascii=False)}"

        for chat_id in chat_ids:
            chat_id = chat_id.strip()
            if not chat_id:
                continue

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(url, json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }, timeout=5.0)
    except Exception as e:
        print(f"发送 Telegram 告警失败: {e}")
