# 运维 · 备份 · 排错

上线检查清单、安全基线、备份恢复，以及常见问题的排查路径。

## 部署自检（推荐每次上线前跑一遍）

> 自检不需要数据库以外的任何依赖，但**它跑的是真实的库**（默认开发库 `royalbot_unified.db`），
> 会在结束时删掉自己建的那一份数据；如果只想看界面，用 `--keep` 保留进程。

冒烟测试用的是进程内 TestClient（网络层被假服务替换），验证业务逻辑；**部署自检**验证的是
「这套东西真的起得来、真的能用」——它启动真实 uvicorn，然后用真实 HTTP 走关键链路：

```bash
python3 scripts/deploy_check.py            # 默认起在 127.0.0.1:8010
python3 scripts/deploy_check.py --port 9000 --timeout 90
python3 scripts/deploy_check.py --keep      # 自检完不杀进程（会打印 PID，方便手动看页面）
```

它会依次检查：依赖可导入、数据库可初始化、**两个构建产物存在且不落后于 `src/`** →
服务在超时内就绪 → 用户端 `/` 与管理端 `/admin/` 能拿到构建产物 → Emby 协议面
（`/emby/System/Info/Public`、`/emby/system/info/public`、`/System/Info/Public`）→
错误密码与未带 token 被拒、管理员登录 → 挂载类型表（含 rclone）→
建本机挂载 / 浏览 / 测试连接 → 绑定媒体库并触发扫描 → 条目真的入库 →
**再起一套分离部署**验证 EM 交出协议面、EA 配对可用、客户端能在 EA 上用 EM 的账号认证 →
删掉自检产生的数据并优雅停掉全部服务。

分离部署那一段不需要你另外配端口：默认单进程用 `--port`（8010），分离模式自动用 `port+1`
（EM 关网关）与 `port+2`（EA）。它还会跑一次**负向断言**：不设 `SECRET_KEY` 时 EA 必须拒绝启动。

输出会区分 `PASS` / `FAIL` / `WARN`：`WARN` 不影响退出码，`FAIL` 会让退出码为 1，适合当发布门禁。
两种常见的 `WARN` 都值得处理：

| WARN | 含义 | 怎么处理 |
| --- | --- | --- |
| 本机没有 `ffprobe` | 媒体探测退化为按文件大小建档（界面无分辨率 / 音轨 / 时长） | 装 ffmpeg（EA 那台机器） |
| 当前环境没有 `SECRET_KEY` | 自检自造了一个；EM 用临时随机密钥，**EA 会拒绝启动**、重启后登录态全失效 | 在 `.env` 里显式设置 `SECRET_KEY` |
| 构建产物落后于源码 | 部署上去的是旧界面（代码里看不出来） | 重新构建对应前端 |

## 上线检查清单

部署完先过一遍这张表，逐项打勾：

**基础**

- [ ] EM：`GET /api/health` 返回 200，`GET /` 是门户页面且有样式，`GET /admin/` 是后台登录页
- [ ] EM：刷新门户子路由（`/wallet`、`/history` 等）不 404（SPA 兜底生效）
- [ ] EA（分离部署）：`GET /api/health` 返回 `service=ea` 且 `paired_with_em=true`
- [ ] EA（分离部署）：`GET /emby/system/info/public` 与 `GET /System/Info/Public`（裸根）都返回服务器信息

**安全（详见下节）**

- [ ] `SECRET_KEY` 已设置为固定随机值，不是留空（EM 与 EA **必须相同**）
- [ ] `DATABASE_URL` 在 EM 与 EA 上指向同一个库（跨机分离部署必须用 PostgreSQL）
- [ ] `CORS_ORIGINS` 已填具体域名，不是留空
- [ ] `EMBY_ALLOW_LEGACY_TOKENS` 已废弃（旧数字 token 兼容代码已移除，无需再配）
- [ ] 全站 HTTPS 已生效，HTTP 自动跳转
- [ ] Nginx 使用的证书是**你自己的**（仓库里那份旧证书与私钥已删除；若你曾用过 `nginx/ssl/privkey.pem`，视为已泄露并重新签发）
- [ ] `/metrics` 未暴露到公网：服务端已默认只放行**本机/内网**来源（公网请求直接 403，见 `backend/metrics_guard.py`），
      确需公网采集时再设 `METRICS_ALLOW_REMOTE=true`，并继续在 Nginx 层限制来源
- [ ] 已改掉所有默认口令（数据库、管理员账号），无弱密码

**功能**

- [ ] 已建至少一个媒体库并完成一次扫描，能浏览到条目
- [ ] 门户能注册/登录；后台能用 `is_staff` 账号登录
- [ ] Emby / Infuse / SenPlayer 等客户端能连上并播放（直连或转码均可）
- [ ] 账号卡里的服务器地址与真实域名一致（`EMBY_PUBLIC_URL`）
- [ ] 支付网关、签到、邀请等经济配置按需在后台「系统设置」里配好
- [ ] 要做促销活动时，在「运营 · 优惠券」建券（比例/直减、门槛与封顶、按服限定）；
      优惠券默认开启，不需要时可以关掉——关闭后用户端不再显示优惠码入口

**运维**

- [ ] EM（与 EA）都已用 systemd 常驻并设为开机自启
- [ ] 有定时备份任务，且**实际恢复演练过一次**（数据库 + `.env` 里的 `SECRET_KEY` 一起备）
- [ ] 磁盘告警已配（转码切片与媒体库都吃空间；转码在 EA 那台）

## 安全基线

EM / EA 已内置这些防护（无需你配置）：

| 项 | 行为 |
| --- | --- |
| 认证限流 | 登录 8 次/分/IP、注册 5 次/时/IP、Emby 协议认证 10 次/分/IP、卡码预检 20 次/分、卡码核销 10 次/分 |
| 管理端保护 | `/api/admin/*` 全部要求 `is_staff`（未认证 401 / 非 staff 403） |
| 密码存储 | bcrypt 哈希；门户密码与 Emby 播放密码均为哈希；改密自动同步 |
| 空密码 | 无法通过 Emby 协议认证 |
| 明文密码 | 历史明文密码在用户登录时透明升级为 bcrypt |
| 账号卡 | 不返回密码明文，只给用户名与服务器地址 |
| 响应头 | `X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy`；API 路径禁用缓存 |
| 卡码蜜罐 | 诱饵码（盗版渠道流通）被使用时不暴露身份，直接封禁账号并落安全日志 |
| 设备风控 | 每用户设备上限 + 超限自动踢最久未使用的设备；被封禁设备登录即拒 |
| 下载门禁 | 站点级 `allow_download` 开关关闭后，客户端下载与 `/Items/{id}/File`（等价拉文件路径）一并被拦 |

需要**你**在部署时决定的三项，风险最高：

1. **`SECRET_KEY` 留空** → 每次重启密钥变更，所有登录态失效。这是最常见的「上线后大家莫名被登出」。
2. **`CORS_ORIGINS` 留空** → 等于允许所有来源请求 API。同源部署下不会有功能问题，但等于少了一道边界。
3. ~~开启 `EMBY_ALLOW_LEGACY_TOKENS`~~ → 该开关与背后的数字 token 兼容分支已删除，`Bearer <user_id>` 无法再冒充用户；只需保证 `SECRET_KEY` 固定且不泄露。

建议顺手开启的运营项：

- `device_limit_per_user`：限制单账号设备数，防止账号被共享；
- `login_log_retention_days`：日志保留天数，兼顾审计与磁盘；
- `subscription_required`：付费墙开关（管理员始终放行）；
- `coupon_reserve_hours`：优惠券预订的超时收尾时限（默认 24 小时，写 0 = 不自动清理）。
  「下单占了额度但一直不付款」的订单到点会自动关单并退回优惠额度——
  活动期间券很稀缺时把时限调小，避免额度被挂着。

## 备份与恢复

### SQLite（默认）

数据库就是仓库根目录下的 `royalbot_unified.db`（伴随 `-wal` / `-shm` 两个文件）。**不要直接 `cp` 正在被写入的库**，用 SQLite 自己的备份命令：

```bash
# 热备份（不锁写，推荐）
sqlite3 royalbot_unified.db ".backup '/backups/royalbot_$(date +%F_%H%M).db'"

# 验证备份可读
sqlite3 /backups/royalbot_2026-09-20_1200.db "PRAGMA integrity_check;"
```

恢复：

```bash
sudo systemctl stop aetrix
cp /backups/royalbot_2026-09-20_1200.db royalbot_unified.db
rm -f royalbot_unified.db-wal royalbot_unified.db-shm   # 清掉旧 WAL，避免与新库不一致
sudo systemctl start aetrix
```

### PostgreSQL

```bash
pg_dump -U royalbot royalbot | gzip > /backups/royalbot_$(date +%F_%H%M).sql.gz
# 恢复
gunzip -c /backups/royalbot_2026-09-20_1200.sql.gz | psql -U royalbot royalbot
```

### 还要一起备份的东西

- `.env`（含 `SECRET_KEY`，丢了等于所有人重新登录）
- 你服务器上 Nginx 的证书与续期/cron 配置（**不在仓库里**，仓库那份已删除）

> `scripts/backup.sh` / `backup_db.sh` / `restore.sh` 等是**旧版拆分栈（PostgreSQL + 容器）**的脚本：其 `BACKUP_DIR` 默认 `/backups`、产出 `royalbot_*.sql.gz`。如果你跑的是统一后端的 PostgreSQL，可以直接复用其 `pg_dump` 部分，但别指望它认识 SQLite 单文件部署。

定时任务示例（每天 3:10）：

```cron
10 3 * * * sqlite3 /opt/Aetrix-Portal/royalbot_unified.db ".backup '/backups/aetrix_$(date +\%F).db'" && find /backups -name 'aetrix_*.db' -mtime +14 -delete
```

## 常见问题

### Freebuff Hosting 报「找不到受支持的框架」

> Freebuff hosting could not identify a supported framework in package.json.
> Hosting builds React projects only: Vite + React, Next.js, and Create React App.

这不是配置写错，而是形态不匹配，改 `package.json` 绕不过去：

| 本项目 | Freebuff Hosting 要求 |
| --- | --- |
| 前端是 **Vue 3 + Vite**（依赖 `vue`、`@vitejs/plugin-vue`） | 只识别 **Vite + React** / Next.js / CRA |
| 仓库根目录**没有** `package.json`（主体是 Python 后端） | 需要根 `package.json` 中有受支持的框架 |
| 后端是 **Python FastAPI**，依赖数据库、Redis、ffmpeg，并自带 Emby 协议端点与 WebSocket | 构建镜像仅 Node.js，Python 只能以 `api/*.py` 无状态函数运行 |

即使硬把前端改成能通过框架识别的形态，部署出来也只是连不上 API 的空壳——播放、登录、支付、Emby 协议端点全部不可用。**请走本文档的服务器部署路径**（[EM 面板](./deploy-em.md) + [EA 网关](./deploy-ea.md)）。沙箱里的 `Preview`（`*.daytonaproxy01.net`）只用于开发预览，不是生产部署。

### `/admin/` 404 或白屏

- **404 / 日志提示「管理后台构建产物不存在」**：`admin_frontend/dist` 没构建。`cd admin_frontend && npm ci && npm run build`。
- **白屏且控制台一堆 `/assets/*` 404**：`admin_frontend` 的 Vite `base` 不是 `/admin/`，或 Nginx 用了 `root` 而非 `alias` 导致路径拼错。
- **能打开但接口全 404**：后台 API 基址是写死的 `/api/admin`，说明请求没走到后端（多半是分流规则写成了 `/admin/api/...`）。

### 整站没有样式

门户的 Vite `base` 是 `/`，必须由**根路径**托管（`/assets/...`）。若你把门户挂到 `/app/` 之类的子路径下，静态资源会全 404——本项目不支持子路径部署门户，请把门户放在根、后台放在 `/admin`。

### 播放报 401 / 403

- **403 且提示需要会员**：付费墙生效。`subscription_required` 开启时，非会员的 `PlaybackInfo`、直连流、HLS 会话、下载都会被拦；管理员（`is_staff`）始终放行。用户需要开通会员（卡码或订阅）。
- **401**：客户端没有有效 token。确认客户端用的是门户账号（不是旧账号），且服务器地址正确（`EMBY_PUBLIC_URL`）。
- **HLS 变体/切片 401**：属历史缺陷，v2.5.5 起切片地址自带 `api_key`；如果你还在跑更早版本，请升级。

### HLS 转码 503 或首片一直转圈

- **503 且日志提示找不到 ffmpeg**：装 ffmpeg，或把 `EMBY_FFMPEG_PATH` 指向真实路径。直连播放不需要 ffmpeg。
- **首片慢**：首片需要先编码出若干秒内容，属正常。Nginx 默认 60s 读超时会提前断流，请把 `proxy_read_timeout` 调到 300s 并关闭 `proxy_buffering`（EA 侧配置见[EA 网关部署](./deploy-ea.md)的 Nginx 一节）。
- **切片 404**：客户端请求早于 ffmpeg 写出，后端会短暂等待；若 ffmpeg 已退出则明确返回 503，去看 `journalctl -u aetrix` 里的 ffmpeg 报错（常见原因是源文件不可读或磁盘满）。

### 数据库报 `database is locked`

v2.1.0 起已启用 WAL 与 `busy_timeout`，正常不会再出现。若仍出现：确认没有别的东西在用同一个库文件（比如旧栈的容器也在读写同一个 `royalbot_unified.db`），并检查是否有残留的 `-wal` / `-shm` 属于其他进程。

### EA 启动即退出，日志提示与 EM 未配对

这是**有意设计**，不是 bug。EA 的硬依赖是共享密钥与共享库，不满足就拒绝启动，避免出现"服务起得来、但谁都认证不了"的假健康：

| 日志 | 原因 | 处理 |
| --- | --- | --- |
| `SECRET_KEY 未设置` | 客户端 token 由 EM 签发、EA 校验 | 让 EA 与 EM 用同一份 `.env`（值必须一致） |
| `共享数据库缺少 EM 的表：…` | EA 指向的库不是那套，或 EM 还没初始化过 | 先跑 EM（`python serve.py`）并至少建一个媒体库；跨机部署改用同一个 PostgreSQL |

另有一条**软警告** `EM 面板当前不可达`：只是探测，不阻断——EM 短暂重启不应该掐断正在播放的会话。

### 求片批了但片子一直没进来（下游没接）

求片审批只是「同意」，**真正去把片子弄进来的是外部服务**。顺序排查：

1. 后台「系统 → 服务器」里看四张统计卡：`MoviePilot` / `qBittorrent` 是不是 0 台，
   或者有但「可用」是 0——那就是还没接好（或凭据/地址不对），求片页会直接提示去这里添加；
2. 点对应服务器的「测试」，看失败原因：
   - **MoviePilot**：「API 密钥可用」只代表能查订阅；要**提交订阅**必须再填用户名 + 密码
     （它用登录令牌控制 `/api/v1/subscribe/`）。只填了 API 密钥时面板会明说这一点；
   - **qBittorrent**：报「用户名或密码不对」就是 Web UI 的登录名/密码（首次启动时 qB 会打印
     临时密码，在「选项 → Web UI」里可改）；报「没有返回会话 Cookie」通常是把地址指到了别的服务；
   - 报「无法连接」：跨机访问先确认 qB / MoviePilot 监听的是 `0.0.0.0` 而不是 `127.0.0.1`。
3. 打开「内容 → 求片管理」，看那一行的「转交外部服务」列：显示「失败」时把鼠标停在原因上，
   失败原因原样来自下游（例如「MoviePilot 拒绝了登录令牌」）；
4. 手动重推：待审或已批准的记录都有「交 MoviePilot / 交给 qB」按钮。
   注意 **qBittorrent 是下载器，不会自己去找片子**——它需要磁力链接或 `.torrent` 地址；
   「自动搜索并下载」靠 MoviePilot（它自己带下载器配置）。

> 批量求片的正确姿势：同时接上 MoviePilot 与 qBittorrent。求片 → 一键交 MoviePilot，
> 它自己去搜索下载整理；已经找到链接的（比如从群里拿到的磁力）直接交给 qB 即可。

### 同一条挂载，EM 能用不代表 EA 能播（分离部署必看）

挂载里的配置有相当一部分是**「跟着服务器走」**的：`local` / `strm` 的路径、rclone 的 RC 地址
（默认 `127.0.0.1:5572` 指的是各自那台机器自己）与 rclone 可执行文件。
而同一条 `StorageMount` 会被**两个进程各自解析**：**EM（面板）** 负责扫描、目录浏览、
后台「测试连接」，**EA（网关）** 负责播放出流。所以后台测试通过，**并不代表那台 EA 能播**——
以前这类不一致只会在之后以扫描 `failed_roots` 或播放 502/404 的形式暴露，排查很绕。

现在后台把两个视角都摊开：

- **「存储挂载」页的「EM / EA 可达」列**：逐条给出两个节点各自的结论（可达 / 不可达 / 未体检）、
  失败原因与最近体检时间。**被媒体库引用、却在 EA 上不可达**的挂载会单独报红并列出名字——
  这些库会「扫得到、播不了」。只有当前出流节点是 EA 时才算阻断性告警，
  一体化部署与外部 Emby 模式都不会误报。
- **保存（或「设为当前」）「服务器 · Emby 总览」里的后端服（EA）时**会自动拉一次 EA 视角的体检，
  不用你去逐个点「测试」（失败的挂载列表也会随之刷新）；总览页的「挂载体检」列直接给出
  「N 条不可达」与不可达挂载名，页头的「一键体检」可随时重拉。
- 两个按钮：**「本机体检」**=在 EM 进程里逐条跑探测，**「EA 体检」**=向 EA 再拉一次
  （EA 连不上时**保留上一次逐条结果**并提示快照已失效，不会把结论全抹成未知）。
- 修法通常二选一：在那台 EA 机器上把同样的路径 / rclone 配好；或者改用网络型来源
  （`115` / `webdav` / `alist` / `s3` …），它们只要两台机器能出网就行。

> EA 上的体检端点是 `GET /api/admin/mounts/health`，鉴权用两端共享的 `SECRET_KEY`
> （请求头 `X-Panel-Key`）。**EA 与 EM 的 `SECRET_KEY` 必须一致**，否则会得到
> 「EA 拒绝了面板密钥」；该端点不存在于 EM 上，也不面向公网。

### 挂载来源不可用（媒体库扫不出内容 / 扫描日志里出现「跳过清理」）

「挂载」是媒体库的内容来源，后台「存储挂载」页每个类型都可以单独「测试」。扫描时来源不可用（目录不存在 / 挂载停用 / 凭据失效 / 网络不通）**不会**报错退出，而是记入 `failed_roots` 并**跳过清理阶段**——这是有意的安全网，避免把「读不到」当成「文件已删除」批量误删条目。排查顺序：

1. 后台「存储挂载」里点对应挂载的「测试」：能看到「Cookie / 令牌 / 密钥」字样的错误就是凭据问题，重新粘贴即可（密钥字段留空表示不修改）；
2. 本机类型（`local` / `strm`）报「目录不可用」：挂载点掉了（rclone / CloudDrive2 / SMB / NFS 断了），或者容器里没把宿主目录挂进来；
3. 远程类型报网络错误：EM / EA 所在机器能不能出网、域名是否被网络策略改写（用 `MOUNT_*_BASE` 覆盖入口）；
4. 媒体库若绑定了多个来源，确认要用的那个没有被停用（停用的挂载不会参与扫描，也不能被新绑定）。

常见类型对应的参数都在后台表单里；入口地址与超时可以用 `env.example` 里的 `MOUNT_TIMEOUT` / `MOUNT_UA` / `MOUNT_S3_REGION` / `MOUNT_ALIYUN_ENDPOINT` / `MOUNT_QUARK_BASE` / `MOUNT_GRAPH_BASE` 覆盖。

> 远程挂载的条目入库为 `mount://<挂载 id>/<相对路径>`，播放时才解析成真实直链并由服务器按 Range 代理转发。所以**客户端拿不到你的 Cookie / 令牌 / 预签名地址**，也不会因为直链过期而播放失败。

### rclone 挂载怎么选模式

rclone 挂载是唯一一种「一种类型接住所有后端」的来源（Google Drive / OneDrive / S3 / 115 / 夸克 / SFTP …），它复用你机器上已有的 rclone remote，面板里不用重填密钥。两种模式：

- **rc（推荐）**：宿主机上先起一个 rc 服务，rclone 挂载里选 rc 模式并填地址（支持用户名 / 密码）：
  ```bash
  rclone rcd --rc-serve --rc-addr 127.0.0.1:5572
  # 带认证（生产建议）：--rc-user=user --rc-pass=pass
  ```
  列目录 / 测试走 RC API，播放地址直接取自 rc-serve（rclone 自己处理 Range）。容器部署时注意 `127.0.0.1` 指向的是容器自己，要改成宿主机地址（如 `http://host.docker.internal:5572`）并让 rc 监听 `0.0.0.0`。
- **cli（兜底）**：直接调用 rclone 可执行文件（`lsjson` / `cat` / `link`）。适合「机器上有 rclone 但不想常驻 rc」；EM / EA 进程必须能找到 rclone（不在 PATH 就用 `MOUNT_RCLONE_BIN` 或配置里的绝对路径）。

两个容易踩的点：

1. **列目录正常但一播就 404** → `--rc-serve` 没开。后台测试连接会提示「rc-serve 似乎未开启」。
2. **`cli` 模式报「rclone 未返回公开直链」** → 该后端不支持 `rclone link`（比如部分网盘）。改用 rc 模式，或把网盘 `rclone mount` 到本机后用 `local` 挂载。

> 已经 `rclone mount` 到本机目录的场景，直接用 `local` 挂载那个目录更直接（走本机文件，没有代理开销）。

### 115 直挂：列目录失败 / 提示 Cookie 失效

115 直挂（存储挂载类型选 **115**）用 Cookie 型 Web API 列目录、换直链，**没有转存任务那一层**
（分享链接转存已在 v2.18.0 移除）。排查顺序：

1. 后台「**115 账号**」里点「校验」，失效就重新粘贴（浏览器里登录 115 后复制 `uid=…; cid=…; seid=…; kid=…`）；
2. 用该账号点「浏览」实测一次列目录：能看到目录说明 Cookie 与出口网络都通，看不到就是 Cookie 或网络问题；
3. 媒体库若单独绑定了账号，确认那个配置档没有被停用或删除（停用会自动回退默认账号）；
4. 没有配置档时只能走服务器级 `PAN115_COOKIE` 兜底，注意要在**面板（EM）与播放节点（EA）两侧**
   的 `.env` 里都有：列目录在 EM，播放换直链在 EA。

### 每次重启后所有人被登出

`SECRET_KEY` 没设（分离部署时还可能被 EA 与 EM 设成了不同的值）。补一个固定值后重启：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# 写入 .env 的 SECRET_KEY=（EM 与 EA 共用同一份 .env），然后：
# systemctl restart aetrix-em aetrix-ea
```

### 多服运营：什么按服、什么全局

判断标准只有一条：**这个维度会不会改变系统的判断**。会改变的才按服；只是给人看的，优先全局或派生，
不要存一份会漂的副本（“归属”存了但没人读，比不存更糟——界面会让人以为它生效了）。

| 维度 | 按不按服 | 为什么 |
| --- | --- | --- |
| 媒体库 / 存储挂载 | **按服**（挂载可留空 = 未分配） | 它们决定**哪些节点能出流、哪些用户看得到**；挂载又是主机相对资源（乙服的机器未必碰得到甲服挂的盘） |
| 服务器（EA / Emby） | **按服** | 一个服一个出流入口；同一个服可以有多台 EA |
| 套餐 / 订阅 | **按服** | 一个服一个价；付费墙按服严格判定（甲服的会员不能在乙服的 EA 上播） |
| 卡码（注册码 / 续期码 / 白名单码） | **按服** | 它决定**开通哪个服的会员**：乙服的注册码开通乙服的会员，续期码只在同服内叠加 |
| 每服配置（`emby_active_mode` / 入口 URL / api_key / 挂载体检快照） | **按服** | 一个服一个 Emby 入口；默认服沿用历史键名，其它服用 `<键名>__r<服 id>` |
| 求片 | **按服记录，出口全局** | 求片要能回答“这部片进哪个库”（单服自动带出、多服让用户选）；但 MoviePilot / qB 是**一套全局共享**的下载与整理器——多服共用一个下载器比每个服各揠一份更合理，不会重复下载 |
| 用户 / 设备风控 / 登录日志 | **全局** | 一个账号一套凭据登录所有服；同一台设备就是同一台设备，按服封会出现“甲服封了乙服还能用”的破窗 |
| 余额 / 积分 / 兑换码 | **全局（共用一份）** | 一个用户一份钱袋：多服共用最省事，但意味着可跨服补贴（甲服的积分可以在乙服买套餐）。若将来要做**分账**（退款 / 对账 / 结算拆开），得单独立项，并给历史流水**快照**归属，而不是靠外键派生 |
| 公告 / 工单 / 邀请 | **全局** | 一套运维通知对所有人；工单只需要在详情里看出“用户来自哪个服”（报表用），不该把筛选做成硬门槛 |

一句话：**内容、卖什么、卖给谁、谁能出流 → 按服；账号、钱袋、风控、运维 → 全局。**

### 客户端看不到自己在别的服买的会员 / 会员明明有效却播不了

多服部署下**会员是一个服一个的**：

1. 截图看用户到底买的是哪个服（「订阅管理」页切到「全部服」，或用户端个人中心的会员列表会带服名）；
2. 确认他连的是**那个服**的地址（「服管理」页每个服下面的 `public_url`）；
3. 甲服的会员在乙服的 EA 上会被付费墙拦住，这是预期行为，不是 bug。

### 某台 EA 什么都看不到 / 只看到一部分媒体库

EA 只报自己服务得上、且碰得到的内容（见 [EA 部署 · 多机多服](./deploy-ea.md#10-多台-ea-与多个服多机多服)）：

| 现象 | 原因 |
| --- | --- |
| 客户端一个库都没有 | 那台 EA 的 `REALM` 与面板里它的归属服不一致（去「服管理」页点「节点体检」，会直接报「自称属于 X，与这个服不一致」） |
| 只有一个库（或几个） | 其余库的「归属节点」不是它：在「媒体库」页把库的归属改成它，或改成「未分配」（未分配 = 所有节点可见） |
| `GET /api/health` 里 `node.filtering=false` | 这台 EA 既没配 `NODE_KEY` 也没配 `REALM`，也不属于任何服：面板还没把它认领进去 |

### 客户端连不上服务器

1. 用**手机流量**访问 `https://你的域名/emby/system/info/public`，确认公网可达（排除只开了内网端口）；
2. 服务器地址**不要**带 `/emby` 后缀，客户端自己会拼协议路径；
3. HTTPS 证书必须被客户端信任（自签证书在部分播放器上会被直接拒绝）；
4. `EMBY_SERVER_ID` 若中途变过，客户端会把同一台服务器当成新服务器，需要重新添加。

### 旧版拆分栈还在吗

**不在了。** v2.0 之前的拆分式部署栈（`admin_backend/`、`user_backend/`、`docker-compose.yml`、`deploy.sh`、`update.sh`、`dev.sh`、旧 `.env` 模板、旧 `nginx.conf` 与 `user_frontend_dist/`）**已从仓库删除**。它们与当前 EM/EA 架构不共享数据库结构，留着只会让人误用。

连带清掉的还有一批“留着就会误导”的残留：三个 `Dockerfile` 与两个前端 `nginx.conf`
（没有任何文档在用它们，且 `admin_frontend/nginx.conf` 反向代理指向的是已删除的 `admin_backend:8080`）、
根目录的两份一次性报告（`FIX_REPORT.md`、`FRONTEND_BACKEND_LINKAGE.md`）、
`admin_frontend/docs/navigation-architecture.md`（描述的是未实现的导航重构，
它提到的组件与配置文件在代码里都不存在）、走开发库的旧 `pytest.ini` + `tests/`，
以及跑不通的 `telegram_login_bot/`（它调用的 `{WEB_URL}/api/user/auth/telegram-login` 从来不存在）。

需要当年那套文件时从 git 历史取回即可：

```bash
git log --oneline -- docker-compose.yml      # 找到删除前的最后一个提交
git show <那个提交>:docker-compose.yml > /tmp/docker-compose.yml
```

> ⚠️ 那套栈里曾经**硬编码过生产库口令**，`nginx/ssl/privkey.pem` 还是一把**真实域名（login.laodaemby.xyz）的 EC 私钥**。如果你用过旧栈：
> 1. **立即更换 PostgreSQL 与 Redis 口令**；
> 2. 那把 TLS 私钥视为已泄露，**吊销并重签**证书；
> 3. 仓库历史里仍有旧口令（git 历史没有重写），必要时用 `git filter-repo` 清理或直接轮换。

新部署请直接按本文档走：EM（`serve.py`）一个进程同时托管门户、后台与 API，静态产物由 EM 自己托管，不再需要三个容器。
