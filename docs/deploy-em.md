# EM · Emby Manager —— 面板部署

**EM 负责所有「卖会员」相关的事**：用户注册 / 登录 / 套餐订阅 / 续费 / 充值 / 邀请返利 / 卡码核销 / 签到 / 工单 / 公告 / 设备与登录风控 / 管理后台。它是整套系统的**唯一事实来源**——用户、媒体库、策略、开关都由 EM 写入共享数据库，EA（Emby API 网关）只是把这些"推下来"的结果对客户端兑现。

EM 部署到**你自己的域名**（面板域名），客户端不要连这个域名。

> 第一次部署？建议顺序：先按本篇把 EM 跑起来并建好媒体库，再按 [EA 部署](./deploy-ea.md) 把客户端接上。

## 1. 部署形态：先决定单进程还是分离

| 形态 | 进程 | 适用 |
| --- | --- | --- |
| **分离部署（推荐生产）** | EM（`serve.py`）+ EA（`serve_emby.py`） | 面板与协议面分开、各自独立域名/端口、可分别重启与扩容，客户端直连 EA |
| 单进程（兼容旧部署） | 只跑 EM（`serve.py`） | 单机小站，EM 自己一并提供 `/emby/*` 协议面 |

EM 是否内置 Emby 协议面由 `ENABLE_EMBY_GATEWAY` 控制（**默认 `true`**，即保持原有行为）：

```env
ENABLE_EMBY_GATEWAY=true    # 单进程模式：EM 自己提供 /emby/*
ENABLE_EMBY_GATEWAY=false   # 分离模式：协议面交给 EA，EM 只跑面板
```

置为 `false` 后，若有客户端误连 EM，EM 会返回明确的 404 指引（告诉它该去哪个 EA 地址），而不是把页面 HTML 当成响应发出去。

## 2. 环境要求

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.10+（容器镜像为 3.11-slim） | 必需 |
| Node.js | 20.19+ 或 22.12+ | 仅构建前端时需要（见 `user_frontend/package.json` 的 `engines`） |
| SQLite | 内置 | 默认数据库 |
| PostgreSQL | 13+ | 生产推荐 |
| Redis | 5+ | 可选：多实例、或希望重启不丢风控状态时启用 |
| ffmpeg | 可选 | **分离部署下转码在 EA 那台机器上，EM 不需要** |

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y python3 python3-venv python3-pip
```

## 3. 拉取代码并安装依赖

```bash
git clone https://github.com/xzb177/Aetrix-Portal.git
cd Aetrix-Portal

python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## 4. 构建两个前端

EM 负责托管门户与管理后台的静态产物。产物路径是**固定约定**：

| 前端 | 构建命令 | 输出 | Vite `base` | EM 挂载到 |
| --- | --- | --- | --- | --- |
| 用户门户 | `npm run build-only` | `user_frontend/dist` | `/` | `/` |
| 管理后台 | `npm run build` | `admin_frontend/dist` | `/admin/` | `/admin` |

```bash
cd user_frontend  && npm ci && npm run build-only && cd ..
cd admin_frontend && npm ci && npm run build      && cd ..
```

想要构建时同时过类型检查，用户端可用 `npm run build:strict`。

> 管理后台的 `base` 必须是 `/admin/`；改错会导致后台白屏（页面里的资源全 404）。EM 启动时若发现 `admin_frontend/dist` 不存在，会在日志里提示「管理后台构建产物不存在，/admin 不可用」。

门户与管理后台的 API 请求都走**相对路径**（`/api/user/*`、`/api/admin`），因此**必须与 EM 同源**：一个域名，Nginx 分流。不要把面板放 A 域、API 放 B 域。

## 5. 配置 `.env`

```bash
cp env.example .env
```

`env.example` 里逐项都有注释。真正需要你决定的是这些：

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | **生产必填** | JWT 签名密钥。不设置会用临时随机密钥，**每次重启所有人登录态失效**；分离部署时 EA 必须用**同一个值**。生成：`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
| `PORT` / `HOST` | 建议 | 面板端口，默认 `8000` / `0.0.0.0` |
| `EMBY_PUBLIC_URL` | **必填** | 用户账号卡与「一键导入」展示的地址。分离部署时填 **EA 的地址** |
| `EMBY_API_PUBLIC_URL` | 分离模式建议 | 与 `EMBY_PUBLIC_URL` 同为客户端地址，用于 EM 的"请去连 EA"指引 |
| `EM_PANEL_URL` | 可选 | EM 自己的面板地址；EA 启动时探测它是否可达 |
| `CORS_ORIGINS` | **生产必填** | 逗号分隔的具体域名。留空等于允许所有源 |
| `EMBY_ALLOW_LEGACY_TOKENS` | 保持 `false` | 开启后 `Bearer <user_id>` 可冒充任意用户，仅过渡期使用 |
| `CORS_ORIGINS` / `DATABASE_URL` | 生产建议 | 默认 SQLite 单文件；切 PG：`DATABASE_TYPE=postgresql` + `DATABASE_URL=postgresql://…` |
| `REDIS_ENABLED` / `REDIS_URL` | 可选 | 未启用时用内存缓存 |
| `TMDB_API_KEY` | 可选 | 中文元数据刮削（海报/简介/评分）；不填只做本地 ffprobe 探测 |
| `ENABLE_EMBY_GATEWAY` | 分离模式必填 | 详见第 1 节 |

> 支付网关、签到奖励、邀请返利等经济项**可以留空**，之后在管理后台「系统设置 → 经济设置」在线配置，后台值优先。

## 6. 启动 EM

```bash
python serve.py              # 默认 0.0.0.0:8000
PORT=9000 python serve.py    # 指定端口
```

### systemd 常驻

`/etc/systemd/system/aetrix-em.service`：

```ini
[Unit]
Description=Aetrix Portal EM (panel)
After=network.target

[Service]
Type=simple
User=aetrix
WorkingDirectory=/opt/Aetrix-Portal
EnvironmentFile=/opt/Aetrix-Portal/.env
ExecStart=/opt/Aetrix-Portal/.venv/bin/python serve.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now aetrix-em
journalctl -u aetrix-em -f
```

> 单进程模式（EM 自带协议面）下**不要**用 `uvicorn --workers N`：HLS 转码子进程与会话管理在同一进程内闭环，多 worker 会重复 fork 并泄漏进程。分离部署时 EM 不参与转码，但仍建议保持单进程以免风控计数分散。

## 7. Nginx + HTTPS（按域名授权）

EM 建议放在**面板域名**上，例如 `panel.example.com`。仓库给了完整示例 `nginx/nginx.conf`（Cloudflare 真实 IP、gzip、TLS、安全头），下面是站点级最小配置：

```nginx
server {
    listen 80;
    server_name panel.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name panel.example.com;

    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    client_max_body_size 20m;

    # 分离部署：网页播放器走同源 /emby/*，反代给 EA，避免跨域
    location /emby/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_buffering off;          # 边转码边播放
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";   # WebSocket 通知（站内消息/工单推送）
    }
}
```

单进程模式（`ENABLE_EMBY_GATEWAY=true`）不需要 `/emby/` 那段，全部转给 `127.0.0.1:8000` 即可。

> ⚠️ 仓库里提交了 `nginx/ssl/fullchain.pem` 与 `nginx/ssl/privkey.pem`。**不要直接用于生产**，请换成你自己的证书；若那两个文件里其实是可用的真实私钥，请立即吊销重签。

## 8. 首次登录与管理

1. **先造管理员**：新库里没有任何账号。注册第一个用户（门户注册页，或 `POST /api/user/auth/register`），然后把它设为管理员——直接改库 `web_users.is_staff = True`，或用 `scripts/reset_admin_password.py` 辅助。
2. 门户：`https://panel.example.com/`
3. 管理后台：`https://panel.example.com/admin/`（同一套账号，非 `is_staff` 会被拒）

> 后台**不会**把第一个注册用户自动变成管理员，这是有意的安全设计。

## 9. 媒体库创建与扫描

媒体库属于 EM 的管理面（写入的就是 EA 要服务的那些数据）：

```bash
TOKEN=<管理员 access_token>

curl -X POST https://panel.example.com/api/admin/emby/libraries \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"电影","collection_type":"movies","paths":["/data/movies"]}'

curl -X POST https://panel.example.com/api/admin/emby/libraries/1/scan \
  -H "Authorization: Bearer $TOKEN"
```

扫描会递归识别「电影 / 剧集 / 季 / 集」（支持 `S01E02`、`1x02`、`第N集`、`EP05`，以及只有季号的 `S09` / `Season 9` / `第九季`），ffprobe 提取编码、分辨率、音轨与字幕轨，并检测外挂字幕。

> 分离部署时注意：媒体文件的路径必须是 **EA 那台机器/容器能看到**的路径（EA 才负责读文件与转码）。

### 刮削策略

每个媒体库可单独选择刮削策略（后台媒体库卡片直接选，或 `PUT /api/admin/emby/libraries/{id}` 传 `scrape_policy`）：

| 值 | 含义 |
| --- | --- |
| `missing_only` | 仅缺失时刮削（**默认**）：已有 TMDB 命中就不再发请求，省配额 |
| `3m` / `6m` / `1y` | 到期重刮；缺元数据的条目不受窗口限制，总会补 |
| `all` | 每次扫描全量重刮（仅在通网、配额充足时用） |

多密钥轮询：`TMDB_API_KEYS=key1,key2,key3` 逗号分隔，某个密钥叫到配额上限时自动轮到下一个。

扫描任务使用**固定配置快照**：运行中修改路径/策略不会把本次任务改成「一半旧一半新」；保存后重新触发即用新路径（旧路径不会被继续扫描）。同一媒体库同时只允许一个扫描任务，重复触发返回 `409`。

### 按发行平台生成虚拟媒体库

识别片名/目录里的发行组标签（`NF` / `DSNP` / `ATVP` / `AMZN` / `HMAX` / `HULU` / `PMTP` / `PCOK` / `CR` …）后，可为 Netflix / Disney+ / Apple TV+ / Prime Video / Max / Hulu / Paramount+ / Peacock / Crunchyroll 生成虚拟媒体库：

```bash
curl -X POST https://panel.example.com/api/admin/emby/libraries/virtual \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"enabled": true}'            # 不传 platforms = 按库里实际出现过的标签生成
```

虚拟库没有自己的目录，是**跨库的平台视图**（条目仍归属原媒体库）；只在总开关与单个库都开启时才出现在客户端。关闭方式：

- 整个实例关闭：`ENABLE_VIRTUAL_LIBRARIES=false`（每台 EA 可独立配置）
- 单个库关闭：后台停用该库（或 `PUT /libraries/{id}` 传 `is_enabled: false`）

两种情况下客户端媒体库列表不会出现它，用 guid 直达也返回 `404`。

### 图片修复队列

数据库里有图片记录但取不到图（换盘 / 迁移 / 挂载掉线 / 远程图失效）时，图片接口会返回干净的 `404`（而不是 5xx——客户端会把 5xx 当成鉴权或服务器故障反复重试），并把条目排进修复队列；下一轮扫描会换成 TMDB 远程图。

```bash
curl https://panel.example.com/api/admin/emby/libraries/repair/queue -H "Authorization: Bearer $TOKEN"
curl -X POST https://panel.example.com/api/admin/emby/libraries/repair/run -H "Authorization: Bearer $TOKEN"
```

## 10. 运营配置

进后台「系统设置」按需配置（这些都直接决定 EA 对客户端的态度）：

| 配置 | 作用 |
| --- | --- |
| 付费墙（`subscription_required` + 拦截文案） | 非会员的播放、直连流、HLS、下载一律被拦；管理员始终放行 |
| 下载开关（`allow_download`） | 关闭后客户端下载与 `/Items/{id}/File` 等价路径一并被拦 |
| 设备风控（`device_limit_per_user` / `device_limit_auto_evict`） | 每用户设备上限，超限自动踢最久未使用设备 |
| 登录与安全日志（`login_log_retention_days`） | 登录成功/失败、设备超限、诱饵码触发等事件保留天数 |
| 卡码体系 | 注册码 / 续期码 / 白名单码 / 诱饵码 / 指名码的生成、筛选、停用与回收 |
| 经济设置 | 支付网关（易支付兼容）、签到奖励、邀请返利比例 |

**可选组件**：`telegram_login_bot/` 是一个独立的轻量 Telegram 登录 Bot，需要 `TELEGRAM_LOGIN_BOT_TOKEN`（以及 `WEB_URL` 指向面板地址），单独一个进程运行，不影响 EM 主服务。

## 11. 验证清单

```bash
BASE=https://panel.example.com

curl -s -o /dev/null -w '%{http_code}\n' $BASE/            # 200 门户页面
curl -s -o /dev/null -w '%{http_code}\n' $BASE/admin/      # 200 后台页面
curl -s $BASE/api/health                                    # 面板健康检查
curl -s $BASE/api/health/detailed                           # 数据库 / Redis / WebSocket
```

浏览器再确认：首页有样式、刷新 `/wallet` 等子路由不 404、`/admin/` 能登录进「数据概览」。

## 12. 备份

数据库与 `SECRET_KEY` 一起备（丢了密钥等于所有人重新登录，且 EA 会因配对校验拒绝启动）。SQLite / PostgreSQL 的具体命令、定时任务与恢复步骤见 [运维 · 备份 · 排错](./operations.md)。

## 下一步

- 把客户端接上：部署 [EA · Emby API](./deploy-ea.md)
- 上线检查与排错：[运维 · 备份 · 排错](./operations.md)
