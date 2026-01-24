"""
用户端线路查询 API

支持兼容回退机制：配置中心无数据/异常时自动使用默认线路
"""
import hashlib
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import engine
from database.models import WebUser
from api.auth import get_current_user_optional
from sqlalchemy.orm import sessionmaker
SessionLocal = sessionmaker(bind=engine)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# Feature Flag 检查
# ============================================================

def check_route_config_enabled() -> bool:
    """检查线路配置功能是否启用"""
    import os
    return os.getenv('FEATURE_ROUTE_CONFIG', 'false').lower() == 'true'


# ============================================================
# 线路响应模型（简化版，不暴露敏感信息）
# ============================================================

class RouteInfo(BaseModel):
    """用户端线路信息（简化版）"""
    id: int
    name: str
    description: Optional[str] = None
    priority: int
    domain: str
    tls: bool
    base_path: str
    tags: List[str]
    region_scope: List[str]
    # Worker 配置（可能不暴露给前端）
    worker_route: Optional[str] = None
    origin_type: str = 'emby'

    class Config:
        from_attributes = True


# ============================================================
# 默认线路（兼容回退）
# ============================================================

def get_default_routes() -> List[RouteInfo]:
    """
    获取默认线路列表（兼容回退）

    当配置中心不可用时，返回基于 Emby 服务器的默认线路
    """
    try:
        # 导入 Emby 相关模型
        from database.models import EmbyServer

        db = SessionLocal()
        try:
            # 获取所有启用的 Emby 服务器
            servers = db.query(EmbyServer).filter(
                EmbyServer.is_active == True
            ).all()

            if not servers:
                return []

            routes = []
            for server in servers:
                # 从 URL 提取域名
                from urllib.parse import urlparse
                parsed = urlparse(server.url)
                domain = parsed.netloc or parsed.path

                routes.append(RouteInfo(
                    id=server.id,  # 使用服务器ID作为线路ID
                    name=server.name or f"线路 {server.id}",
                    description="默认线路（基于 Emby 服务器）",
                    priority=100,  # 默认优先级
                    domain=domain,
                    tls=parsed.scheme == 'https',
                    base_path="",
                    tags=['default', 'emby'],
                    region_scope=['GLOBAL'],
                    worker_route=None,
                    origin_type='emby',
                ))

            return routes
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to get default routes: {e}")
        return []


# ============================================================
# 线路选择算法
# ============================================================

def hash_user_id_for_rollout(user_id: int, route_id: int) -> int:
    """
    稳定哈希函数，用于灰度分流

    返回 0-100 的值，相同的 user_id + route_id 组合总是得到相同结果
    """
    combined = f"{user_id}-{route_id}".encode('utf-8')
    hash_value = hashlib.md5(combined).hexdigest()
    return int(hash_value, 16) % 101


def select_route_for_user(
    routes: List[RouteInfo],
    user_id: int,
    region: Optional[str] = None
) -> Optional[RouteInfo]:
    """
    线路选择算法（用户端版本）

    规则优先级：
    1. denyUserIds 排除（用户端不提供此字段，跳过）
    2. allowUserIds 优先匹配（用户端不提供此字段，跳过）
    3. enabled=false 或 status!=ok 排除（用户端只获取 enabled 的）
    4. regionScope 不匹配降权/排除
    5. percent 灰度使用 userId 稳定 hash（用户端不提供此字段，跳过）
    6. 按 priority 升序排序，选最优
    """
    if not routes:
        return None

    # 地区匹配
    if region:
        region_matches = [
            r for r in routes
            if region in (r.region_scope or ['GLOBAL']) or 'GLOBAL' in (r.region_scope or [])
        ]
        if region_matches:
            routes = region_matches
        else:
            # 降级到 GLOBAL 线路
            routes = [r for r in routes if 'GLOBAL' in (r.region_scope or [])]

    if not routes:
        return None

    # 按 priority 选最优
    return min(routes, key=lambda r: r.priority)


# ============================================================
# 从配置中心获取线路
# ============================================================

async def fetch_routes_from_config() -> List[RouteInfo]:
    """
    从管理后台配置中心获取线路

    通过内部 API 调用获取启用的线路列表
    """
    import os
    import httpx

    admin_backend_url = os.getenv('ADMIN_BACKEND_URL', 'http://royalbot_admin_backend:8080')

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # 调用管理后台的公开接口获取线路
            response = await client.get(
                f"{admin_backend_url}/api/routes/public",
                headers={"X-Internal-Call": "true"},
                follow_redirects=True
            )

            if response.status_code == 200:
                data = response.json()
                # 转换为 RouteInfo
                return [
                    RouteInfo(
                        id=r['id'],
                        name=r['name'],
                        description=r.get('description'),
                        priority=r['priority'],
                        domain=r['domain'],
                        tls=r['tls'],
                        base_path=r['base_path'],
                        tags=r['tags'],
                        region_scope=r['region_scope'],
                        worker_route=r.get('worker_route'),
                        origin_type=r.get('origin_type', 'emby'),
                    )
                    for r in data
                ]
            else:
                logger.warning(f"Failed to fetch routes from config: {response.status_code}")
                return []
    except Exception as e:
        logger.warning(f"Error fetching routes from config: {e}")
        return []


async def get_available_routes(
    user_id: Optional[int] = None,
    region: Optional[str] = None
) -> List[RouteInfo]:
    """
    获取可用线路，支持兼容回退

    优先级：
    1. Feature Flag 关闭 → 返回默认线路
    2. 配置中心无数据/异常 → 返回默认线路
    3. 正常返回配置中心线路
    """
    # 检查 Feature Flag
    if not check_route_config_enabled():
        logger.debug("Route config feature disabled, using defaults")
        return get_default_routes()

    # 尝试从配置中心获取
    try:
        config_routes = await fetch_routes_from_config()

        if not config_routes:
            logger.debug("No routes from config center, using defaults")
            return get_default_routes()

        return config_routes
    except Exception as e:
        logger.warning(f"Failed to get routes from config: {e}, using defaults")
        return get_default_routes()


# ============================================================
# API 路由
# ============================================================

@router.get("/", response_model=List[RouteInfo])
async def list_routes(
    region: Optional[str] = Query(None, description="地区代码"),
    current_user: Optional[WebUser] = Depends(get_current_user_optional),
):
    """
    获取可用线路列表

    - 支持按地区筛选
    - 配置中心不可用时自动回退到默认线路
    - 不需要登录（游客也可获取，用于展示）
    """
    routes = await get_available_routes(
        user_id=current_user.id if current_user else None,
        region=region
    )

    return routes


@router.get("/active", response_model=Optional[RouteInfo])
async def get_active_route(
    region: Optional[str] = Query(None, description="地区代码"),
    current_user: Optional[WebUser] = Depends(get_current_user_optional),
):
    """
    获取当前激活的线路（根据用户选择算法）

    - 需要登录才能获取个人化的线路选择
    - 游客返回第一个可用线路
    """
    routes = await get_available_routes(
        user_id=current_user.id if current_user else None,
        region=region
    )

    if not routes:
        return None

    if current_user:
        # 登录用户：使用选择算法
        return select_route_for_user(routes, current_user.id, region)
    else:
        # 游客：返回优先级最高的线路
        return min(routes, key=lambda r: r.priority)


@router.get("/debug", response_model=dict)
async def debug_routes(
    current_user: Optional[WebUser] = Depends(get_current_user_optional),
):
    """
    调试接口：返回线路选择相关的调试信息

    包含：
    - Feature Flag 状态
    - 配置中心连接状态
    - 可用线路数量
    - 用户信息
    """
    feature_enabled = check_route_config_enabled()

    routes = await get_available_routes(
        user_id=current_user.id if current_user else None,
        region=None
    )

    # 检查配置中心连接
    config_center_ok = False
    if feature_enabled:
        try:
            config_routes = await fetch_routes_from_config()
            config_center_ok = len(config_routes) > 0
        except:
            pass

    return {
        "feature_enabled": feature_enabled,
        "config_center_ok": config_center_ok,
        "total_routes": len(routes),
        "user_id": current_user.id if current_user else None,
        "is_logged_in": current_user is not None,
        "routes": [
            {
                "id": r.id,
                "name": r.name,
                "domain": r.domain,
                "priority": r.priority,
            }
            for r in routes[:5]  # 只返回前5个
        ],
    }
