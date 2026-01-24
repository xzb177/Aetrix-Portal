# 线路管理后台（Routes Config Center）设计文档

## 一、项目概述

**目标**：为 RoyalBot-Portal 新增"线路管理后台"，支持多域名入口 + Cloudflare Worker 多路由配置。

**核心原则**：
- 轻量设计，最小化改动
- 兼容现有逻辑，可一键回滚
- 配置中心故障时自动降级

---

## 二、数据结构设计

### 2.1 数据库表：`routes`

```sql
CREATE TABLE routes (
    -- 基础字段
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 100,
    tags TEXT[],                    -- 标签数组: ['primary', 'backup', 'cf-worker']
    region_scope TEXT[],            -- 地区范围: ['CN', 'US', 'GLOBAL']
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Domain 层
    domain VARCHAR(255) NOT NULL,
    tls BOOLEAN DEFAULT TRUE,
    base_path VARCHAR(100) DEFAULT '',

    -- Worker 层
    worker_route VARCHAR(255),      -- Cloudflare Worker 路由
    origin_type VARCHAR(50) DEFAULT 'emby',  -- emby, jellyfin, http
    rewrite_from VARCHAR(255),     -- 重写源路径
    rewrite_to VARCHAR(255),       -- 重写目标路径
    headers JSONB,                 -- 额外请求头 {"X-Custom": "value"}
    auth_mode VARCHAR(50) DEFAULT 'none',  -- none, token, basic (预留)
    cache_mode VARCHAR(50) DEFAULT 'bypass',  -- bypass, basic, aggressive (预留)

    -- 状态和灰度
    status VARCHAR(20) NOT NULL DEFAULT 'ok',  -- ok, maintenance, degraded, down
    maintenance_message TEXT,
    rollout_percent INTEGER DEFAULT 100,
    rollout_allow_user_ids INTEGER[],   -- 允许的用户ID列表
    rollout_deny_user_ids INTEGER[],    -- 拒绝的用户ID列表

    -- 健康检查
    health_url VARCHAR(500),
    health_expect_status INTEGER DEFAULT 200,
    health_timeout_ms INTEGER DEFAULT 5000,
    health_interval_sec INTEGER DEFAULT 60,
    health_last_ok_at TIMESTAMP,
    health_last_latency_ms INTEGER,
    health_fail_count INTEGER DEFAULT 0
);

-- 索引
CREATE INDEX idx_routes_enabled ON routes(enabled) WHERE enabled = TRUE;
CREATE INDEX idx_routes_priority ON routes(priority);
CREATE INDEX idx_routes_status ON routes(status);
CREATE INDEX idx_routes_tags ON routes USING GIN(tags);
CREATE INDEX idx_routes_region ON routes USING GIN(region_scope);

-- 触发器：更新 updated_at
CREATE TRIGGER update_routes_updated_at
    BEFORE UPDATE ON routes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

### 2.2 Pydantic 模型

```python
# admin_backend/schemas/route.py
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Literal
from datetime import datetime

class RouteBase(BaseModel):
    """基础字段"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=999)
    tags: List[str] = Field(default_factory=list)
    region_scope: List[str] = Field(default_factory=lambda: ['GLOBAL'])

class RouteDomain(BaseModel):
    """Domain 层配置"""
    domain: str = Field(..., min_length=1)
    tls: bool = True
    base_path: str = Field(default="")

class RouteWorker(BaseModel):
    """Worker 层配置"""
    worker_route: Optional[str] = None
    origin_type: Literal['emby', 'jellyfin', 'http'] = 'emby'
    rewrite_from: Optional[str] = None
    rewrite_to: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    auth_mode: Literal['none', 'token', 'basic'] = 'none'
    cache_mode: Literal['bypass', 'basic', 'aggressive'] = 'bypass'

class RouteStatus(BaseModel):
    """状态和灰度"""
    status: Literal['ok', 'maintenance', 'degraded', 'down'] = 'ok'
    maintenance_message: Optional[str] = None
    rollout_percent: int = Field(default=100, ge=0, le=100)
    rollout_allow_user_ids: List[int] = Field(default_factory=list)
    rollout_deny_user_ids: List[int] = Field(default_factory=list)

class RouteHealth(BaseModel):
    """健康检查配置"""
    health_url: Optional[str] = None
    health_expect_status: int = Field(default=200)
    health_timeout_ms: int = Field(default=5000, ge=1000, le=30000)
    health_interval_sec: int = Field(default=60, ge=10, le=600)
    # 只读字段
    health_last_ok_at: Optional[datetime] = None
    health_last_latency_ms: Optional[int] = None
    health_fail_count: int = Field(default=0)

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
    """线路响应"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class RouteListItem(BaseModel):
    """列表项（简化版）"""
    id: int
    name: str
    enabled: bool
    priority: int
    status: str
    domain: str
    tags: List[str]
    health_last_ok_at: Optional[datetime]
    health_fail_count: int

class RoutePreviewRequest(BaseModel):
    """策略预览请求"""
    user_id: int
    region: Optional[str] = None
    device: Optional[str] = None

class RoutePreviewResponse(BaseModel):
    """策略预览响应"""
    selected_route: Optional[RouteResponse]
    available_routes: List[RouteResponse]
    explanation: str
    debug_info: Dict[str, any]
```

---

## 三、API 设计

### 3.1 管理后台 API (admin_backend)

**路由前缀**: `/api/routes`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/routes` | 获取线路列表 | routes.view |
| GET | `/api/routes/{id}` | 获取线路详情 | routes.view |
| POST | `/api/routes` | 创建线路 | routes.create |
| PUT | `/api/routes/{id}` | 更新线路 | routes.update |
| DELETE | `/api/routes/{id}` | 删除线路 | routes.delete |
| POST | `/api/routes/{id}/toggle` | 启用/禁用 | routes.update |
| POST | `/api/routes/{id}/maintenance` | 设置维护模式 | routes.update |
| POST | `/api/routes/{id}/copy` | 复制线路 | routes.create |
| PUT | `/api/routes/{id}/priority` | 调整优先级 | routes.update |
| POST | `/api/routes/preview` | 策略预览 | routes.view |
| POST | `/api/routes/{id}/health-check` | 手动健康检查 | routes.update |

### 3.2 用户端 API (user_backend)

**路由前缀**: `/api/user/routes`

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| GET | `/api/user/routes` | 获取可用线路列表 | 需登录 |
| GET | `/api/user/routes/active` | 获取当前激活线路 | 需登录 |

### 3.3 兼容回退机制

```python
# user_backend/api/routes.py
async def get_available_routes(
    user_id: int,
    region: Optional[str] = None,
    feature_enabled: bool = True  # Feature Flag
) -> List[RouteResponse]:
    """
    获取可用线路，支持兼容回退

    优先级：
    1. Feature Flag 关闭 → 返回默认线路
    2. 配置中心无数据/异常 → 返回默认线路
    3. 正常返回配置中心线路
    """
    if not feature_enabled:
        return get_default_routes()

    try:
        routes = await fetch_routes_from_admin()
        if not routes:
            return get_default_routes()
        return filter_routes(routes, user_id, region)
    except Exception as e:
        logger.warning(f"Failed to fetch routes: {e}, using defaults")
        return get_default_routes()
```

---

## 四、文件清单

### 4.1 新增文件

**后端 - admin_backend**
```
admin_backend/
├── api/
│   └── routes.py                 # 线路管理 API
├── schemas/
│   └── route.py                  # Pydantic 模型
├── services/
│   ├── route_service.py          # 线路业务逻辑
│   └── health_checker.py         # 健康检查服务
└── database/
    └── migrations/
        └── 001_create_routes.sql # 数据库迁移
```

**后端 - user_backend**
```
user_backend/
├── api/
│   └── routes.py                 # 用户端线路查询 API
└── services/
    └── route_selector.py         # 线路选择逻辑
```

**前端 - admin_frontend**
```
admin_frontend/src/
├── views/
│   └── Routes.vue                # 线路管理页面
├── components/
│   └── routes/
│       ├── RouteList.vue         # 线路列表
│       ├── RouteEditor.vue       # 线路编辑器
│       └── RoutePreview.vue      # 策略预览
├── api/
│   └── routes.ts                 # API 调用封装
└── types/
    └── route.ts                  # TypeScript 类型
```

**前端 - user_frontend**
```
user_frontend/src/
├── composables/
│   └── useRouteSelector.ts       # 线路选择 Composable
└── config/
    └── featureFlags.ts           # 更新 Feature Flags
```

### 4.2 修改文件

```
# admin_backend
main.py                            # 注册路由
admin_utils/config.py              # 添加 Feature Flag 配置

# user_backend
main.py                            # 注册路由
api/emby.py                        # 集成线路选择逻辑

# admin_frontend
router/index.ts                    # 添加路由
src/layouts/AdminLayout.vue        # 添加菜单项

# user_frontend
components/PlayerSelectorSheet.vue # 集成线路选择
src/api/index.ts                   # 添加 routes API
```

---

## 五、Feature Flags 配置

### 5.1 后端配置 (admin_backend/admin_utils/config.py)

```python
# Feature Flags
FEATURE_ROUTE_ADMIN: bool = Field(
    default=False,
    description="启用线路管理后台功能"
)
FEATURE_ROUTE_CONFIG: bool = Field(
    default=False,
    description="启用线路配置中心功能"
)
```

### 5.2 前端配置 (user_frontend/src/config/featureFlags.ts)

```typescript
interface FeatureFlagConfig {
  // ... 现有 flags
  ROUTE_SELECTOR: boolean      // 启用线路选择器
  ROUTE_ADVANCED: boolean      // 启用高级线路功能
}

const DEFAULT_FLAGS: FeatureFlagConfig = {
  // ...
  ROUTE_SELECTOR: false,
  ROUTE_ADVANCED: false,
}
```

---

## 六、线路选择算法

```python
# user_backend/services/route_selector.py
def select_route(
    routes: List[Route],
    user_id: int,
    region: Optional[str] = None
) -> Optional[Route]:
    """
    线路选择算法

    规则优先级：
    1. denyUserIds 排除
    2. allowUserIds 优先匹配
    3. enabled=false 或 status!=ok 排除
    4. regionScope 不匹配降权/排除
    5. percent 灰度使用 userId 稳定 hash
    6. 按 priority 升序排序，选最优
    """
    # 1. 过滤排除规则
    candidates = [
        r for r in routes
        if r.enabled
        and r.status == 'ok'
        and user_id not in (r.rollout_deny_user_ids or [])
    ]

    # 2. 白名单优先
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
            if region in (r.region_scope or ['GLOBAL'])
        ]
        if region_matches:
            candidates = region_matches
        else:
            # 降级到 GLOBAL 线路
            candidates = [r for r in candidates if 'GLOBAL' in (r.region_scope or [])]

    if not candidates:
        return None

    # 4. 灰度分流
    def hash_percent(uid: int, route_id: int) -> int:
        """稳定 hash，返回 0-100 */
        combined = f"{uid}-{route_id}".encode()
        return int(hashlib.md5(combined).hexdigest(), 16) % 101

    for route in candidates:
        hp = hash_percent(user_id, route.id)
        if hp <= (route.rollout_percent or 100):
            return route

    # 5. 按 priority 选最优
    return min(candidates, key=lambda r: r.priority)
```

---

## 七、自测清单

### 7.1 后端自测

- [ ] 数据库表创建成功
- [ ] CRUD API 正常工作
- [ ] Feature Flag 关闭时 API 返回 404/禁用
- [ ] 权限控制正常（非管理员无法访问）
- [ ] 健康检查功能正常
- [ ] 策略预览算法正确

### 7.2 前端自测（管理后台）

- [ ] 菜单显示/隐藏受 Feature Flag 控制
- [ ] 线路列表正常加载
- [ ] 创建/编辑/删除线路正常
- [ ] 启用/禁用/维护模式切换正常
- [ ] 优先级调整正常
- [ ] 复制线路功能正常
- [ ] 策略预览功能正常

### 7.3 前端自测（用户端）

- [ ] Feature Flag 关闭时使用默认线路
- [ ] Feature Flag 开启时从配置中心读取
- [ ] 配置中心异常时自动回退到默认
- [ ] 线路选择算法正确执行
- [ ] 白名单用户优先匹配
- [ ] 黑名单用户被排除
- [ ] 灰度分流正确
- [ ] 地区匹配正确

### 7.4 兼容性自测

- [ ] 现有 Emby 账号获取不受影响
- [ ] 播放器导入功能正常
- [ ] 无线路配置时降级正常

---

## 八、回滚方式

### 8.1 一键回滚（Feature Flag）

**后端**：修改环境变量或数据库配置
```bash
# docker-compose.yml 或 .env
FEATURE_ROUTE_ADMIN=false
FEATURE_ROUTE_CONFIG=false
```

**前端**：浏览器控制台或 localStorage
```javascript
localStorage.setItem('feature_flags', JSON.stringify({
  ROUTE_SELECTOR: false
}))
```

### 8.2 代码回滚

```bash
# Git 回滚
git revert <commit-hash>

# 或删除功能文件
rm admin_backend/api/routes.py
rm user_backend/api/routes.py
rm admin_frontend/src/views/Routes.vue
```

### 8.3 数据库回滚

```sql
-- 禁用线路（软删除）
UPDATE routes SET enabled = FALSE;

-- 或直接删除表
DROP TABLE IF EXISTS routes CASCADE;
```

---

## 九、安全考虑

1. **敏感字段保护**
   - `auth_mode=token` 时，token 字段不在前端暴露
   - 使用 `**` 遮罩显示敏感信息

2. **权限控制**
   - 复用现有 RBAC 体系
   - 新增权限：`routes.view`, `routes.create`, `routes.update`, `routes.delete`

3. **审计日志**
   - 所有线路修改操作记录日志
   - 记录操作人、时间、变更内容

4. **限流保护**
   - API 限流：100次/分钟
   - 防止滥用

---

## 十、部署步骤

1. **数据库迁移**
   ```bash
   docker exec royalbot_postgres psql -U royalbot -d royalbot -f /scripts/001_create_routes.sql
   ```

2. **环境变量配置**
   ```bash
   # docker-compose.yml
   environment:
     - FEATURE_ROUTE_ADMIN=true
     - FEATURE_ROUTE_CONFIG=true
   ```

3. **构建部署**
   ```bash
   docker compose build admin_backend user_backend admin_frontend
   docker compose up -d admin_backend user_backend admin_frontend
   ```

4. **验证**
   ```bash
   curl -H "Authorization: Bearer <token>" https://admin/api/routes
   ```
