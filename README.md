# Aetrix Portal

**把「自己的影视服务器 + 会员网站」一次装好 —— 不用再单独装 Emby。**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-latest-blue.svg)]()
[![CI](https://github.com/xzb177/Aetrix-Portal/actions/workflows/ci.yml/badge.svg)](https://github.com/xzb177/Aetrix-Portal/actions/workflows/ci.yml)

---

## 这是什么

你想开一个自己的视频网站，需要这些东西：

| 你想要的 | 相当于 |
| --- | --- |
| 片库（电影、剧集放在硬盘里） | 你的网盘 / NAS |
| 片库详情页（海报、简介、分类） | 视频网站的详情页 |
| 让 App 能看到片库并播放 | 视频网站的播放器接口 |
| 用户注册、会员付费 | 视频网站的会员系统 |
| 管理员管这一切 | 视频网站的后台 |

**Aetrix 把这些全做了，而且对外伪装成一个 Emby 服务器。**

### 为什么说「伪装成 Emby」

Infuse、Forward、SenPlayer 这些播放器 App 只认 Emby 的接口。Aetrix 内部自己实现了这套接口，
所以**你不需要装官方 Emby**，直接让这些 App 连上 Aetrix 就能播片。

好处是：界面、会员、支付全归你管，不受官方 Emby 的限制。

### 适合谁

- ✅ 想开**自己的影视站**的人（会员、积分、支付、卡密都内置了）
- ✅ 手里有**大硬盘 / NAS**，想自建片库的人
- ✅ 已经有 Emby、但想要**自己的用户端和运营后台**的人
- ❌ 只想看几个本地视频的人 → 用现成的播放器更省事

---

## 30 秒跑起来

需要：一台 Linux 服务器（2 核 4G 起）+ Docker。

```bash
# 1. 拉代码
git clone https://github.com/xzb177/Aetrix-Portal.git
cd Aetrix-Portal

# 2. 生成一个密钥（必须填，否则拒绝启动）
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# 3. 准备配置，把上面那串密钥填进 SECRET_KEY
cp env.example .env
nano .env

# 4. 启动
bash scripts/deploy.sh
```

跑完浏览器打开 `http://你的IP:8000/admin/` 就能进后台。

**卡住了？** 看 [新手指南](docs/新手指南.md)，里面有每一步的详细解释和常见问题。

---

## 它能做什么

<details>
<summary><b>展开看完整功能列表</b></summary>

### 媒体库

- 递归扫描目录，自动认出电影 / 剧集 / 季 / 集（`S01E02`、`1x02`、`第3集` 都能认）
- ffprobe 提取轨道信息（编码、分辨率、音轨、字幕）
- 可选 TMDB 中文刮削（海报、简介、评分、类型）
- 外挂字幕自动发现
- 增量扫描：目录没变就跳过，不重复干活

### 播放

- HTTP Range 直连流 —— 原盘直出，不转码，零损耗
- HLS 实时转码 —— 浏览器和受限设备用，可限码率和分辨率
- 播放进度自动记录，跨设备续看
- 字幕投递

### 用户端（网页）

- 浏览 / 搜索 / 详情 / 在线播放
- 每日签到（连签加成）
- 收藏、播放历史
- 会员订阅购买（支付回调自动开通）
- 积分充值、兑换码核销、优惠券抵扣
- 邀请返利
- 媒体求片 + 投票

### 管理后台

- 媒体库增删改查、扫描
- 条目管理
- 在线会话监控、强制下线
- 转码管理
- 存储挂载（本地硬盘 / 115 / rclone）
- 经济系统配置（价格、套餐、卡密、优惠券）
- 签到 / 兑换码 / 邀请 统计
- 多服务器、多节点出流
- 数据库自动备份

### 客户端兼容

Infuse、Fileball、Forward+、Hills、SenPlayer、官方 Emby App —— 都能直接连。

</details>

---

## 两个角色：EM 和 EA

Aetrix 内部拆成两半，但**默认装在一起，你不用管**：

| 代号 | 干什么 | 谁在用 |
| --- | --- | --- |
| **Aetrix EM** | 面板：网页、扫描、会员系统 | 浏览器里的用户和管理员 |
| **Aetrix EA** | 出流：传视频字节、转码、字幕 | 播放器 App（Infuse 等） |

两半共用同一个数据库和 `SECRET_KEY`。

**小机器**：就让它俩待在一起（默认配置）。
**机器好、想专门出流**：可以把 EA 拆到另一台机器上，EM 只管页面和业务。

> 名字来源：`Aetrix` = Aether（以太，串流）+ Matrix（矩阵，多台服务器组网）。
> `Portal` 是它的角色 —— 面板即门户，字节由 EA 送出。

### 架构长什么样

```
Emby 客户端 ──HTTP──▶ EA（出流）
                        │
                        ▼
浏览器 ──▶ EM（面板）──┴──▶ PostgreSQL ──▶ 你的硬盘
             │
             └──▶ Redis（缓存 / 限流）
```

单进程模式下 EM 也会提供出流能力，浏览器一个端口就够了。

更多细节见 [部署文档](docs/deploy-docker.md)。

---

## 常用命令

```bash
bash scripts/deploy.sh     # 首次安装
bash scripts/update.sh     # 更新到最新版（自动备份数据库）
bash scripts/deploy.sh --dry-run   # 只看要执行什么，不真跑
```

```bash
curl http://127.0.0.1:8000/api/health   # 看服务状态
docker logs -f aetrix-api               # 看日志
docker compose restart                  # 重启
```

---

## 文档

| 文档 | 什么时候看 |
| --- | --- |
| [新手指南](docs/新手指南.md) | **第一次用**，从零开始 |
| [Docker 部署](docs/deploy-docker.md) | 配置 HTTPS、反代、多机拆分 |
| [能力清单](docs/capabilities.md) | 有哪些功能、边界在哪 |
| [运维手册](docs/operations.md) | 日常维护、排查问题 |
| [性能调优](docs/performance.md) | 扫描慢、内存高、数据库大 |

---

## 技术栈

- **后端**：Python 3.12 · FastAPI · SQLAlchemy
- **数据库**：PostgreSQL（默认）或 SQLite
- **缓存**：Redis 7
- **前端**：Vue 3 · TypeScript · Element Plus
- **转码**：ffmpeg
- **存储挂载**：本地硬盘 / 115 / rclone

---

## 常见问题

<details>
<summary><b>要不要装官方 Emby？</b></summary>

不用。Aetrix 自己实现了 Emby 协议。
</details>

<details>
<summary><b>会推片源吗？</b></summary>

不会。这是自建系统，你把片源放在自己的硬盘或挂载上。
</details>

<details>
<summary><b>数据存在哪？</b></summary>

Docker volume 里。**但不会自动备份到你的电脑**，重要数据请定期拷出来。
详见 [新手指南 · 常见问题](docs/新手指南.md)。
</details>

<details>
<summary><b>能多开几个站点吗？</b></summary>

能。「多服运营」功能支持一套部署跑多个独立站点，各自有独立的会员、套餐、媒体库。
</details>

<details>
<summary><b>我的数据能用官方工具备份吗？</b></summary>

可以。默认 PostgreSQL，用 `pg_dump` 即可。
</details>

---

## 许可证

[MIT](LICENSE)

---

## 更新日志

### v2.42.0 — 默认数据库切换到 PostgreSQL

SQLite 只在单进程/单机场景够用：单写锁模型下扫描、播放上报、订单并发容易撞
`database is locked`，备份也只能做文件级快照。Docker Compose 部署会自动配好 PG，
不用手工连线。老部署若要继续用 SQLite，显式设置 `DATABASE_TYPE=sqlite` 即可。

同时修复了一组迁移链路问题（跨进程建表竞态、孤儿外键、自引用外键导入顺序），
详见 [PR #221](https://github.com/xzb177/Aetrix-Portal/pull/221)。

部署形态也跟着调了：**前后端分离**（后端只跑 API，两个前端由 nginx 容器单独 serve，
改前端不用重建后端镜像），同时把 api / worker / ea **合并回一个容器**，Compose 服务数
8 → 6。功能上借鉴 twilight-kotomi 补了四项能力 —— 配置自愈、诱饵码、首次运行向导、
配置热重载；并修回了管理端深色主题（Element Plus 按需引入后自带样式盖掉深色变量，
表现为输入框 / 下拉 / 弹窗发白、主色变默认蓝）。

公测前又做了一轮加固：配置自愈不再改写数据库连接与对外地址这类「写错就连不上」的
配置项（改为只告警不代填）、EA 的内部端口收回本机地址（不再绕过 nginx 直接对公网开放）、
备份链路真正可用（内置定时备份只管 SQLite，PostgreSQL 需要 pg_dump 定时任务）。
逐条说明见 [CHANGELOG.md](CHANGELOG.md) 的 2.42.0 一节。

### v2.41.0 — 后端拆分

后台任务进程（扫描、探测、补全、定时、追新）从 API 进程里拆出，
不再和网页服务抢资源。两者用 Redis 锁保证只跑一个。

### v2.40.0 — 分层扫描

扫描分三层：L1 前台只做文件发现与指纹，扫完立刻能在媒体库里看见条目；side 图片 / NFO /
TMDB 刮削 / 探测交给后台补全 worker 慢慢做完。文件指纹命中即整文件秒跳 ——
「文件没变」与「元数据没补全」不再互相牵连，这正是此前配了 TMDB 的剧集库每轮全量重做的根因。


<details>
<summary><b>展开：技术细节与开发指南（架构详解 / 完整功能列表 / 目录结构 / 配置项 / 开发）</b></summary>

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
- 📚 **媒体库** - 卡片支持直接上传/更换封面，快速识别媒体库；卡片保留**服务（归属节点）/ 来源（几条路径 + 几个挂载）/ 扫描状态 / 条目数**，低频配置收进设置抽屉；库/路径/扫描/条目管理、按来源拆分的扫描明细
- 🗂️ **存储来源** - 把内容接进媒体库，只保留三种：**本地硬盘**（任意绝对路径，如 `/media/movies`）、**115 网盘**（`115:/` 开头）、**rclone**（`rclone:` 开头，形如 `rclone:gdrive/Movies`）。类型由路径前缀决定，不用另选；远程来源代理播放，凭据不下发；每条都标明**被哪些媒体库使用**。旁边的**rclone.conf** 页粘贴你自己的 `rclone config` 文本——面板只落盘并给命令加 `--config`，**不代管任何凭据**，也不会回显原文
- 📺 **会话监控** - 在线用户、强制下线
- 🎫 **工单处理** - 工单会话、状态/优先级流转、回复与关闭
- 📣 **公告管理** - 发布/编辑/置顶/停用，联动全站推送
- 📝 **日志审计** - 全量管理操作流水，按操作类型快捷筛选 + 关键字检索

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 数据库：PostgreSQL（默认）或 SQLite（`DATABASE_TYPE=sqlite`，单机开发够用）
- ffmpeg（可选，转码需要；直连播放不需要）

### 启动统一后端（含自建 Emby 服务器）

```bash
pip install -r backend/requirements.txt
cp env.example .env   # 按需修改 EMBY_PUBLIC_URL 等
python serve.py       # 默认 0.0.0.0:8000
```

> **跑不起来先看这里：数据库。** v2.42.0 起默认连 PostgreSQL，而 `env.example` 里的
> `DATABASE_URL` 指向的是 Compose 内部的服务名 `postgres`——在没装 PG 的机器上
> 直接 `python serve.py` 会以 `psycopg2.OperationalError: connection to server at
> "localhost", port 5432 failed` 退出。两种解法：把 `.env` 换成 SQLite
> （`DATABASE_TYPE=sqlite` + `DATABASE_URL=sqlite:///./aetrix_unified.db`，
> `env.example` 末尾有这两行的注释版本），或让 `docker compose up -d` 把 PostgreSQL 一并拉起来。

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

**先准备好数据库。** `DATABASE_TYPE` 的代码默认值是 `postgresql`，所以「装完依赖直接
`python serve.py`」在没有 PG 的机器上会以
`psycopg2.OperationalError: connection to server at "localhost", port 5432 failed` 退出
——这不是安装坏了，是缺库。单机开发用 SQLite 最省事（`env.example` 里那组
`@postgres:5432` 是 Compose 的服务名，裸机照抄连不上）：

```bash
pip install -r backend/requirements.txt

export DATABASE_TYPE=sqlite                          # 或用 .env 里的 DATABASE_TYPE / DATABASE_URL
export DATABASE_URL=sqlite:///./aetrix_unified.db

python serve.py          # EM 面板 :8000
python serve_emby.py     # EA 协议网关 :8001（分离部署时才需要）
```

要用 PostgreSQL，就让 `DATABASE_URL` 指向一台真的能连上的 PG（自建 PG 时改掉
`@postgres:5432` 这个主机名）；`docker compose up -d` 会把 PG 一起拉起来。

### 持续集成（CI）

[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) 在 push 到 `main`、开 PR 与手动触发时跑三组检查，口径与本地一致：

| 任务 | 内容 |
| --- | --- |
| 前端 · `user_frontend` / `admin_frontend` | `npm ci`（锁文件与 `package.json` 不同步即失败）→ `npm run type-check`（vue-tsc）→ `npm run build` |
| 后端 · 冒烟测试 | `scripts/smoke_test_auth.py`、`scripts/smoke_test_admin_v240.py`、`scripts/smoke_test_admin_account.py`（TestClient 进程内，不需要构建产物） |
| 后端 · 部署自检 | 还原前一个任务产出的 `dist` 后跑 `scripts/deploy_check.py`：**真起 uvicorn、真发 HTTP**，覆盖单进程与 EM/EA 分离两套形态 |

这四个检查在 `main` 上是**必需状态检查**（branch protection）：PR 必须等到它们全部通过才能合并，
挂着失败或还在跑的检查时 GitHub 会拒绝合并（`BLOCKED`，提示 `the base branch policy prohibits the merge`）；
全部通过后转为 `CLEAN` 才可合入。`strict`（要求分支先与 `main` 同步）未开启。

**默认交付走 PR**（见 [`AGENTS.md`](./AGENTS.md)）：从最新 `main` 切分支 → 本地跑上述检查 → 推分支并开 PR，
等 4 项必需检查全部通过后再合并；只有用户明确要求且确认不会绕过必需检查时才直接推送 `main`。
`enforce_admins` 当前未开启（仓库管理员仍可直推），它只是**兜底**，默认流程不依赖它。

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

### v2.33.0 (2026-09-24) — 管理端其余常驻说明统一可折叠
- 📂 **服务器、服管理、客户端策略、系统设置页的常驻说明也收起来了**：分别说明服务类型职责、服级数据隔离、
  客户端策略与站点运营设置的边界、外部服务凭据来源；每块默认收起，点标题才展开，展开状态记在浏览器本地
- 🧭 **需要马上处理的状态不会被藏起来**：权限不足、连接失败、待处理告警、弹窗提示与字段旁短提示仍常驻；
  收起的只是帮助文字，不是当前状态
- ✅ **版本与验证同步更新**：管理端类型检查、生产构建、设计令牌与路由契约检查均通过；构建产物包含独立的
  `NoticePanel` chunk，可打开上述页面手工点击标题演示展开 / 收起与刷新后的状态记忆

### v2.32.0 (2026-09-24) — 用户端地址不再拿写死的 localhost 当配置，后台说明可折叠
- 🚨 **刚装好的测试服务器不再第一眼报红**：入口地址没人配过时，解析曾回退到写死的
  `http://localhost:8000`，面板把它当成「地址解析成 localhost」的证据——于是媒体库页第一眼
  就是一条红提示；后果还不止是红：用户端账号卡会真的把 localhost 下发下去，用户照抄进播放器
  就连不上。现在什么都没配时按**管理员当前访问用的地址**解析（面板与接口同源），
  账号卡下发的就是用户真能连上的那个地址；配过的一律优先，只有真把 localhost 填进配置才报红
- 🧭 **面板会说清地址是哪来的**：服地址 / 服务入口 / 环境变量 / 按当前访问地址推断 / 没配，
  不再把「占位值」当配置报出来
- 🕳️ **环回地址识别补一处漏洞**：IPv6 字面量带方括号（`http://[::1]:8000`）时会漏判，
  于是这种地址永远不提示「只有本机能连」
- 📂 **整块说明文字收成一行**：管理员与权限页（角色说明、三条护栏）、存储来源页（支持的
  来源类型）默认收起，点开才展开；展开状态记在浏览器本地。以前这些常驻版面，手机上一次
  滑动都到不了真正要操作的清单


</details>

## 📄 许可证

Copyright (c) 2024-2026 Aetrix. All rights reserved.
