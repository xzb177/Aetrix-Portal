-- 线路管理表
-- 创建时间: 2026-01-20
-- 说明: 支持多域名入口 + Cloudflare Worker 多路由配置

CREATE TABLE IF NOT EXISTS routes (
    -- ========== 基础字段 ==========
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 100,
    tags TEXT[],                    -- 标签数组: ['primary', 'backup', 'cf-worker']
    region_scope TEXT[],            -- 地区范围: ['CN', 'US', 'GLOBAL', '*']
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- ========== Domain 层 ==========
    domain VARCHAR(255) NOT NULL,
    tls BOOLEAN DEFAULT TRUE,
    base_path VARCHAR(100) DEFAULT '',

    -- ========== Worker 层 ==========
    worker_route VARCHAR(255),      -- Cloudflare Worker 路由
    origin_type VARCHAR(50) DEFAULT 'emby',  -- emby, jellyfin, http
    rewrite_from VARCHAR(255),     -- 重写源路径
    rewrite_to VARCHAR(255),       -- 重写目标路径
    headers JSONB DEFAULT '{}',     -- 额外请求头 {"X-Custom": "value"}
    auth_mode VARCHAR(50) DEFAULT 'none',  -- none, token, basic (预留)
    cache_mode VARCHAR(50) DEFAULT 'bypass',  -- bypass, basic, aggressive (预留)

    -- ========== 状态和灰度 ==========
    status VARCHAR(20) NOT NULL DEFAULT 'ok',  -- ok, maintenance, degraded, down
    maintenance_message TEXT,
    rollout_percent INTEGER DEFAULT 100 CHECK (rollout_percent >= 0 AND rollout_percent <= 100),
    rollout_allow_user_ids INTEGER[],   -- 允许的用户ID列表
    rollout_deny_user_ids INTEGER[],    -- 拒绝的用户ID列表

    -- ========== 健康检查 ==========
    health_url VARCHAR(500),
    health_expect_status INTEGER DEFAULT 200,
    health_timeout_ms INTEGER DEFAULT 5000,
    health_interval_sec INTEGER DEFAULT 60,
    health_last_ok_at TIMESTAMP,
    health_last_latency_ms INTEGER,
    health_fail_count INTEGER DEFAULT 0,

    -- 约束
    CONSTRAINT routes_name_check CHECK (name != ''),
    CONSTRAINT routes_priority_check CHECK (priority >= 0 AND priority <= 999),
    CONSTRAINT routes_status_check CHECK (status IN ('ok', 'maintenance', 'degraded', 'down')),
    CONSTRAINT routes_auth_mode_check CHECK (auth_mode IN ('none', 'token', 'basic')),
    CONSTRAINT routes_cache_mode_check CHECK (cache_mode IN ('bypass', 'basic', 'aggressive')),
    CONSTRAINT routes_origin_type_check CHECK (origin_type IN ('emby', 'jellyfin', 'http'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_routes_enabled ON routes(enabled) WHERE enabled = TRUE;
CREATE INDEX IF NOT EXISTS idx_routes_priority ON routes(priority);
CREATE INDEX IF NOT EXISTS idx_routes_status ON routes(status);
CREATE INDEX IF NOT EXISTS idx_routes_tags ON routes USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_routes_region ON routes USING GIN(region_scope);
CREATE INDEX IF NOT EXISTS idx_routes_rollout_allow ON routes USING GIN(rollout_allow_user_ids);
CREATE INDEX IF NOT EXISTS idx_routes_rollout_deny ON routes USING GIN(rollout_deny_user_ids);

-- 触发器：更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_routes_updated_at ON routes;
CREATE TRIGGER update_routes_updated_at
    BEFORE UPDATE ON routes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 注释
COMMENT ON TABLE routes IS '线路配置表，支持多域名入口和 Cloudflare Worker 路由';
COMMENT ON COLUMN routes.id IS '线路ID';
COMMENT ON COLUMN routes.name IS '线路名称，如"主线路 CF Worker"';
COMMENT ON COLUMN routes.enabled IS '是否启用';
COMMENT ON COLUMN routes.priority IS '优先级，越小越优先（0-999）';
COMMENT ON COLUMN routes.tags IS '标签数组，用于分类和筛选';
COMMENT ON COLUMN routes.region_scope IS '地区范围，["GLOBAL"] 表示全球';
COMMENT ON COLUMN routes.domain IS '域名入口';
COMMENT ON COLUMN routes.tls IS '是否使用 HTTPS';
COMMENT ON COLUMN routes.worker_route IS 'Cloudflare Worker 路由';
COMMENT ON COLUMN routes.status IS '线路状态：ok=正常, maintenance=维护中, degraded=降级, down=宕机';
COMMENT ON COLUMN routes.rollout_percent IS '灰度百分比 0-100';
COMMENT ON COLUMN routes.health_last_ok_at IS '最后一次健康检查成功时间';
COMMENT ON COLUMN routes.health_fail_count IS '健康检查失败次数';
