# RoyalBot Portal

> **Emby 影视账号订阅服务系统** - 用户端 + 管理后台一体化解决方案

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-latest-blue.svg)]()

## ✨ 功能特性

### 用户端
- 🎬 **订阅套餐** - 灵活的订阅套餐管理
- 📺 **媒体求片** - 用户求片 + 投票系统
- 💰 **充值兑换** - 支持充值和兑换码
- 🎫 **工单系统** - 用户客服工单
- 📢 **站内消息** - 系统公告和通知
- 👥 **邀请系统** - 邀请码奖励机制
- 🤖 **Telegram 登录** - 一键快速登录
- 📱 **一键导入** - Forward/Hills/SenPlayer 播放器
- 🏆 **徽章系统** - 用户成就展示

### 管理后台
- 👤 **用户管理** - 用户信息、VIP 管理
- 📊 **数据统计** - 用户、订单、收入统计
- ⚙️ **系统配置** - 支付配置、公告管理
- 🎥 **Emby 管理** - 服务器和账号管理
- 🎫 **工单处理** - 工单回复和管理
- 🔧 **路由管理** - 线路配置和监控
- 📝 **日志审计** - 系统操作日志

## 🚀 快速开始

### 环境要求

- Docker & Docker Compose
- 域名 + SSL 证书（推荐）

### 一键部署

```bash
# 克隆仓库
git clone https://github.com/xzb177/Aetrix-Portal.git
cd Aetrix-Portal

# 启动服务
docker compose up -d
```

## 📦 目录结构

```
RoyalBot-Portal/
├── user_frontend/       # 用户前端 (Vue 3)
├── user_backend/        # 用户后端 (FastAPI)
├── admin_frontend/      # 管理前端 (Vue 3)
├── admin_backend/       # 管理后端 (FastAPI)
├── nginx/               # Nginx 配置
└── docker-compose.yml   # 容器编排
```

## 🔧 配置说明

首次运行前请配置 `.env` 文件：

```env
# 数据库
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# JWT 密钥
SECRET_KEY=your-secret-key

# 支付配置
YIPAY_GATEWAY_URL=https://pay.example.com
YIPAY_PARTNER_ID=your_partner_id
YIPAY_KEY=your_key

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_BOT_USERNAME=your_bot_username
```

## 📱 一键导入客户端

支持通过 URL Scheme 一键导入 Emby 配置：

| 播放器 | 支持状态 |
|--------|---------|
| Forward | ✅ |
| Hills | ✅ |
| SenPlayer | ✅ |

## 🛠️ 开发

### 前端开发

```bash
cd user_frontend  # 或 admin_frontend
npm install
npm run dev
```

### 后端开发

```bash
cd user_backend  # 或 admin_backend
pip install -r requirements.txt
python main.py
```

## 📝 更新日志

### v1.5.0 (2026-01-24)
- ✅ 修复用户登录数据库字段缺失问题
- ✅ 优化前端错误提示，用户友好化
- ✅ 新增数据库自动迁移机制
- ✅ 添加徽章系统
- ✅ 完善路由管理功能

### v1.4.0
- 添加媒体求片功能
- 添加工单系统
- 添加邀请码系统

### v1.0.0
- 初始版本发布

## 📄 许可证

Copyright (c) 2024-2025 RoyalBot. All rights reserved.
