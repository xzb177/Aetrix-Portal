# RoyalBot Portal

独立的 RoyalBot Web 门户项目，包含用户端和管理后台。

## 项目结构

```
/root/RoyalBot-Portal/
├── user_frontend/      # 用户端前端 (Vue 3 + Tailwind CSS)
│   └── dist/           # 构建输出
├── user_backend/       # 用户端后端 (FastAPI + Python)
│   ├── api/            # API 路由
│   ├── database/       # 数据库模型
│   ├── schemas/        # Pydantic 模型
│   ├── utils/          # 工具函数
│   ├── venv/           # Python 虚拟环境
│   ├── run.py          # 启动脚本
│   └── main.py         # FastAPI 应用
├── admin_frontend/     # 管理后台前端
│   └── dist/           # 构建输出
└── admin_backend/      # 管理后台后端
```

## 访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| 用户端 | http://154.40.33.2/ | 订阅、求片、充值 |
| 管理后台 | http://154.40.33.2/admin | 用户管理、数据统计 |
| 用户端 API | http://154.40.33.2:8001/ | FastAPI + Swagger UI |
| 管理后台 API | http://154.40.33.2:8000/ | FastAPI + Swagger UI |

## 服务管理

```bash
# 用户端后端
systemctl start|stop|restart|status royalbot-portal.service

# 管理后台后端
systemctl start|stop|restart|status royalbot-admin.service

# 查看日志
journalctl -u royalbot-portal.service -f
journalctl -u royalbot-admin.service -f

# 重载 Nginx
systemctl reload nginx
```

## 前端构建

```bash
# 用户端
cd /root/RoyalBot-Portal/user_frontend
npm run build-only

# 管理后台
cd /root/RoyalBot-Portal/admin_frontend
npm run build
```

## 依赖关系

- **机器人项目**: `/root/royalbot/` (主项目，包含数据库)
- **Portal 项目**: `/root/RoyalBot-Portal/` (本项，独立 Web 服务)

Portal 项目通过读取 `/root/royalbot/royalbot.db` 数据库与机器人项目关联。
