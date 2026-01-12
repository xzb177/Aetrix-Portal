# RoyalBot Portal 部署脚本

Emby 影视账号订阅服务系统的一键部署脚本。

## 功能特性

- 用户端：订阅套餐、媒体求片、充值兑换、工单系统
- 管理后台：用户管理、数据统计、系统配置
- 支持多种支付方式
- 邀请码和兑换码系统
- Telegram 一键登录
- 一键导入客户端 (Forward/SenPlayer/EplayerX/Emby)

## 快速开始

### 下载部署脚本

```bash
wget https://github.com/xxx/RoyalBot-Portal/raw/main/deploy.sh
chmod +x deploy.sh
```

### 一键部署

```bash
./deploy.sh --full
```

### 开发环境

```bash
./dev.sh
```

## 脚本选项

### deploy.sh (部署脚本)

```bash
./deploy.sh --full         # 完整部署
./deploy.sh --fe-only      # 仅构建前端
./deploy.sh --backend      # 仅启动后端
./deploy.sh --backup       # 备份数据库
./deploy.sh --restore      # 恢复数据库
./deploy.sh --update       # 更新并重启服务
./deploy.sh --logs         # 查看日志
./deploy.sh --menu         # 交互式菜单
```

### update.sh (一键更新脚本)

快速更新前端代码和服务：

```bash
./update.sh              # 标准更新（构建+重启）
./update.sh --clean      # 更新并清理旧镜像
./update.sh --no-cache   # 不使用缓存构建
```

**更新内容：**
1. 自动备份当前版本到 `backups/` 目录
2. 重新构建前端 Docker 镜像
3. 重启 user_frontend 服务
4. 清理未使用的旧镜像（--clean 选项）

### dev.sh (开发环境)

开发环境快速启动，包含热重载功能。

## 目录结构

```
RoyalBot-Portal/
├── deploy.sh           # 一键部署脚本
├── update.sh           # 一键更新脚本
├── dev.sh              # 开发环境脚本
├── docker-compose.yml  # Docker Compose 配置
└── scripts/            # 辅助脚本
    ├── backup_db.sh
    ├── restore_db.sh
    ├── docker-deploy.sh
    └── ...
```

## 环境要求

- Docker & Docker Compose
- Python 3.10+
- Node.js 22+
- PostgreSQL / SQLite

## 配置说明

首次运行前请配置 `.env` 文件中的必要参数：

- 数据库连接信息
- JWT 密钥
- 支付配置
- Telegram Bot 配置

## 一键导入客户端

支持通过 URL Scheme 一键导入 Emby 配置到以下播放器：

| 播放器 | URL Scheme |
|--------|-------------|
| Forward | `forward://emby/add?url=...` |
| EplayerX | `eplayerx://emby/add?url=...` |
| SenPlayer | `senplayer://add?host=...` |
| Emby 官方 | `emby://host#username@password` |

## 许可证

Copyright (c) 2024 RoyalBot. All rights reserved.
