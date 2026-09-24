# Aetrix Docker 部署

## 单机 EM 部署

当前 Compose 默认是单机模式：Aetrix EM 同时提供门户、后台 API 与 Emby 协议面，Redis 作为内部缓存/限流服务。

```bash
cp env.example .env
# 至少填写固定随机 SECRET_KEY；生产不要使用临时密钥
# 可按需修改 AETRIX_PORT、MEDIA_ROOT

bash scripts/deploy.sh
```

`scripts/deploy.sh` 会校验 Compose 配置、构建镜像、启动服务，并等待 `aetrix` 容器的健康检查通过；
它不会拉取远端代码。首次部署前只执行一次上面的 `cp` 并填写 `.env`，之后重复部署直接运行脚本即可。
想先看将要执行的命令，可以使用：

```bash
bash scripts/deploy.sh --dry-run
```

手动等价流程：

```bash
docker compose build --pull
docker compose up -d --remove-orphans
docker compose ps
curl http://127.0.0.1:8000/api/health
```

容器结构：

- `aetrix`：Python 3.12 + 前端多阶段构建 + ffmpeg，默认端口 `8000`；
- `aetrix-redis`：Redis 7，数据通过 Docker volume 持久化；
- `aetrix_data`：SQLite、转码临时目录、图片缓存；
- `redis_data`：Redis AOF 数据。

媒体目录由 `MEDIA_ROOT` 映射到容器 `/media`，默认只读。媒体挂载配置若使用主机路径，必须改成容器内可见的路径。

## 一键更新

项目根目录提供了一键更新脚本，默认会检查依赖与 Git 工作区、尝试备份容器内 SQLite，然后拉取代码、
重新构建镜像并更新 Compose 服务：

```bash
bash scripts/update.sh
```

脚本会在工作区有未提交改动时停止，不会用远端代码覆盖本地现场；容器正在运行且 `/data` 下有 SQLite
数据库时，会使用容器内置的 Python `sqlite3` 模块把备份写到 `/data/aetrix-update-时间.db`。备份失败会
停止更新；找不到数据库时会明确告警并继续代码更新。

常用选项：

```bash
bash scripts/update.sh --dry-run       # 只打印流程，不实际拉取、备份、构建或重启
bash scripts/update.sh --skip-backup   # 明确跳过数据库备份
```

手动等价流程：

```bash
git pull --ff-only
docker compose build --pull
docker compose up -d --remove-orphans
docker compose ps
```

升级前备份：

```bash
docker compose exec aetrix sh -c 'sqlite3 /data/aetrix_unified.db ".backup /data/aetrix-backup.db"'
```

生产环境不要把 `.env`、数据库、媒体文件写入镜像；`.dockerignore` 已排除这些内容。

## 分离 EM / EA

分离部署时建议拆成两套 Compose 项目：

- EM：`ENABLE_EMBY_GATEWAY=false`，只提供面板；
- EA：使用同一个代码镜像，启动命令改为 `python serve_emby.py`，使用共享 PostgreSQL 与完全相同的 `SECRET_KEY`；
- EA 所在机器必须挂载实际媒体目录，并设置 `NODE_KEY` / `REALM`。

跨机器生产部署不要使用 SQLite；改用 PostgreSQL，并让 EM 与 EA 连接同一个数据库。

## 反向代理

当前 Compose 直接暴露 `AETRIX_PORT`。接入 Nginx/Caddy 时只反代到 `127.0.0.1:8000`，外部 HTTPS 终止在反代层；不要把 Redis 端口暴露公网。

## 安全要求

- `SECRET_KEY` 至少 32 字符，EM/EA 必须一致；
- `.env` 权限设为 `600`；
- Docker 容器不要使用 `--privileged`；
- 转码目录与数据库使用持久卷；
- 部署后验证 `/api/health`、`/admin/`、`/emby/System/Info/Public`；
- root 密码部署完成后应立即轮换，改用 SSH key 并关闭密码登录。

> 更新脚本不会修改宿主机配置、数据库卷或媒体目录。
