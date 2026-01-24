"""
线路管理 Pydantic 模型

用于线路配置中心的数据验证和序列化
"""
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Literal
from datetime import datetime


# ============================================================
# 基础字段
# ============================================================

class RouteBase(BaseModel):
    """线路基础字段"""
    name: str = Field(..., min_length=1, max_length=100, description="线路名称")
    description: Optional[str] = Field(None, description="线路描述")
    enabled: bool = Field(True, description="是否启用")
    priority: int = Field(default=100, ge=0, le=999, description="优先级（越小越优先）")
    tags: List[str] = Field(default_factory=list, description="标签")
    region_scope: List[str] = Field(
        default_factory=lambda: ['GLOBAL'],
        description="地区范围，['GLOBAL'] 表示全球"
    )


# ============================================================
# Domain 层
# ============================================================

class RouteDomain(BaseModel):
    """域名入口配置"""
    domain: str = Field(..., min_length=1, description="域名")
    tls: bool = Field(True, description="是否使用 HTTPS")
    base_path: str = Field(default="", max_length=100, description="基础路径")


# ============================================================
# Worker 层
# ============================================================

class RouteWorker(BaseModel):
    """Worker/路由配置"""
    worker_route: Optional[str] = Field(None, description="Cloudflare Worker 路由")
    origin_type: Literal['emby', 'jellyfin', 'http'] = Field(
        default='emby',
        description="源类型"
    )
    rewrite_from: Optional[str] = Field(None, description="重写源路径")
    rewrite_to: Optional[str] = Field(None, description="重写目标路径")
    headers: Dict[str, str] = Field(default_factory=dict, description="额外请求头")
    auth_mode: Literal['none', 'token', 'basic'] = Field(
        default='none',
        description="认证模式（预留）"
    )
    cache_mode: Literal['bypass', 'basic', 'aggressive'] = Field(
        default='bypass',
        description="缓存模式（预留）"
    )


# ============================================================
# 状态和灰度
# ============================================================

class RouteStatus(BaseModel):
    """状态和灰度配置"""
    status: Literal['ok', 'maintenance', 'degraded', 'down'] = Field(
        default='ok',
        description="线路状态"
    )
    maintenance_message: Optional[str] = Field(None, description="维护模式消息")
    rollout_percent: int = Field(
        default=100,
        ge=0,
        le=100,
        description="灰度百分比 0-100"
    )
    rollout_allow_user_ids: List[int] = Field(
        default_factory=list,
        description="白名单用户ID列表"
    )
    rollout_deny_user_ids: List[int] = Field(
        default_factory=list,
        description="黑名单用户ID列表"
    )


# ============================================================
# 健康检查
# ============================================================

class RouteHealth(BaseModel):
    """健康检查配置"""
    health_url: Optional[str] = Field(None, description="健康检查URL")
    health_expect_status: int = Field(default=200, description="期望HTTP状态码")
    health_timeout_ms: int = Field(default=5000, ge=1000, le=30000, description="超时时间(毫秒)")
    health_interval_sec: int = Field(default=60, ge=10, le=600, description="检查间隔(秒)")
    # 只读字段（由系统更新）
    health_last_ok_at: Optional[datetime] = Field(None, description="最后成功时间")
    health_last_latency_ms: Optional[int] = Field(None, description="最后延迟(毫秒)")
    health_fail_count: int = Field(default=0, description="失败次数")


# ============================================================
# 完整模型
# ============================================================

class RouteCreate(RouteBase, RouteDomain, RouteWorker, RouteStatus, RouteHealth):
    """创建线路（完整配置）"""
    pass


class RouteUpdate(BaseModel):
    """更新线路（所有字段可选）"""
    # 基础
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0, le=999)
    tags: Optional[List[str]] = None
    region_scope: Optional[List[str]] = None
    # Domain
    domain: Optional[str] = None
    tls: Optional[bool] = None
    base_path: Optional[str] = None
    # Worker
    worker_route: Optional[str] = None
    origin_type: Optional[Literal['emby', 'jellyfin', 'http']] = None
    rewrite_from: Optional[str] = None
    rewrite_to: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    auth_mode: Optional[Literal['none', 'token', 'basic']] = None
    cache_mode: Optional[Literal['bypass', 'basic', 'aggressive']] = None
    # Status
    status: Optional[Literal['ok', 'maintenance', 'degraded', 'down']] = None
    maintenance_message: Optional[str] = None
    rollout_percent: Optional[int] = Field(None, ge=0, le=100)
    rollout_allow_user_ids: Optional[List[int]] = None
    rollout_deny_user_ids: Optional[List[int]] = None
    # Health
    health_url: Optional[str] = None
    health_expect_status: Optional[int] = None
    health_timeout_ms: Optional[int] = None
    health_interval_sec: Optional[int] = None


class RouteResponse(RouteBase, RouteDomain, RouteWorker, RouteStatus, RouteHealth):
    """线路响应（完整）"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RouteListItem(BaseModel):
    """列表项（简化版）"""
    id: int
    name: str
    description: Optional[str]
    enabled: bool
    priority: int
    status: str
    domain: str
    tags: List[str]
    region_scope: List[str]
    health_last_ok_at: Optional[datetime]
    health_fail_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 操作相关
# ============================================================

class RouteToggleRequest(BaseModel):
    """启用/禁用请求"""
    enabled: bool = Field(..., description="启用状态")


class RouteMaintenanceRequest(BaseModel):
    """维护模式请求"""
    status: Literal['ok', 'maintenance', 'degraded', 'down'] = Field(
        ...,
        description="状态"
    )
    maintenance_message: Optional[str] = Field(None, description="维护消息")


class RoutePriorityRequest(BaseModel):
    """优先级调整请求"""
    priority: int = Field(..., ge=0, le=999, description="新优先级")


class RouteCopyRequest(BaseModel):
    """复制线路请求"""
    name: str = Field(..., min_length=1, max_length=100, description="新线路名称")


# ============================================================
# 策略预览
# ============================================================

class RoutePreviewRequest(BaseModel):
    """策略预览请求"""
    user_id: Optional[int] = Field(None, description="用户ID")
    tg_id: Optional[int] = Field(None, description="Telegram ID")
    emby_user_id: Optional[str] = Field(None, description="Emby 用户ID")
    anon_id: Optional[str] = Field(None, description="匿名用户ID (localStorage)")
    region: Optional[str] = Field(None, description="地区代码")
    device: Optional[str] = Field(None, description="设备类型")

    @property
    def sticky_key(self) -> str:
        """
        获取稳定分流 key，优先级：
        tg_id > emby_user_id > user_id > anon_id
        """
        if self.tg_id:
            return f"tg:{self.tg_id}"
        if self.emby_user_id:
            return f"emby:{self.emby_user_id}"
        if self.user_id:
            return f"user:{self.user_id}"
        if self.anon_id:
            return f"anon:{self.anon_id}"
        return "unknown"


class RoutePreviewDebugInfo(BaseModel):
    """预览调试信息"""
    total_routes: int
    enabled_routes: int
    status_ok_routes: int
    region_matched: bool
    in_allow_list: bool
    in_deny_list: bool
    rollout_passed: bool
    hash_value: Optional[int] = None
    matched_rules: List[str] = Field(default_factory=list)


class RoutePreviewResponse(BaseModel):
    """策略预览响应"""
    selected_route: Optional[RouteResponse] = Field(None, description="选中的线路")
    available_routes: List[RouteResponse] = Field(default_factory=list, description="可用线路列表")
    explanation: str = Field(..., description="选择原因说明")
    debug_info: RoutePreviewDebugInfo = Field(..., description="调试信息")


# ============================================================
# 批量操作
# ============================================================

class RouteBatchUpdateRequest(BaseModel):
    """批量更新请求"""
    route_ids: List[int] = Field(..., min_items=1, description="线路ID列表")
    enabled: Optional[bool] = Field(None, description="统一设置启用状态")
    status: Optional[Literal['ok', 'maintenance', 'degraded', 'down']] = Field(
        None,
        description="统一设置状态"
    )


class RouteBatchUpdateResponse(BaseModel):
    """批量更新响应"""
    updated_count: int
    failed_ids: List[int] = Field(default_factory=list)


# ============================================================
# 健康检查响应
# ============================================================

class RouteHealthCheckResponse(BaseModel):
    """健康检查响应"""
    route_id: int
    route_name: str
    is_healthy: bool
    status_code: Optional[int] = None
    latency_ms: Optional[int] = None
    error_message: Optional[str] = None
    checked_at: datetime


# ============================================================
# 默认线路（兼容回退）
# ============================================================

class DefaultRoute(BaseModel):
    """默认线路配置（用于回退）"""
    id: int = -1  # 负ID表示默认线路
    name: str = "默认线路"
    description: str = "系统默认线路（配置中心不可用时）"
    enabled: bool = True
    priority: int = 999
    status: str = "ok"
    domain: str = ""
    tls: bool = True
    base_path: str = ""
    worker_route: Optional[str] = None
    tags: List[str] = ["default"]
    region_scope: List[str] = ["GLOBAL"]
