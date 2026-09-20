# Aetrix Portal 文档中心

本项目的部署形态是「**一个 Python 进程 + 两个前端构建产物**」：统一后端同时提供门户 API、自建 Emby 协议网关，以及用户端与管理后台的静态页面。没有独立的数据库容器、没有必须安装的官方 Emby。

## 我该看哪一篇？

| 你的情况 | 看这篇 |
| --- | --- |
| 要把媒体服务跑起来：后端、Emby 网关、媒体库、播放器接入 | [服务端部署](./deploy-server.md) |
| 要把门户网站和管理后台发布出去：前端构建、域名、HTTPS、反向代理 | [门户与管理后台部署](./deploy-web.md) |
| 上线前检查、备份与恢复、出问题了怎么查 | [运维 · 备份 · 排错](./operations.md) |
| 想用 Freebuff Hosting 部署 | 做不到，原因见 [运维 · 排错](./operations.md#freebuff-hosting-报找不到受支持的框架) |

## 架构一图

```
   Emby / Infuse /        ┌────────────────────────────────┐
   Forward / Hills /      │        Nginx (443, HTTPS)      │
   SenPlayer 等客户端 ───► │  /        → 门户 SPA（静态）    │
                          │  /admin   → 管理后台（静态）    │
                          │  /api/*   → 门户 / 管理 API     │
                          │  /emby/*  → Emby 协议网关       │
                          └───────────────┬────────────────┘
                                          │ 反向代理
                                          ▼
                          ┌────────────────────────────────┐
                          │  backend（统一后端，默认 :8000） │
                          │  FastAPI 单进程                 │
                          │  ├─ /api/user/*    用户门户 API │
                          │  ├─ /api/admin/*   管理后台 API │
                          │  ├─ /emby/*        Emby 协议面  │
                          │  ├─ /              门户静态托管  │
                          │  ├─ /admin         后台静态托管  │
                          │  ├─ /api/health    健康检查     │
                          │  └─ /metrics       Prometheus   │
                          └───────────────┬────────────────┘
                                          ▼
             SQLite（默认）/ PostgreSQL · Redis（可选）· ffmpeg（转码，可选）
```

## 为什么是单进程

`serve.py` 固定 `workers=1`。HLS 转码的 ffmpeg 子进程管理与内存态会话都在进程内闭环，多 worker 会让「谁在转码、谁的会话还有效」分散到不同进程，出现重复 fork 与进程泄漏。**不要给统一后端开多 worker**，横向扩展请靠给不同用户分站点。

## 与旧版拆分架构的关系

仓库里同时留着 v2.0 之前的**拆分式**部署配置：`docker-compose.yml`（`admin_frontend` / `admin_backend` / `user_frontend` 三个容器）、`deploy.sh`、`update.sh`、`user_backend/`、`admin_backend/`。当前主线是**统一后端**（`backend/` + `serve.py`），部署请以本目录文档为准；旧栈仅在你需要接管一套历史部署时才用，且它与统一后端**不共享数据库结构**，不要混用（详见 [运维 · 排错](./operations.md#旧版-compose-栈能直接用吗)）。

## 文档清单

| 文档 | 内容 |
| --- | --- |
| [deploy-server.md](./deploy-server.md) | 环境要求、依赖安装、`.env` 配置、启动与 systemd 常驻、媒体库创建与扫描、播放器接入、监控 |
| [deploy-web.md](./deploy-web.md) | 两个前端的构建、静态托管路径、Nginx + HTTPS 反代、首登初始化、验证 |
| [operations.md](./operations.md) | 上线检查清单、安全基线、备份与恢复、常见问题与排错 |
