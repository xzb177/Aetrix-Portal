# 门户与管理后台部署

这篇把「网站」发布出去：用户门户 + 管理后台两个 Vue 前端的构建、静态托管、域名与 HTTPS。

> 前置：服务端已按 [服务端部署](./deploy-server.md) 跑起来（`http://127.0.0.1:8000` 能响应 `/api/health`）。

## 1. 关键前提：必须同源部署

两个前端的 API 请求都是**相对路径**，依赖与后端同源：

| 前端 | API 基址 | 说明 |
| --- | --- | --- |
| `user_frontend`（门户） | `''`（空 baseURL） | 请求 `/api/user/*`、`/emby/*`，自动跟随当前域名 |
| `admin_frontend`（后台） | `/api/admin` | 请求 `/api/admin/*`，写死在 `src/utils/request.ts` |

所以**不要**把 SPA 放到 `panel.example.com`、把 API 放到 `api.example.com`——那会直接跨域失败。正确做法是同一个域名下由 Nginx 分流（`/` 和 `/admin` 是页面，`/api` 和 `/emby` 是后端）。

## 2. 构建两个前端

需要 Node **20.19+ 或 22.12+**（见 `user_frontend/package.json` 的 `engines`）。

```bash
# 用户门户
cd user_frontend
npm ci
npm run build-only          # 只构建，输出 dist/
# 想同时过类型检查：npm run build:strict

# 管理后台
cd ../admin_frontend
npm ci
npm run build               # 输出 dist/
```

构建产物路径是**固定约定**，不要改：

| 前端 | 输出目录 | Vite `base` | 由谁托管 |
| --- | --- | --- | --- |
| 用户门户 | `user_frontend/dist` | `/` | 后端挂载到 `/` |
| 管理后台 | `admin_frontend/dist` | `/admin/` | 后端挂载到 `/admin` |

`admin_frontend` 的 `base` 必须是 `/admin/`；改错会导致后台白屏（页面里的 `/assets/*` 全 404）。

## 3. 静态托管：交给后端（推荐）

统一后端启动时会自动托管这两个目录（`backend/main.py`）：

- `user_frontend/dist` → `/`（SPA 兜底路由，刷新子路由不会 404）
- `admin_frontend/dist` → `/admin`（`/admin` 会 302 到 `/admin/`，其余交给 SPA 兜底）

所以**只要你构建了 dist，Nginx 就只需要做 TLS 终结和反代**，不需要单独配静态站点：

```
client ──443──▶ Nginx ──▶ 127.0.0.1:8000 (backend)
```

> 若启动日志出现「管理后台构建产物不存在，/admin 不可用」，就是 `admin_frontend/dist` 没构建。门户同理，此时 `/` 不会返回页面。

### 备选：让 Nginx 直接托管 dist

想省掉后端的一次转发，也可以让 Nginx 直接读文件，但**两个 SPA 都要配 try_files 兜底**：

```nginx
# 用户门户
location / {
    root /opt/Aetrix-Portal/user_frontend/dist;
    try_files $uri $uri/ /index.html;
}

# 管理后台（注意路径前缀）
location /admin/ {
    alias /opt/Aetrix-Portal/admin_frontend/dist/;
    try_files $uri $uri/ /admin/index.html;
}

# API 与协议面仍然反代给后端
location /api/  { proxy_pass http://127.0.0.1:8000; }
location /emby/ { proxy_pass http://127.0.0.1:8000; }
```

## 4. Nginx + HTTPS

仓库里给了完整示例：`nginx/nginx.conf`（含 Cloudflare 真实 IP、gzip、TLS、安全头）与 `nginx/ssl/`。

> ⚠️ 仓库里提交了 `nginx/ssl/fullchain.pem` 与 `nginx/ssl/privkey.pem` 两个文件。**不要直接拿去上生产**，请换成你自己的证书。另外请自查一下：如果这两个文件里确实是可用的真实私钥（而不是示例占位），它已经进了公开仓库，请**立即吐销该证书并重新签发**。

一份最小可用的站点配置：

```nginx
server {
    listen 80;
    server_name media.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name media.example.com;

    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    client_max_body_size 20m;

    # 直连流与 HLS 切片需要较大超时；转码首片可能等十几秒
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";   # WebSocket 通知
        proxy_buffering off;                      # 边转码边播放，不要缓冲
    }
}
```

> `proxy_buffering off` 与较长的 `proxy_read_timeout` 是播放体验的关键；默认 60s 超时会让转码首片前就断流。

**同时要做的两件事**：

1. `.env` 里 `EMBY_PUBLIC_URL` 改成这个域名（`https://media.example.com`），否则用户拿到的账号卡与一键导入地址还是旧的。
2. `.env` 里 `CORS_ORIGINS` 填上域名。同源部署其实不需要跨域，但设成具体域名可以避免任何「留空=允许所有源」的敞口。

## 5. 首次登录

1. **先有管理员**：新库里没有任何账号。注册第一个用户（`POST /api/user/auth/register` 或直接走门户注册页），然后把它设为管理员（`web_users.is_staff = True`；可用 `scripts/reset_admin_password.py` 辅助）。
2. 门户：`https://media.example.com/` → 用该账号登录。
3. 后台：`https://media.example.com/admin/` → 同一套账号登录（后台登录同样要求 `is_staff`，非 staff 会被拒）。

> 注意：后台**不会**把「第一个注册用户」自动变成管理员，必须显式提升，这也是为了安全。

## 6. 验证清单

```bash
BASE=https://media.example.com

curl -s -o /dev/null -w '%{http_code}\n' $BASE/                 # 200：门户页面
curl -s -o /dev/null -w '%{http_code}\n' $BASE/admin/           # 200：后台页面
curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/health       # 200：后端
curl -s $BASE/emby/system/info/public                            # 服务器名与版本
```

浏览器里再确认三件事：

- 门户首页能加载样式与图标（无 FOUC、控制台无 404）——若整页无样式，多半是 `base` 或托管路径错了；
- 刷新任意子路由（如 `/wallet`）不出现 404——SPA 兜底生效；
- 后台 `/admin/` 登录后能进「数据概览」——`/api/admin/*` 同源可达。

## 7. 更新前端

改了前端代码后只需重新构建并重启后端（后端在启动时读盘挂载静态目录）：

```bash
git pull
cd user_frontend && npm ci && npm run build-only && cd ..
cd admin_frontend && npm ci && npm run build && cd ..
sudo systemctl restart aetrix
```

> 旧版拆分栈的 `user_frontend/Dockerfile`、`admin_frontend/Dockerfile`（构建成自带 nginx 的镜像）属于 v2.0 之前的方案，统一后端下不需要；`deploy.sh` / `update.sh` 也是给那套栈用的。详见 [运维 · 排错](./operations.md)。

## 下一步

- 上线检查、备份恢复、排错 → [运维 · 备份 · 排错](./operations.md)
