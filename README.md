# Aetrix Portal

> **完全自建 Emby 影视服务系统** —— 内置自研 Emby 兼容媒体服务器 + 用户门户 + 运营后台

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-latest-blue.svg)]()
[![CI](https://github.com/xzb177/Aetrix-Portal/actions/workflows/ci.yml/badge.svg)](https://github.com/xzb177/Aetrix-Portal/actions/workflows/ci.yml)

**Aetrix Portal 把「媒体服务器 + 会员运营 + 客户端接入」装进一个仓库**：媒体库扫描与刮削、
直连流与 HLS 转码、订阅与积分支付、求片与工单、多服多节点出流，全部自带 —— 不装官方 Emby/EmbyServer，
也不需要一套容器编排。

| 代号 | 是什么 | 谁在用 |
| --- | --- | --- |
| **Aetrix EM** | **控制面**：门户、管理后台、扫描、经济系统 · `python serve.py` | 浏览器：用户与管理员 |
| **Aetrix EA** | **数据面**：Emby 协议网关、拉流、转码、字幕 · `python serve_emby.py` | 播放器：Infuse / Fileball / Forward+ / Hills / SenPlayer / 官方 App |

两半共用同一个数据库与 `SECRET_KEY`：可以只跑 EM 一个进程（`ENABLE_EMBY_GATEWAY=true`，默认），
也可以把 EA 拆到另一台机器上专门出流。部署见 [docs/](docs/README.md)，运维见 [docs/operations.md](docs/operations.md)。

> **名字**：`Aetrix` = **Aether**（以太，串流）+ **Matrix**（矩阵，多服 / 多节点）；
> `Portal` 是它的角色 —— 面板即门户，字节由 EA 送出。全篇的 **EM / EA** 就指上表的两个部署单元。

## 🎯 完全自建架构（v2.0）

本项目后端**内置完整的 Emby 协议兼容媒体服务器**，无需安装官方 Emby/EmbyServer，Emby 客户端（Infuse、Forward、Hills、SenPlayer、官方 App）可直接连接：

- **EM（面板）** 与 **EA（Emby API 网关）** 可分开部署：客户端直连 EA，面板跑 EM，两者共用同一个数据库与 `SECRET_KEY`（见 [docs/](docs/README.md)）
- 也可以只跑一个进程（`ENABLE_EMBY_GATEWAY=true`，默认），由 `backend/main.py` 一并提供以下全部端点：

```
Emby 客户端 ──HTTP──▶ backend/main.py（单进程单端口）
                        ├── /emby/*                 Emby 协议兼容 API
                        │   ├── /Users/AuthenticateByName   用户名密码认证
                        │   ├── /Users/{uid}/Items          媒体库浏览/搜索/筛选
                        │   ├── /Items/{id}/PlaybackInfo    播放信息（GET/POST）
                        │   ├── /Videos/{id}/stream         直连流（Range 分段）
                        │   ├── /videos/{id}/master.m3u8    HLS 转码（ffmpeg，切片自带 api_key）
                        │   ├── /Videos/{id}/{mid}/Subtitles/{i}/Stream.{fmt}  字幕投递
                        │   ├── /Search/Hints               全局搜索
                        │   ├── /Items/{id}/Images/{Type}/{Index}  海报/背景图
                        │   ├── /Genres /Studios /Items/Counts /Items/Filters  分类与统计
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
- 🌐 **网页媒体库** - 浏览/搜索/详情/在线播放（直连 + HLS 转码）
- 📅 **每日签到** - 连签加成，积分日结
- 💰 **钱包** - 积分充值（易支付）/ 兑换码核销 / 优惠券抵扣 / 订单与流水
- 💳 **订阅购买** - 套餐在线购买，支付回调自动开通
- 👥 **邀请返利** - 邀请双向奖励 + 下级充值返利
- 📺 **媒体求片** - 用户求片 + 投票系统
- 🎫 **工单系统** - 用户客服工单
- 📢 **站内消息** - 系统公告和通知
- 🤖 **AI 助手** - 由站长自己配置的模型回答使用问题（未配置时不显示入口）
- 📱 **一键导入** - 账号卡 + 播放器 URL Scheme 导入

### 管理后台

导航按**交付链**组织（v2.25.0）：仪表盘 / 用户与账号 / 媒体与交付 / 求片与内容 / 运营中心 /
服务支持 / 系统与审计 —— 不用先理解内部架构（服务器、媒体库、挂载原本拆在多个技术分类里）。

- 🧭 **仪表盘** - 交付链数据卡（用户总数 / 当前播放 / 待处理求片 / 待处理工单 / 扫描状态 /
  存储健康，每张点进明细页）、待办条、各服概况、趋势图、播放排行
- 🏠 **多服（作用域）** - 一个面板可以同时运营多个「服」（独立的一套播放服务）：自己的媒体库 /
  存储来源 / 套餐 / 订阅 / 卡码 / 求片。它不再是一个要先学的模块：**当前服与范围在
  「服务器与线路」页里选**（顶栏切换器同步），各页作用域跟着走；一个服可以部署到多台机器、
  多台 EA 同时出流（内容与扫描归属按节点划分，会员按服判定）
- 👤 **用户** - 搜索/筛选、用户 360° 画像（订阅/积分/订单/邀请/签到/观看）、禁用启用、重置密码、消息与广播、管理员授权
- 💎 **订阅与权益** - 生效中 / 7 天内到期 / 已过期总览，延长与续订；默认只看当前服，可切「全部服」跨服汇总
- 🛒 **商品与套餐** - 订阅套餐与充值包 CRUD（订阅套餐一个服一个，充值套餐全服共用）
- 🖥️ **服务器与线路** - **媒体与交付的入口页**：按服给出每台出流入口（后端服 EA / 已有 Emby）的连接、`NODE_KEY` 认领、EA 视角的挂载体检与媒体库归属，不一致处直接列成告警；顶部选「当前服 / 范围」，直接点去媒体库与存储来源；「一键体检」真去问每台 EA「你是谁、属于哪个服」；新增即体检、一键设为当前使用；EA 归属某个服，MoviePilot 与 qB 可「全服共用」
- 🧾 **订单** - 充值/订阅订单筛选、营收统计、人工补单
- 🎟️ **兑换码** - 批量生成（积分型/订阅型）、停用启用、核销审计
- 🏷️ **优惠券** - 付费时抵扣（比例/直减、门槛与封顶、按服限定）、额度预订制（关单/退款自动退回）、超时未支付自动收尾、核销记录与审计
- 🎁 **邀请与积分** - 邀请台账、全站积分流水、按用户搜索后人工调整积分
- 🛡️ **管理员与权限** - 三层角色（超级管理员 / 运营 / 只读审计）：判定只在服务端一处（鉴权依赖），
  只读角色挡下**一切**写操作（扫描、体检、改库、踢人下线、全站广播、Emby 兼容面也算写）；
  不能改自己、不能没有超级管理员、
  被停用的账号不能当管理员；升级上来的老管理员按超级管理员处理（权限不变）
- 🎛️ **客户端策略** - 「客户端到底允许做什么」一页说完：转码开关 / 并发转码上限 / 码率上限 /
  UA 黑（白）名单准入（被拦的客户端连播放信息都拿不到，管理员不受限）+ 本进程运行态
  （几路转码 / 上限 / 由谁出流 / ffmpeg 是否可用）；下载开关与设备风控也在这一页
- ⚙️ **系统设置** - 注册策略（开放/注册码/关闭）与签到、兑换、支付网关、邀请返利规则在线配置
- 🔌 **外部服务能力中心** - 网络代理 / 人机验证 / 邮件与模板 / Telegram / AI 模型 / IP 归属地
  六张卡片 + **站点与品牌**（站名 / Logo / 主题色 / SEO）；**面板只提供能力，凭据自己填**
  （不内置任何 Key），每个能力都能当场「测试连接」——详见 [能力中心](./docs/capabilities.md)
- 🔑 **注册码** - 批量生成、次数/过期管理、使用审计
- 📚 **媒体库** - 卡片上直接写清每个库的**服务（归属节点）/ 来源（几条路径 + 几个挂载）/ 扫描状态 / 条目数**；库/路径/扫描/条目管理、按来源拆分的扫描明细
- 🗂️ **存储来源** - 把内容接进媒体库：本地目录 / STRM / 115 / WebDAV / AList / S3 / 阿里云盘 / 夸克 / OneDrive / rclone（远程来源代理播放，凭据不下发）；每条都标明**被哪些媒体库使用**
- 📺 **会话监控** - 在线用户、强制下线
- 🎫 **工单处理** - 工单会话、状态/优先级流转、回复与关闭
- 📣 **公告管理** - 发布/编辑/置顶/停用，联动全站推送
- 📝 **日志审计** - 全量管理操作流水，按操作类型快捷筛选 + 关键字检索

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
- 密码 bcrypt 存储（门户密码与 Emby 播放密码均为哈希存储）；注册自动生成自建 Emby 凭据，改密自动同步 Emby 播放密码
- 兼容：`/api/user/emby/*` 等门户端点接受 JWT 与 Emby 客户端 token；旧版「纯数字即 user_id」的 token 已**彻底移除**（不再有任何环境变量可以开启）

### 安全机制

- 🔐 **认证限流**：登录（8 次/分/IP）、注册（5 次/时/IP）、Emby 协议认证（10 次/分/IP）
- 🔐 **管理端保护**：`/api/admin/emby/*` 全部端点要求 `is_staff` 用户（未认证 401 / 非 staff 403）
- 🔐 **密码策略**：空密码无法通过 Emby 协议认证；旧明文密码在登录时透明升级为 bcrypt
- 🔐 **账号卡**：不返回密码明文，仅返回用户名与服务器地址
- 🔐 **安全响应头**：`X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy`；API 路径禁用缓存
- 🔐 **CORS**：生产环境请设置 `CORS_ORIGINS` 环境变量限制来源域名

## 📦 目录结构

```
Aetrix-Portal/
├── serve.py                    # EM（面板）启动器
├── serve_emby.py               # EA（Emby API 网关）启动器（分离部署用）
├── emby_api/
│   └── main.py                 # EA 应用：只含 Emby 协议面 + 配对硬校验
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
│       ├── streaming.py        #   直连流/Range/HLS 转码（会话复用 + 失效回收）
│       ├── subtitles.py        #   字幕投递（外挂直出 / 内封 ffmpeg 抽取 → VTT）
│       ├── api.py              #   Emby 协议兼容 API（/emby/*，含客户端兼容补齐）
│       └── portal.py           #   门户集成 API（账号卡/收藏/统计/管理）
├── user_frontend/              # 用户前端 (Vue 3)
├── admin_frontend/             # 管理前端 (Vue 3)
└── scripts/
    ├── smoke_test_emby.py            # 自建 Emby 端到端冒烟测试
    ├── smoke_test_emby_gateway.py    # Emby 网关兼容面 + 路由优先级回归
    └── smoke_test_auth.py            # 门户认证（JWT）端到端测试
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

只有一个后端：仓库根目录的 `backend/`（EM 面板 + 自建 Emby），依赖在 `backend/requirements.txt`。

```bash
pip install -r backend/requirements.txt
python serve.py          # EM 面板 :8000
python serve_emby.py     # EA 协议网关 :8001（分离部署时才需要）
```

### 持续集成（CI）

[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) 在 push 到 `main`、开 PR 与手动触发时跑三组检查，口径与本地一致：

| 任务 | 内容 |
| --- | --- |
| 前端 · `user_frontend` / `admin_frontend` | `npm ci`（锁文件与 `package.json` 不同步即失败）→ `npm run type-check`（vue-tsc）→ `npm run build` |
| 后端 · 冒烟测试 | `scripts/smoke_test_auth.py`、`scripts/smoke_test_admin_v240.py`、`scripts/smoke_test_admin_account.py`（TestClient 进程内，不需要构建产物） |
| 后端 · 部署自检 | 还原前一个任务产出的 `dist` 后跑 `scripts/deploy_check.py`：**真起 uvicorn、真发 HTTP**，覆盖单进程与 EM/EA 分离两套形态 |

这四个检查在 `main` 上是**必需状态检查**（branch protection）：PR 必须等到它们全部通过才能合并，
挂着失败或还在跑的检查时 GitHub 会拒绝合并（`BLOCKED`，提示 `the base branch policy prohibits the merge`）；
全部通过后转为 `CLEAN` 才可合入。`strict`（要求分支先与 `main` 同步）未开启，
`enforce_admins` 也未开启（仓库管理员仍可直接向 `main` 推送）。

本地复现（与 CI 同序）：

```bash
cd user_frontend  && npm ci && npm run type-check && npm run build && cd ..
cd admin_frontend && npm ci && npm run type-check && npm run build && cd ..

DATABASE_TYPE=sqlite DATABASE_URL=sqlite:///./ci.db REDIS_ENABLED=false \
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  python3 scripts/deploy_check.py
```

## 🚢 部署

整套系统可拆成两个独立部署的服务：

| | **EM · Emby Manager（面板）** | **EA · Emby API（网关）** |
| --- | --- | --- |
| 面向 | 浏览器（用户 / 管理员） | 播放器客户端（Infuse / Fileball / Forward+ / SenPlayer / 官方 App） |
| 管什么 | 注册 / 登录 / 套餐 / 续费 / 充值 / 邀请 / 卡码 / 签到 / 工单 / 风控 + 管理后台 | 只兑现协议：认证、媒体库浏览、拉流、转码、字幕、进度上报 |
| 入口 | `python serve.py`（默认 :8000） | `python serve_emby.py`（默认 :8001） |

**EM 是唯一事实来源**，EA 的用户 / 媒体库 / 策略全部来自 EM 写入的共享数据库，所以 **EA 不能脱离 EM 单独运行**（缺共享密钥或共享库时启动即被拒）。也可以只跑 EM 一个进程，由它一并提供协议面（`ENABLE_EMBY_GATEWAY=true`，默认）。

完整文档在 [`docs/`](./docs/README.md)：

| 文档 | 内容 |
| --- | --- |
| [文档中心](./docs/README.md) | EM / EA 架构一图、该看哪一篇、为什么两者都必须单进程 |
| [EM 面板部署](./docs/deploy-em.md) | 环境要求、`.env` 逐项说明、前端构建与静态托管、Nginx + HTTPS、首次登录、媒体库扫描、运营配置 |
| [EA 网关部署](./docs/deploy-ea.md) | 与 EM 的配对硬依赖、独立地址规划、systemd、客户端接入、付费墙 / 限流 / 踢设备、转码排错 |
| [运维 · 备份 · 排错](./docs/operations.md) | 上线检查清单、安全基线、备份恢复、常见问题 |
| [性能与资源预算](./docs/performance.md) | 扫描/播放的资源设计、可调参数、实测口径、下一步瓶颈 |

最短路径（单机裸部署）：

```bash
pip install -r backend/requirements.txt
cp env.example .env                    # 至少设置 SECRET_KEY 与 EMBY_PUBLIC_URL

cd user_frontend  && npm ci && npm run build-only && cd ..
cd admin_frontend && npm ci && npm run build      && cd ..

python3 scripts/create_admin.py        # 新库里先造一个管理员（随机强密码，会打印）
python serve.py                        # EM 面板 :8000（门户 / 管理后台 / API）
python serve_emby.py                   # EA 网关 :8001（客户端连它，分离部署时才需要）
```

再用 Nginx 终结 TLS 并将两个域名分别指向它们即可（含网页播放器所需的 `/emby/*` 反代，见文档）。

> ⚠️ **Freebuff Hosting 无法部署本项目**：该平台只构建 React 项目（Vite + React / Next.js / CRA），而本项目是 Vue 3 + Python FastAPI。原因与替代路径见 [运维 · 排错](./docs/operations.md#freebuff-hosting-报找不到受支持的框架)。

## 📝 更新日志

完整历史（按版本倒序、含每个版本的来龙去脉）在 [CHANGELOG.md](./CHANGELOG.md)；这里只留最近两个版本。

### v2.30.0 (2026-09-24) — 统一品牌与命名：RoyalBot → Aetrix
- 🏷️ **仓库与文档统一叫 Aetrix Portal**：README 标题与目录树、许可证署名、文档标题、
  两个前端标题与 manifest、设计令牌注释、监控配置、运维脚本抬头全部改到同一个名字
  （此前一半叫 Aetrix、一半叫 RoyalBot，改个站名要在两种叫法之间猜）
- 🧩 **默认站名对齐**：管理端默认站名 `RoyalBot` → `Aetrix`，与用户端、后端默认值
  （`Aetrix`）和 Emby 服务器名默认值一致；后台「站点与品牌」填过站名的部署不受影响
- 🗂️ **数据库默认名 `royalbot_unified.db` → `aetrix_unified.db`**：**老部署不会被改名**——
  新名不存在而老文件还在时继续沿用老文件（改品牌不该让任何人「换了个文件名就丢整站数据」）
- 🔌 **运维标识跟着走**：PostgreSQL 默认库/账号、容器名 `royalbot_postgres`、systemd 单元
  `royalbot-em/ea`、备份目录 `/opt/Aetrix-Portal/backups`、Prometheus 作业名与告警文案
- ⚠️ **唯一需要留意的一处**：`EMBY_SERVER_ID` 默认值改为 `aetrix-emby-server`。若你的
  `.env` 没显式设过它，升级后客户端会把服务器认成新的一台（重登一次即可）；想避免就在
  `.env` 里保留旧值
- 📉 **README 瘦身**：内联的 700 行版本历史与 `CHANGELOG.md` 重复（还把 README 撑到 97 KB），
  改为「最近两个版本 + 指向 CHANGELOG.md」；历史仍完整保留在 changelog 与 git 里

### v2.29.0 (2026-09-23) — 后台：一个按钮 + 弹窗里详细操作
- 🪟 **行内按钮簇收进弹窗**：多个页面行尾原来并排摆着 4~5 个按钮（点下去只有一个确认框，
  需要的信息却在带 tooltip 的列里）——现在行里只留一个入口，弹窗里先看全部事实再动手：
  求片处理 / 管理员管理 / 设备详情与处置 / 订单详情与处理 / 公告管理 / 优惠券管理 /
  115 账号管理 / 存储来源管理 / 服务器管理
- 🔄 **弹窗不关，快照就地刷新**：动作做完弹窗里那一行换成后端最新结果（状态、校验结果、额度、
  转交结果），长流程（批准 → 标记上架）不用重新找到那一行；已删除 / 不再符合筛选时如实说明并关闭
- 🧠 **动作后果写在弹窗里**：封禁会吊销令牌、移除等于踢下线、停用 ≠ 删除、有核销记录的券只能停用、
  「设为当前」连接不通过会保持原入口——不用靠记
- 🔐 **授权不再常驻版面**：管理员页的授权输入框改成页头一个「授予管理员」按钮 + 弹窗
  （角色说明跟着选中的角色走）；行里的角色下拉 / 停用 / 撤销 → 「管理」弹窗，
  改不动的原因（这是你自己 / 需要超级管理员）直接写在弹窗里
- 🧹 **修掉三处「写了但没生效」**：115 账号页头部类名写错（从未吃到全局样式）、
  设备页「已封禁」立牌缺 `is-danger` 规则、`.user-name` 在五个页面都在用却从未定义

## 📄 许可证

Copyright (c) 2024-2026 Aetrix. All rights reserved.
