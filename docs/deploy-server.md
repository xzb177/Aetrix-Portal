# 服务端部署（统一后端 + 自建 Emby 网关）

这篇把「媒体服务本身」跑起来：统一后端进程、数据库、媒体库扫描、Emby 协议网关，以及让 Infuse / SenPlayer 等客户端连上来。

> 前置：一台能跑 Python 的 Linux 服务器（1C1G 起步，转码建议 2C4G+ 且有核显/独显）。**不需要**安装官方 Emby Server。

## 1. 环境要求

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.10+（容器镜像用 3.11-slim） | 必需 |
| ffmpeg | 任意较新版本 | **可选**。仅 HLS 转码需要；原盘直连播放不需要 |
| SQLite | 内置 | 默认数据库，开箱即用 |
| PostgreSQL | 13+ | 生产推荐，需自行安装并建库 |
| Redis | 5+ | 可选。未启用时用内存缓存，单机单进程够用 |

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg
```

## 2. 拉取代码并安装依赖

```bash
git clone https://github.com/xzb177/Aetrix-Portal.git
cd Aetrix-Portal

python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## 3. 配置 `.env`

```bash
cp env.example .env
```

`env.example` 里逐项都有注释，部署时真正需要你决定的是这几项：

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `PORT` / `HOST` | 建议 | 默认 `8000` / `0.0.0.0` |
| `SECRET_KEY` | **生产必填** | JWT 签名密钥。不设置会用临时随机密钥，**每次重启所有人登录态失效**。生成：`python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `EMBY_PUBLIC_URL` | **必填** | 对外访问地址（如 `https://media.example.com`）。账号卡与播放器一键导入都读它，填错客户端会连到错误地址 |
| `EMBY_SERVER_NAME` / `EMBY_SERVER_ID` | 建议 | 客户端里显示的服务器名与稳定 ID，迁移时保持 `EMBY_SERVER_ID` 不变 |
| `CORS_ORIGINS` | **生产必填** | 逗号分隔的具体域名。**留空等于允许所有源**，仅适合本地调试 |
| `EMBY_ALLOW_LEGACY_TOKENS` | 保持 `false` | 开启后 `Bearer <user_id>` 可冒充任意用户。仅限历史 token 过渡期临时打开 |
| `DATABASE_TYPE` / `DATABASE_URL` | 生产建议 | 默认 SQLite 单文件；切 PostgreSQL 见下 |
| `REDIS_ENABLED` / `REDIS_URL` | 可选 | 多实例或重启不丢登录风控时才需要 |
| `EMBY_TRANSCODE_DIR` | 可选 | HLS 切片临时目录，确保有足够磁盘空间 |
| `EMBY_FFMPEG_PATH` | 可选 | 默认 `ffmpeg`，装在非标准路径时改这里 |
| `TMDB_API_KEY` | 可选 | 开启中文元数据刮削（海报/简介/评分）。不填则只做 ffprobe 本地探测 |

切 PostgreSQL 时：

```env
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql://royalbot:改一个强密码@localhost:5432/royalbot
```

> 经济系统相关的支付网关、签到奖励、邀请返利等，**也可以留空**，之后在管理后台「系统设置 → 经济设置」在线配置，后台值优先于环境变量。

## 4. 启动

```bash
python serve.py            # 默认 0.0.0.0:8000
PORT=9000 python serve.py  # 换端口
```

### 用 systemd 常驻（推荐）

`/etc/systemd/system/aetrix.service`：

```ini
[Unit]
Description=Aetrix Portal (unified backend)
After=network.target

[Service]
Type=simple
User=aetrix
WorkingDirectory=/opt/Aetrix-Portal
EnvironmentFile=/opt/Aetrix-Portal/.env
ExecStart=/opt/Aetrix-Portal/.venv/bin/python serve.py
Restart=always
RestartSec=5
# 转码进程组需要能被整体回收
KillMode=control-group
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aetrix
sudo systemctl status aetrix
journalctl -u aetrix -f
```

> 只跑 `serve.py` 一个进程即可。**不要**用 `uvicorn --workers N` 起多个 worker，原因见[文档中心](./README.md#为什么是单进程)。

## 5. 验证服务端

```bash
# 健康检查
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/health/detailed

# Emby 客户端视角：协议面是否可用
curl -s http://127.0.0.1:8000/emby/system/info/public

# Prometheus 指标
curl -s http://127.0.0.1:8000/metrics | head
```

`/emby/system/info/public` 返回服务器名与版本号，说明 Emby 协议网关已就绪。

## 6. 创建媒体库并扫描

媒体库用管理 API 创建（需要 `is_staff` 管理员的 JWT）：

```bash
TOKEN=<管理员 access_token>

# 建电影库
curl -X POST http://127.0.0.1:8000/api/admin/emby/libraries \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"电影","collection_type":"movies","paths":["/data/movies"]}'

# 建剧集库
curl -X POST http://127.0.0.1:8000/api/admin/emby/libraries \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"剧集","collection_type":"tvshows","paths":["/data/tv"]}'

# 触发扫描（把 1 换成库 ID）
curl -X POST http://127.0.0.1:8000/api/admin/emby/libraries/1/scan \
  -H "Authorization: Bearer $TOKEN"
```

扫描会递归识别「电影 / 剧集 / 季 / 集」（支持 `S01E02`、`1x02`、`第N集` 等命名），用 ffprobe 提取编码、分辨率、音轨与字幕轨，并检测外挂字幕。

> 首次部署时数据库里还没有管理员。用 `POST /api/user/auth/register` 注册第一个账号，再把它提升为管理员（`is_staff`）——可参考 `scripts/reset_admin_password.py`，或直接改库里的 `web_users.is_staff`。然后再去门户/后台登录。

## 7. 让 Emby 客户端连上来

客户端里「服务器地址」填 `EMBY_PUBLIC_URL` 指向的地址（如 `https://media.example.com`，不要带 `/emby` 后缀），用户名密码用**门户账号**：

- 用户首次打开门户的账号卡时会自动生成 `emby_username`；
- 也可以让用户主动设置：`POST /api/user/emby/password`；
- 门户改密会**自动同步**为 Emby 播放密码，两边永远一致，用户不用记两套。

已在 README 列出兼容性验证过的客户端：官方 App、Infuse、Forward、Hills、SenPlayer 等。

协议面已实现的端点包括（节选）：`/Users/AuthenticateByName`、`/Users/{uid}/Items`、`/Items/{id}/PlaybackInfo`、`/Videos/{id}/stream`（Range 直连）、`/videos/{id}/master.m3u8`（HLS 转码）、字幕投递 `/Videos/{id}/{mid}/Subtitles/{i}/Stream.{fmt}`、`/Search/Hints`、`/Items/{id}/Images/{Type}/{Index}`、`/Sessions/Playing/*` 进度上报等 40+ 端点。

### 转码与直连

- 客户端支持时会走**直连流**（HTTP Range），几乎不吃 CPU；
- 不支持或带宽受限时回退 **HLS 转码**，需要 ffmpeg；ffmpeg 缺失时端点会明确返回 503 而不是 500。

## 8. 监控（可选）

后端在 `/metrics` 暴露 Prometheus 指标，`monitoring/` 下给了现成的采集与告警配置：

```bash
prometheus --config.file=monitoring/prometheus.yml
alertmanager --config.file=monitoring/alertmanager.yml
```

> `/metrics` 没有内置鉴权。生产环境请在 Nginx 层限制来源（只放行监控机），不要裸暴露到公网。

## 下一步

- 把门户网站和管理后台发布出去 → [门户与管理后台部署](./deploy-web.md)
- 上线前过一遍检查清单 → [运维 · 备份 · 排错](./operations.md)
