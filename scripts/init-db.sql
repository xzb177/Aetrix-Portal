-- RoyalBot Portal PostgreSQL 初始化脚本
-- 此脚本在 PostgreSQL 容器首次启动时自动执行

-- 创建枚举类型
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subscription_status_enum') THEN
        CREATE TYPE subscription_status_enum AS ENUM ('active', 'expired', 'cancelled', 'pending');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'request_status_enum') THEN
        CREATE TYPE request_status_enum AS ENUM ('pending', 'approved', 'rejected', 'completed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_status_enum') THEN
        CREATE TYPE order_status_enum AS ENUM ('pending', 'paid', 'failed', 'cancelled');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_method_enum') THEN
        CREATE TYPE payment_method_enum AS ENUM ('yipay', 'alipay', 'wxpay', 'balance');
    END IF;
END $$;

-- 用户端表

CREATE TABLE IF NOT EXISTS web_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    telegram_id BIGINT UNIQUE,
    is_active BOOLEAN DEFAULT TRUE,
    is_staff BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_web_users_telegram_id ON web_users(telegram_id);

CREATE TABLE IF NOT EXISTS subscription_plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    duration_days INTEGER NOT NULL,
    features TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_popular BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recharge_packages (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    amount INTEGER NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    bonus INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    is_popular BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    plan_id INTEGER NOT NULL REFERENCES subscription_plans(id),
    start_date TIMESTAMP,
    end_date TIMESTAMP NOT NULL,
    status subscription_status_enum DEFAULT 'active',
    auto_renew BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user ON user_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_status ON user_subscriptions(status);

CREATE TABLE IF NOT EXISTS movie_requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    movie_name VARCHAR(255) NOT NULL,
    year VARCHAR(10),
    type VARCHAR(50),
    note TEXT,
    status request_status_enum DEFAULT 'pending',
    admin_note TEXT,
    emby_item_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_movie_requests_user ON movie_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_movie_requests_status ON movie_requests(status);

CREATE TABLE IF NOT EXISTS recharge_orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    package_id INTEGER NOT NULL REFERENCES recharge_packages(id),
    amount INTEGER NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    payment_method payment_method_enum,
    status order_status_enum DEFAULT 'pending',
    payment_url VARCHAR(500),
    paid_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_recharge_orders_user ON recharge_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_recharge_orders_status ON recharge_orders(status);

CREATE TABLE IF NOT EXISTS subscription_orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    plan_id INTEGER NOT NULL REFERENCES subscription_plans(id),
    item_name VARCHAR(255),
    amount DECIMAL(10,2) NOT NULL,
    payment_method payment_method_enum,
    status order_status_enum DEFAULT 'pending',
    payment_url VARCHAR(500),
    paid_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_subscription_orders_user ON subscription_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_subscription_orders_status ON subscription_orders(status);

-- Emby 相关表

CREATE TABLE IF NOT EXISTS emby_servers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    url VARCHAR(500) NOT NULL,
    host VARCHAR(255),
    port INTEGER,
    api_key VARCHAR(255) NOT NULL,
    max_users INTEGER DEFAULT 0,
    current_users INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plan_server_relations (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES subscription_plans(id) ON DELETE CASCADE,
    server_id INTEGER NOT NULL REFERENCES emby_servers(id) ON DELETE CASCADE,
    weight INTEGER DEFAULT 1,
    UNIQUE(plan_id, server_id)
);

CREATE TABLE IF NOT EXISTS user_emby_accounts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    server_id INTEGER NOT NULL REFERENCES emby_servers(id) ON DELETE CASCADE,
    emby_user_id VARCHAR(100),
    username VARCHAR(100) NOT NULL,
    password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, server_id)
);
CREATE INDEX IF NOT EXISTS idx_user_emby_accounts_user ON user_emby_accounts(user_id);

-- 公告和工单表

CREATE TABLE IF NOT EXISTS announcements (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    type VARCHAR(20) DEFAULT 'system',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    category VARCHAR(50),
    priority VARCHAR(20) DEFAULT 'normal',
    status VARCHAR(20) DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES web_users(id),
    is_admin BOOLEAN DEFAULT FALSE,
    message TEXT NOT NULL,
    attachment_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket ON ticket_messages(ticket_id);

-- 邀请系统表

CREATE TABLE IF NOT EXISTS invitation_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,
    user_id INTEGER REFERENCES web_users(id) ON DELETE SET NULL,
    max_uses INTEGER DEFAULT -1,
    use_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invitation_records (
    id SERIAL PRIMARY KEY,
    inviter_id INTEGER NOT NULL REFERENCES web_users(id),
    invitee_id INTEGER REFERENCES web_users(id),
    code_id INTEGER REFERENCES invitation_codes(id),
    code VARCHAR(20),
    reward_points INTEGER DEFAULT 0,
    inviter_reward INTEGER DEFAULT 0,
    invitee_reward INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'completed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_invitation_records_inviter ON invitation_records(inviter_id);

-- 兑换码表

CREATE TABLE IF NOT EXISTS exchange_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    type INTEGER NOT NULL DEFAULT 1,
    exchange_count INTEGER NOT NULL DEFAULT 1,
    status INTEGER NOT NULL DEFAULT 0,
    used_by_user_id INTEGER REFERENCES web_users(id) ON DELETE SET NULL,
    used_at TIMESTAMP,
    created_by_admin_id INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_exchange_codes_code ON exchange_codes(code);
CREATE INDEX IF NOT EXISTS idx_exchange_codes_status ON exchange_codes(status);
CREATE INDEX IF NOT EXISTS idx_exchange_codes_user ON exchange_codes(used_by_user_id);
CREATE INDEX IF NOT EXISTS idx_exchange_codes_admin ON exchange_codes(created_by_admin_id);

-- 系统配置表

CREATE TABLE IF NOT EXISTS system_configs (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 管理后台表

CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'admin',
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_logs (
    id SERIAL PRIMARY KEY,
    admin_id INTEGER NOT NULL REFERENCES admin_users(id),
    admin_username VARCHAR(50),
    action VARCHAR(100) NOT NULL,
    resource VARCHAR(100),
    resource_id VARCHAR(100),
    details JSONB,
    ip_address VARCHAR(50),
    user_agent VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id);
CREATE INDEX IF NOT EXISTS idx_admin_logs_action ON admin_logs(action);

-- 插入默认系统配置
INSERT INTO system_configs (key, value, description) VALUES
    ('invitation.inviter_reward', '100', '邀请者奖励积分'),
    ('invitation.invitee_reward', '50', '被邀请者奖励积分')
ON CONFLICT (key) DO NOTHING;

-- 插入示例订阅套餐
INSERT INTO subscription_plans (name, description, price, duration_days, features, is_active, is_popular, sort_order) VALUES
    ('月度 VIP', '30天 VIP 会员', 19.90, 30, '["4K 超高清", "3台设备同时播放", "无广告", "专属客服"]', TRUE, FALSE, 1),
    ('季度 VIP', '90天 VIP 会员，节省20%', 49.90, 90, '["4K 超高清", "3台设备同时播放", "无广告", "专属客服", "优先转码"]', TRUE, TRUE, 2),
    ('年度 VIP', '365天 VIP 会员，节省50%', 99.90, 365, '["4K 超高清", "5台设备同时播放", "无广告", "专属客服", "优先转码", "专属片库"]', TRUE, FALSE, 3)
ON CONFLICT DO NOTHING;

-- 插入示例充值套餐
INSERT INTO recharge_packages (name, amount, price, bonus, is_active, is_popular, sort_order) VALUES
    ('基础充值', 100, 9.90, 0, TRUE, FALSE, 1),
    ('超值充值', 500, 39.90, 50, TRUE, TRUE, 2),
    ('豪华充值', 1000, 69.90, 200, TRUE, FALSE, 3)
ON CONFLICT DO NOTHING;
