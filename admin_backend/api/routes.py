"""
线路管理 API

支持多域名入口 + Cloudflare Worker 多路由配置
"""
import hashlib
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, text
from pydantic import BaseModel

from admin_database import get_db
from admin_utils.models_loader import AdminUser, AdminLog
from admin_utils.auth import get_current_admin, require_permission
from admin_utils.config import settings
from schemas.route import (
    RouteCreate,
    RouteUpdate,
    RouteResponse,
    RouteListItem,
    RouteToggleRequest,
    RouteMaintenanceRequest,
    RoutePriorityRequest,
    RouteCopyRequest,
    RoutePreviewRequest,
    RoutePreviewResponse,
    RoutePreviewDebugInfo,
    RouteHealthCheckResponse,
)
from schemas.common import Response

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================
# 公开接口（供 user_backend 调用）
# ============================================================

class PublicRouteInfo(BaseModel):
    """公开线路信息（不含敏感字段）"""
    id: int
    name: str
    description: Optional[str] = None
    priority: int
    domain: str
    tls: bool
    base_path: str
    tags: List[str]
    region_scope: List[str]
    worker_route: Optional[str] = None
    origin_type: str = 'emby'


@router.get("/public", response_model=List[PublicRouteInfo])
async def get_public_routes():
    """
    获取公开线路列表

    供 user_backend 调用，只返回启用的、状态正常的线路
    不包含敏感字段（如 auth_token）
    """
    if not check_feature_flag():
        return []

    engine = get_routes_table()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, name, description, priority, tags, region_scope,
                   domain, tls, base_path, worker_route, origin_type
            FROM routes
            WHERE enabled = TRUE AND status = 'ok'
            ORDER BY priority ASC, id ASC
        """))
        rows = result.fetchall()

        return [
            PublicRouteInfo(
                id=row.id,
                name=row.name,
                description=row.description,
                priority=row.priority,
                tags=row.tags or [],
                region_scope=row.region_scope or ['GLOBAL'],
                domain=row.domain,
                tls=row.tls,
                base_path=row.base_path or "",
                worker_route=row.worker_route,
                origin_type=row.origin_type or 'emby',
            )
            for row in rows
        ]


# ============================================================
# Feature Flag 检查
# ============================================================

def check_feature_flag() -> bool:
    """检查线路管理功能是否启用"""
    return getattr(settings, 'FEATURE_ROUTE_ADMIN', False)


# ============================================================
# 数据库模型 (动态创建，避免依赖)
# ============================================================

class RouteModel:
    """线路数据模型（动态映射）"""

    @staticmethod
    def from_row(row):
        """从数据库行转换为模型"""
        return RouteResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            enabled=row.enabled,
            priority=row.priority,
            tags=row.tags or [],
            region_scope=row.region_scope or ['GLOBAL'],
            domain=row.domain,
            tls=row.tls,
            base_path=row.base_path,
            worker_route=row.worker_route,
            origin_type=row.origin_type,
            rewrite_from=row.rewrite_from,
            rewrite_to=row.rewrite_to,
            headers=row.headers or {},
            auth_mode=row.auth_mode,
            cache_mode=row.cache_mode,
            status=row.status,
            maintenance_message=row.maintenance_message,
            rollout_percent=row.rollout_percent,
            rollout_allow_user_ids=row.rollout_allow_user_ids or [],
            rollout_deny_user_ids=row.rollout_deny_user_ids or [],
            health_url=row.health_url,
            health_expect_status=row.health_expect_status,
            health_timeout_ms=row.health_timeout_ms,
            health_interval_sec=row.health_interval_sec,
            health_last_ok_at=row.health_last_ok_at,
            health_last_latency_ms=row.health_last_latency_ms,
            health_fail_count=row.health_fail_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def to_list_item(row):
        """从数据库行转换为列表项"""
        return RouteListItem(
            id=row.id,
            name=row.name,
            description=row.description,
            enabled=row.enabled,
            priority=row.priority,
            status=row.status,
            domain=row.domain,
            tags=row.tags or [],
            region_scope=row.region_scope or ['GLOBAL'],
            health_last_ok_at=row.health_last_ok_at,
            health_fail_count=row.health_fail_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def get_routes_table():
    """获取 routes 表（使用 text 查询避免模型依赖）"""
    from admin_database import admin_engine
    return admin_engine


# ============================================================
# 辅助函数
# ============================================================

def log_action(
    db: Session,
    admin_id: int,
    admin_username: str,
    action: str,
    resource: str,
    resource_id: str = None,
    details: dict = None,
    request: Request = None
):
    """记录操作日志"""
    try:
        log = AdminLog(
            admin_id=admin_id,
            admin_username=admin_username,
            action=action,
            resource=resource,
            resource_id=str(resource_id) if resource_id else None,
            details=details or {},
            ip_address=request.client.host if request else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log action: {e}")


def hash_user_id_for_rollout(sticky_key: str, route_id: int) -> int:
    """
    稳定哈希函数，用于灰度分流

    返回 0-100 的值，相同的 sticky_key + route_id 组合总是得到相同结果
    """
    combined = f"{sticky_key}-{route_id}".encode('utf-8')
    hash_value = hashlib.md5(combined).hexdigest()
    return int(hash_value, 16) % 101


def get_sticky_key_from_user(user) -> str:
    """
    从用户对象获取稳定分流 key

    优先级：tg_id > emby_user_id > user_id
    """
    # 尝试获取 Telegram ID
    tg_id = getattr(user, 'tg_id', None)
    if tg_id:
        return f"tg:{tg_id}"

    # 尝试获取 Emby 用户ID
    emby_id = getattr(user, 'emby_id', None) or getattr(user, 'emby_account', None)
    if emby_id:
        return f"emby:{emby_id}"

    # 使用用户ID
    user_id = getattr(user, 'id', None)
    if user_id:
        return f"user:{user_id}"

    return "unknown"


def select_route_for_user(
    routes: List[RouteResponse],
    sticky_key: str,
    user_id: Optional[int] = None,
    region: Optional[str] = None
) -> Optional[RouteResponse]:
    """
    线路选择算法

    规则优先级：
    1. denyUserIds 排除（需要 user_id）
    2. allowUserIds 优先匹配（需要 user_id）
    3. enabled=false 或 status!=ok 排除
    4. regionScope 不匹配降权/排除
    5. percent 灰度使用 sticky_key 稳定 hash
    6. 按 priority 升序排序，选最优
    """
    # 1. 过滤排除规则（需要 user_id 才能检查 deny/allow 列表）
    candidates = [
        r for r in routes
        if r.enabled
        and r.status == 'ok'
        and (user_id is None or user_id not in (r.rollout_deny_user_ids or []))
    ]

    if not candidates:
        return None

    # 2. 白名单优先（需要 user_id）
    if user_id is not None:
        whitelist_matches = [
            r for r in candidates
            if user_id in (r.rollout_allow_user_ids or [])
        ]
        if whitelist_matches:
            return min(whitelist_matches, key=lambda r: r.priority)

    # 3. 地区匹配
    if region:
        region_matches = [
            r for r in candidates
            if region in (r.region_scope or ['GLOBAL']) or 'GLOBAL' in (r.region_scope or [])
        ]
        if region_matches:
            candidates = region_matches
        else:
            # 降级到 GLOBAL 线路
            candidates = [r for r in candidates if 'GLOBAL' in (r.region_scope or [])]

    if not candidates:
        return None

    # 4. 灰度分流（使用 sticky_key）
    for route in candidates:
        hp = hash_user_id_for_rollout(sticky_key, route.id)
        if hp <= route.rollout_percent:
            return route

    # 5. 按 priority 选最优
    return min(candidates, key=lambda r: r.priority)


# ============================================================
# API 路由
# ============================================================

@router.get("/", response_model=List[RouteListItem])
async def list_routes(
    enabled: Optional[bool] = Query(None, description="筛选启用状态"),
    status: Optional[str] = Query(None, description="筛选状态"),
    tags: Optional[str] = Query(None, description="筛选标签（逗号分隔）"),
    search: Optional[str] = Query(None, description="搜索名称或域名"),
    current_admin: AdminUser = Depends(require_permission("routes.view")),
):
    """
    获取线路列表

    支持按状态、标签、搜索词筛选
    """
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        # 构建查询
        query = "SELECT * FROM routes WHERE 1=1"
        params = {}

        if enabled is not None:
            query += " AND enabled = :enabled"
            params['enabled'] = enabled

        if status:
            query += " AND status = :status"
            params['status'] = status

        if tags:
            tag_list = tags.split(',')
            query += " AND tags && :tags"
            params['tags'] = tag_list

        if search:
            query += " AND (name ILIKE :search OR domain ILIKE :search)"
            params['search'] = f"%{search}%"

        query += " ORDER BY priority ASC, id ASC"

        result = conn.execute(text(query), params)
        rows = result.fetchall()

        return [RouteModel.to_list_item(row) for row in rows]


@router.get("/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: int,
    current_admin: AdminUser = Depends(require_permission("routes.view")),
):
    """获取线路详情"""
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="线路不存在")

        return RouteModel.from_row(row)


@router.post("/", response_model=RouteResponse)
async def create_route(
    route: RouteCreate,
    request: Request,
    current_admin: AdminUser = Depends(require_permission("routes.create")),
):
    """创建新线路"""
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        # 检查名称是否重复
        existing = conn.execute(
            text("SELECT id FROM routes WHERE name = :name"),
            {'name': route.name},
        ).fetchone()

        if existing:
            raise HTTPException(status_code=400, detail="线路名称已存在")

        # 插入线路
        result = conn.execute(
            text("""INSERT INTO routes (
                name, description, enabled, priority, tags, region_scope,
                domain, tls, base_path,
                worker_route, origin_type, rewrite_from, rewrite_to, headers, auth_mode, cache_mode,
                status, maintenance_message, rollout_percent, rollout_allow_user_ids, rollout_deny_user_ids,
                health_url, health_expect_status, health_timeout_ms, health_interval_sec
            ) VALUES (
                :name, :description, :enabled, :priority, :tags, :region_scope,
                :domain, :tls, :base_path,
                :worker_route, :origin_type, :rewrite_from, :rewrite_to, :headers, :auth_mode, :cache_mode,
                :status, :maintenance_message, :rollout_percent, :rollout_allow_user_ids, :rollout_deny_user_ids,
                :health_url, :health_expect_status, :health_timeout_ms, :health_interval_sec
            ) RETURNING id, created_at, updated_at"""),
            {
                'name': route.name,
                'description': route.description,
                'enabled': route.enabled,
                'priority': route.priority,
                'tags': route.tags,
                'region_scope': route.region_scope,
                'domain': route.domain,
                'tls': route.tls,
                'base_path': route.base_path,
                'worker_route': route.worker_route,
                'origin_type': route.origin_type,
                'rewrite_from': route.rewrite_from,
                'rewrite_to': route.rewrite_to,
                'headers': route.headers,
                'auth_mode': route.auth_mode,
                'cache_mode': route.cache_mode,
                'status': route.status,
                'maintenance_message': route.maintenance_message,
                'rollout_percent': route.rollout_percent,
                'rollout_allow_user_ids': route.rollout_allow_user_ids,
                'rollout_deny_user_ids': route.rollout_deny_user_ids,
                'health_url': route.health_url,
                'health_expect_status': route.health_expect_status,
                'health_timeout_ms': route.health_timeout_ms,
                'health_interval_sec': route.health_interval_sec,
            },
        )

        route_id = result.fetchone()[0]
        conn.commit()

        # 记录日志
        db = get_db()
        log_action(
            db, current_admin.id, current_admin.username,
            "routes.create", "route", route_id,
            {'name': route.name, 'domain': route.domain},
            request
        )

        # 获取创建的线路
        result = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        )
        row = result.fetchone()

        return RouteModel.from_row(row)


@router.put("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: int,
    route: RouteUpdate,
    request: Request,
    current_admin: AdminUser = Depends(require_permission("routes.update")),
):
    """更新线路"""
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        # 检查线路是否存在
        existing = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        ).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail="线路不存在")

        # 构建更新语句
        updates = []
        params = {'id': route_id}

        for field, value in route.model_dump(exclude_unset=True).items():
            if field in ['rollout_allow_user_ids', 'rollout_deny_user_ids', 'tags', 'region_scope', 'headers']:
                # 数组/字典类型需要特殊处理
                updates.append(f"{field} = :{field}")
                params[field] = value
            elif value is not None:
                updates.append(f"{field} = :{field}")
                params[field] = value

        if updates:
            query = f"UPDATE routes SET {', '.join(updates)} WHERE id = :id"
            conn.execute(text(query), params)
            conn.commit()

        # 记录日志
        db = get_db()
        log_action(
            db, current_admin.id, current_admin.username,
            "routes.update", "route", route_id,
            {'updated_fields': list(route.model_dump(exclude_unset=True).keys())},
            request
        )

        # 获取更新后的线路
        result = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        )
        row = result.fetchone()

        return RouteModel.from_row(row)


@router.delete("/{route_id}")
async def delete_route(
    route_id: int,
    request: Request,
    current_admin: AdminUser = Depends(require_permission("routes.delete")),
):
    """删除线路"""
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        # 检查线路是否存在
        existing = conn.execute(
            text("SELECT name FROM routes WHERE id = :id"),
            {'id': route_id},
        ).fetchone()

        if not existing:
            raise HTTPException(status_code=404, detail="线路不存在")

        # 删除线路
        conn.execute(text("DELETE FROM routes WHERE id = :id"), {'id': route_id},)
        conn.commit()

        # 记录日志
        db = get_db()
        log_action(
            db, current_admin.id, current_admin.username,
            "routes.delete", "route", route_id,
            {'deleted_name': existing[0]},
            request
        )

    return Response(success=True, message="线路已删除")


@router.post("/{route_id}/toggle", response_model=RouteResponse)
async def toggle_route(
    route_id: int,
    data: RouteToggleRequest,
    request: Request,
    current_admin: AdminUser = Depends(require_permission("routes.update")),
):
    """启用/禁用线路"""
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        # 更新启用状态
        conn.execute(
            text("UPDATE routes SET enabled = :enabled WHERE id = :id"),
            {'enabled': data.enabled, 'id': route_id},
        )
        conn.commit()

        # 记录日志
        db = get_db()
        log_action(
            db, current_admin.id, current_admin.username,
            "routes.toggle", "route", route_id,
            {'enabled': data.enabled},
            request
        )

        # 获取更新后的线路
        result = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        )
        row = result.fetchone()

        return RouteModel.from_row(row)


@router.post("/{route_id}/maintenance", response_model=RouteResponse)
async def set_maintenance(
    route_id: int,
    data: RouteMaintenanceRequest,
    request: Request,
    current_admin: AdminUser = Depends(require_permission("routes.update")),
):
    """设置维护模式"""
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        # 更新状态
        conn.execute(
            text("""UPDATE routes
               SET status = :status, maintenance_message = :message
               WHERE id = :id"""),
            {'status': data.status, 'message': data.maintenance_message, 'id': route_id},
        )
        conn.commit()

        # 记录日志
        db = get_db()
        log_action(
            db, current_admin.id, current_admin.username,
            "routes.maintenance", "route", route_id,
            {'status': data.status, 'message': data.maintenance_message},
            request
        )

        # 获取更新后的线路
        result = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        )
        row = result.fetchone()

        return RouteModel.from_row(row)


@router.post("/{route_id}/copy", response_model=RouteResponse)
async def copy_route(
    route_id: int,
    data: RouteCopyRequest,
    request: Request,
    current_admin: AdminUser = Depends(require_permission("routes.create")),
):
    """复制线路"""
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        # 获取原线路
        original = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        ).fetchone()

        if not original:
            raise HTTPException(status_code=404, detail="线路不存在")

        # 检查新名称是否重复
        existing = conn.execute(
            text("SELECT id FROM routes WHERE name = :name"),
            {'name': data.name},
        ).fetchone()

        if existing:
            raise HTTPException(status_code=400, detail="线路名称已存在")

        # 插入复制的线路
        result = conn.execute(
            text("""INSERT INTO routes (
                name, description, enabled, priority, tags, region_scope,
                domain, tls, base_path,
                worker_route, origin_type, rewrite_from, rewrite_to, headers, auth_mode, cache_mode,
                status, maintenance_message, rollout_percent, rollout_allow_user_ids, rollout_deny_user_ids,
                health_url, health_expect_status, health_timeout_ms, health_interval_sec
            ) SELECT
                :name, description, enabled, :priority, tags, region_scope,
                domain, tls, base_path,
                worker_route, origin_type, rewrite_from, rewrite_to, headers, auth_mode, cache_mode,
                status, maintenance_message, rollout_percent, rollout_allow_user_ids, rollout_deny_user_ids,
                health_url, health_expect_status, health_timeout_ms, health_interval_sec
            FROM routes WHERE id = :original_id
            RETURNING id, created_at, updated_at"""),
            {'name': data.name, 'priority': original.priority + 1, 'original_id': route_id},
        )

        new_id = result.fetchone()[0]
        conn.commit()

        # 记录日志
        db = get_db()
        log_action(
            db, current_admin.id, current_admin.username,
            "routes.copy", "route", new_id,
            {'original_id': route_id, 'new_name': data.name},
            request
        )

        # 获取创建的线路
        result = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': new_id},
        )
        row = result.fetchone()

        return RouteModel.from_row(row)


@router.put("/{route_id}/priority", response_model=RouteResponse)
async def update_priority(
    route_id: int,
    data: RoutePriorityRequest,
    request: Request,
    current_admin: AdminUser = Depends(require_permission("routes.update")),
):
    """调整线路优先级"""
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    engine = get_routes_table()
    with engine.connect() as conn:
        # 更新优先级
        conn.execute(
            text("UPDATE routes SET priority = :priority WHERE id = :id"),
            {'priority': data.priority, 'id': route_id},
        )
        conn.commit()

        # 记录日志
        db = get_db()
        log_action(
            db, current_admin.id, current_admin.username,
            "routes.priority", "route", route_id,
            {'new_priority': data.priority},
            request
        )

        # 获取更新后的线路
        result = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        )
        row = result.fetchone()

        return RouteModel.from_row(row)


@router.post("/preview", response_model=RoutePreviewResponse)
async def preview_route_selection(
    data: RoutePreviewRequest,
    current_admin: AdminUser = Depends(require_permission("routes.view")),
):
    """
    策略预览

    输入用户标识（user_id/tg_id/emby_user_id/anon_id）和模拟条件，计算会分配到哪条线路并解释原因

    Sticky Key 优先级：tg_id > emby_user_id > user_id > anon_id
    """
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    # 获取 sticky_key
    sticky_key = data.sticky_key

    engine = get_routes_table()
    with engine.connect() as conn:
        # 获取所有启用的线路
        result = conn.execute(
            text("""SELECT * FROM routes
               WHERE enabled = TRUE
               ORDER BY priority ASC""")
        )
        rows = result.fetchall()

        if not rows:
            return RoutePreviewResponse(
                selected_route=None,
                available_routes=[],
                explanation="没有可用的线路配置",
                debug_info=RoutePreviewDebugInfo(
                    total_routes=0,
                    enabled_routes=0,
                    status_ok_routes=0,
                    region_matched=False,
                    in_allow_list=False,
                    in_deny_list=False,
                    rollout_passed=False,
                    matched_rules=[],
                )
            )

        # 转换为模型
        all_routes = [RouteModel.from_row(row) for row in rows]

        # 执行选择算法（使用 sticky_key）
        selected = select_route_for_user(
            all_routes,
            sticky_key,
            data.user_id,
            data.region
        )

        # 构建调试信息
        debug_info = build_debug_info(
            all_routes,
            selected,
            sticky_key,
            data.user_id,
            data.region
        )

        # 构建说明
        explanation = build_explanation(selected, debug_info, sticky_key)

        return RoutePreviewResponse(
            selected_route=selected,
            available_routes=all_routes,
            explanation=explanation,
            debug_info=debug_info
        )


def build_debug_info(
    routes: List[RouteResponse],
    selected: Optional[RouteResponse],
    sticky_key: str,
    user_id: Optional[int] = None,
    region: Optional[str] = None
) -> RoutePreviewDebugInfo:
    """构建调试信息"""
    enabled_count = len([r for r in routes if r.enabled])
    ok_count = len([r for r in routes if r.status == 'ok'])

    in_allow = user_id is not None and any(user_id in (r.rollout_allow_user_ids or []) for r in routes)
    in_deny = user_id is not None and any(user_id in (r.rollout_deny_user_ids or []) for r in routes)

    region_match = False
    if region:
        region_match = any(
            region in (r.region_scope or ['GLOBAL']) or 'GLOBAL' in (r.region_scope or [])
            for r in routes
        )

    rollout_pass = False
    hash_val = None
    matched = []

    if selected:
        hash_val = hash_user_id_for_rollout(sticky_key, selected.id)
        rollout_pass = hash_val <= selected.rollout_percent

        if in_allow:
            matched.append("用户在白名单中")
        elif in_deny:
            matched.append("用户在黑名单中（被排除）")
        elif rollout_pass:
            matched.append(f"灰度分流通过 (hash={hash_val} <= {selected.rollout_percent}%)")
        else:
            matched.append(f"灰度分流未通过 (hash={hash_val} > {selected.rollout_percent}%)")

        if region_match:
            matched.append(f"地区匹配: {region or 'GLOBAL'}")

        # 添加 sticky_key 信息
        matched.append(f"Sticky Key: {sticky_key}")

    return RoutePreviewDebugInfo(
        total_routes=len(routes),
        enabled_routes=enabled_count,
        status_ok_routes=ok_count,
        region_matched=region_match,
        in_allow_list=in_allow,
        in_deny_list=in_deny,
        rollout_passed=rollout_pass,
        hash_value=hash_val,
        matched_rules=matched,
    )


def build_explanation(
    selected: Optional[RouteResponse],
    debug: RoutePreviewDebugInfo,
    sticky_key: str
) -> str:
    """构建选择说明"""
    if not selected:
        if debug.in_deny_list:
            return "用户在黑名单中，没有可用线路"
        return "没有符合条件的线路"

    parts = [f"已选择线路「{selected.name}」"]

    if debug.in_allow_list:
        parts.append("（用户在白名单中）")

    if selected.status == 'maintenance':
        parts.append("（当前处于维护模式）")

    if debug.hash_value is not None:
        parts.append(f"灰度值: {debug.hash_value}%")

    parts.append(f"(Sticky Key: {sticky_key})")

    return "".join(parts)


@router.post("/{route_id}/health-check", response_model=RouteHealthCheckResponse)
async def manual_health_check(
    route_id: int,
    current_admin: AdminUser = Depends(require_permission("routes.update")),
):
    """
    手动触发健康检查

    向配置的健康检查URL发送请求，更新线路状态
    """
    if not check_feature_flag():
        raise HTTPException(status_code=404, detail="功能未启用")

    import httpx

    engine = get_routes_table()
    with engine.connect() as conn:
        # 获取线路信息
        row = conn.execute(
            text("SELECT * FROM routes WHERE id = :id"),
            {'id': route_id},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="线路不存在")

        route_dict = dict(row._mapping)
        route = RouteModel.from_row(row)

        if not route.health_url:
            raise HTTPException(status_code=400, detail="该线路未配置健康检查URL")

        # 执行健康检查
        is_healthy = False
        status_code = None
        latency_ms = None
        error_message = None

        try:
            import time
            start_time = time.time()

            async with httpx.AsyncClient(timeout=route.health_timeout_ms / 1000) as client:
                response = await client.get(
                    route.health_url,
                    follow_redirects=True
                )

            latency_ms = int((time.time() - start_time) * 1000)
            status_code = response.status_code
            is_healthy = status_code == route.health_expect_status

        except Exception as e:
            error_message = str(e)

        # 更新健康检查结果
        if is_healthy:
            conn.execute(
                text("""UPDATE routes
                SET health_last_ok_at = NOW(),
                    health_last_latency_ms = :latency,
                    health_fail_count = 0
                WHERE id = :id"""),
                {'latency': latency_ms, 'id': route_id},
            )
        else:
            conn.execute(
                text("""UPDATE routes
                SET health_fail_count = health_fail_count + 1
                WHERE id = :id"""),
                {'id': route_id},
            )

        conn.commit()

        return RouteHealthCheckResponse(
            route_id=route_id,
            route_name=route.name,
            is_healthy=is_healthy,
            status_code=status_code,
            latency_ms=latency_ms,
            error_message=error_message,
            checked_at=datetime.now()
        )
