# RoyalBot Portal

> **完全自建 Emby 影视服务系统** - 内置自研 Emby 兼容媒体服务器 + 用户端 + 管理后台

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-latest-blue.svg)]()

## 🎯 完全自建架构（v2.0）

本项目后端**内置完整的 Emby 协议兼容媒体服务器**，无需安装官方 Emby/EmbyServer，Emby 客户端（Infuse、Forward、Hills、SenPlayer、官方 App）可直接连接本后端：

```
Emby 客户端 ──HTTP──▶ backend/main.py（单进程单端口）
                        ├── /emby/*                 Emby 协议兼容 API
                        │   ├── /Users/AuthenticateByName   用户名密码认证
                        │   ├── /Users/{uid}/Items          媒体库浏览/搜索/筛选
                        │   ├── /Items/{id}/PlaybackInfo    播放信息
                        │   ├── /Videos/{id}/stream         直连流（Range 分段）
                        │   ├── /videos/{id}/master.m3u8    HLS 转码（ffmpeg）
                        │   ├── /Items/{id}/Images/*        海报/背景图
                        │   └── /Sessions/Playing/*         播放进度上报
                        ├── /api/user/*             用户门户 API
                        └── /api/admin/*            管理后台 API
```

### 核心能力
- **媒体库扫描**：递归扫描视频目录，电影/剧集/季/集自动识别（S01E02 / 1x02 / 第N集），外挂字幕检测
- **元数据刮削**：ffprobe 提取轨道信息（编码/分辨率/音轨/字幕），可选 TMDB 中文刮削（海报/简介/评分/类型）
- **流媒体服务**：HTTP Range 直连流 + ffmpeg HLS 实时转码（可选码率/分辨率）
- **用户体系**：门户账号即 Emby 账号，收藏/已看/续看跨设备同步，播放进度自动记录
- **管理后台**：媒体库 CRUD/扫描、条目管理、在线会话监控/强制下线、转码管理

## ✨ 功能特性

### 自建 Emby 服务器
- 🎬 **Emby 协议兼容** - Infuse/Forward/Hills/SenPlayer/官方客户端直接连接
- 📚 **多媒体库** - 电影库/剧集库，多目录扫描
- 🎞️ **直连 + 转码** - 原盘直连流，浏览器/受限设备自动 HLS 转码
- 🖼️ **图片服务** - 本地海报/TMDB 远程图统一代理
- 📊 **会话监控** - 在线设备/播放进度/观看统计

### 用户端
- 📺 **媒体求片** - 用户求片 + 投票系统
- 💰 **充值兑换** - 支持充值和兑换码
- 🎫 **工单系统** - 用户客服工单
- 📢 **站内消息** - 系统公告和通知
- 👥 **邀请系统** - 邀请码奖励机制
- 📱 **一键导入** - 账号卡 + 播放器 URL Scheme 导入

### 管理后台
- 👤 **用户管理** - 用户信息、Emby 凭据管理
- 📚 **媒体库管理** - 库/路径/扫描/条目管理
- 📊 **会话监控** - 在线用户、强制下线
- 🎫 **工单处理** - 工单回复和管理
- 📝 **日志审计** - 系统操作日志

## 🚀 快速开始

### 环境要求

- Python 3.10+
- ffmpeg（可选，转码需要；直连播放不需要）

### 启动统一后端（含自建 Emby 服务器）

```bash
pip install -r backend/requirements.txt
cp env.example .env   # 按需修改 EMBY_PUBLIC_URL 等
python serve.py       # 默认 0.0.0.0:8000
```

### 验证

```bash
# Emby 客户端视角：系统信息
curl http://localhost:8000/emby/system/info/public

# 管理后台：创建媒体库并扫描
curl -X POST http://localhost:8000/api/admin/emby/libraries \
  -H 'Content-Type: application/json' \
  -d '{"name":"电影","collection_type":"movies","paths":["/data/movies"]}'
curl -X POST http://localhost:8000/api/admin/emby/libraries/1/scan
```

### Emby 客户端连接

服务器地址填本后端地址（如 `http://your-host:8000`），用户名密码使用门户账号（用户首次访问账号卡时自动生成 `emby_username`，或通过 `POST /api/user/emby/password` 设置）。

### 用户门户认证（JWT）

```bash
# 注册（返回 access_token + refresh_token + user）
curl -X POST http://localhost:8000/api/user/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"secret123","email":"demo@example.com"}'

# 登录
curl -X POST http://localhost:8000/api/user/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"demo","password":"secret123"}'

# 当前用户（Authorization: Bearer <access_token>）
curl http://localhost:8000/api/user/auth/me -H 'Authorization: Bearer <token>'

# 刷新 token
curl -X POST http://localhost:8000/api/user/auth/refresh \
  -H 'Content-Type: application/json' -d '{"refresh_token":"<refresh_token>"}'
```

- JWT：HS256，`SECRET_KEY` 签名，access 2 小时 / refresh 30 天，类型隔离（refresh 不能访问业务端点）
- 密码 bcrypt 存储；注册自动生成自建 Emby 凭据，改密自动同步 Emby 播放密码
- 兼容：`/api/user/emby/*` 等门户端点同时接受 JWT、旧数字 token 和 Emby 客户端 token

## 📦 目录结构

```
RoyalBot-Portal/
├── serve.py                    # 统一后端启动器（单进程单端口）
├── backend/
│   ├── main.py                 # FastAPI 主入口
│   ├── security.py             # ★ JWT 签发/校验 + bcrypt 密码哈希
│   ├── database.py             # 数据库配置（SQLite/PG/MySQL）
│   ├── models.py               # 统一数据模型
│   ├── api/
│   │   ├── user.py             # 用户门户业务 API
│   │   ├── admin.py            # 管理后台 API
│   │   └── emby_portal.py      # ★ 注册/登录/JWT 刷新/改密
│   └── emby_server/            # ★ 自建 Emby 服务器
│       ├── models.py           #   媒体库/条目/轨道/会话/Token 模型
│       ├── auth.py             #   Emby 协议认证 + Token 管理
│       ├── scanner.py          #   媒体库扫描 + ffprobe/TMDB 刮削
│       ├── streaming.py        #   直连流/Range/HLS 转码
│       ├── api.py              #   Emby 协议兼容 API（/emby/*）
│       └── portal.py           #   门户集成 API（账号卡/收藏/统计/管理）
├── user_frontend/              # 用户前端 (Vue 3)
├── admin_frontend/             # 管理前端 (Vue 3)
└── scripts/
    ├── smoke_test_emby.py      # 自建 Emby 端到端冒烟测试
    └── smoke_test_auth.py      # 门户认证（JWT）端到端测试
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
