# RoyalBot Portal 部署脚本

Emby 影视账号订阅服务系统的一键部署脚本。

## 功能特性

- 用户端：订阅套餐、媒体求片、充值兑换、工单系统
- 管理后台：用户管理、数据统计、系统配置
- 支持多种支付方式
- 邀请码和兑换码系统
- Telegram 一键登录

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

### deploy.sh

```
--full         完整部署（前后端 + Docker）
--fe-only      仅构建前端
--backend      仅启动后端
--backup       备份数据库
--restore      恢复数据库
--update       更新并重启服务
--logs         查看日志
--menu         交互式菜单
```

### dev.sh

开发环境快速启动，包含热重载功能。

## 目录结构

```
RoyalBot-Portal/
├── deploy.sh           # 一键部署脚本
├── dev.sh              # 开发环境脚本
└── scripts/            # 辅助脚本
    ├── backup_db.sh
    ├── restore_db.sh
    ├── docker-deploy.sh
    └── ...
```

## 环境要求

- Docker & Docker Compose
- Python 3.10+
- Node.js 18+
- PostgreSQL / SQLite

## 配置说明

首次运行前请配置 `.env` 文件中的必要参数：

- 数据库连接信息
- JWT 密钥
- 支付配置
- Telegram Bot 配置

## 许可证

Copyright (c) 2024 RoyalBot. All rights reserved.
