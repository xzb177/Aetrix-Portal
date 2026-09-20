# 更新日志 (Changelog)

所有项目重要更改都将记录在此文件中。

## [2.6.3] - 2026-09-20

### 新增 (Added)
- **EM / EA 分离部署**：把「运营面板」与「Emby API 后端」拆成两个可独立部署的服务
  - **EA（新增 `emby_api/` + `serve_emby.py`）**：独立的 Emby 协议网关，客户端直连它。协议面同时提供 `/emby/*` 与**裸根路径**（`/System/Info`、`/Users/AuthenticateByName` …），因此 EA 独占一个地址；直连流 / HLS 转码 / 字幕投递 / 图片 / 进度上报全在 EA 侧，`/metrics` 与 `/api/health` 独立可观测
  - **EA 不能脱离 EM 单独运行**：启动时硬校验「共享 `SECRET_KEY`」与「共享库里存在 EM 建的表（`web_users` / `emby_libraries` / `emby_api_tokens`）」，不满足即拒绝启动并给出可执行提示；配了 `EM_PANEL_URL` 则额外探测 EM 可达性（仅告警——EM 重启不应禁断正在播放的会话）
  - **EM 仍是唯一事实来源**（用户 / 套餐 / 订阅 / 邀请 / 卡码 / 风控 / 媒体库），新增 `ENABLE_EMBY_GATEWAY` 开关：置 `false` 时 EM 不再提供协议面，并对误连的客户端返回明确的「请连 EA」404 指引（按 `emby_router` 实际声明的全部裸根路径注册，以后新增协议路由不会漏）
  - 分离部署下**前端无需改动**：网页播放器仍走同源 `/emby/*`，由 EM 的 Nginx 反代到 EA，不引入跳域
- `env.example` 新增分离部署配置段：`ENABLE_EMBY_GATEWAY` / `EMBY_API_PORT` / `EMBY_API_PUBLIC_URL` / `EM_PANEL_URL`
- 新增冒烟测试 `scripts/smoke_test_ea_split.py`：15 项断言覆盖配对闸门、EA 协议面（含裸根路径）、EA 健康上报、EM 默认模式行为不变、EM 分离模式的客户端指引与 SPA 不受影响

### 变更 (Changed)
- 文档中心按 EM / EA 重编排：新增 `docs/deploy-em.md`（面板：域名、前端构建、运营配置）与 `docs/deploy-ea.md`（网关：配对硬依赖、独立地址、客户端接入、限流与设备控制）；原 `deploy-server.md` / `deploy-web.md` 的内容并入这两篇（故不再单独存在）
- 版本号：后端 / 用户端 / 管理端 / EA 2.6.3（`backend/main.py`、`emby_api/main.py`、`user_frontend/package.json`、`admin_frontend/package.json` 与后台顶栏 `APP_VERSION` 四处同步）

### 修复 (Fixed)
- `backend/main.py` 的 FastAPI `version` 字段此前停留在 2.6.0、与 CHANGELOG 不一致，现同步

## [2.6.2] - 2026-09-20

### 文档 (Docs)
- **新增文档中心 `docs/`**（对标成熟媒体站项目的文档中心结构），共 4 篇（其中 `deploy-server.md` / `deploy-web.md` 已在 2.6.3 并入 EM / EA 两篇）：
  - [`docs/README.md`](docs/README.md)：文档中心索引——架构一图、按场景的阅读路径、为什么统一后端必须单进程
  - `docs/deploy-server.md`：服务端部署——环境要求、`env.example` 逐项说明、启动与 systemd 常驻、媒体库创建与扫描、Emby 客户端接入、转码与直连、监控
  - `docs/deploy-web.md`：门户与管理后台部署——两个前端的构建与固定产物路径、静态托管、同源约束、Nginx + HTTPS 最小可用配置、首次登录与验证清单
  - [`docs/operations.md`](docs/operations.md)：上线检查清单、安全基线（含风险最高的三项配置）、SQLite / PostgreSQL 备份与恢复、常见问题排错
- README「部署」章节改为指向文档中心并保留最短部署路径；同步修正原描述——自带的一键脚本（`deploy.sh` / `docker-compose.yml`）面向 v2.0 之前的拆分栈，统一后端的部署入口是 `serve.py` 单进程
- 文档中明确 Freebuff Hosting 只构建 React（Vite + React / Next.js / CRA），与本项目 Vue + Python 的形态不兼容，替代路径为服务器部署；并提示仓库内提交的 `nginx/ssl/` 证书不要直接用于生产
- 本版为**纯文档变更**，不涉及代码，应用版本号保持用户端 2.6.1

## [2.6.1] - 2026-09-20

### 变更 (Changed)
- **钱包核销入口二合一**：原先「充值积分」页顶部的「兑换码」与「购买订阅」页里的「会员卡码」是两个各自独立的输入框，用户拿到一串码得先自己判断该填哪一个，填错只会得到一句报错。现收敛为**一个**「卡码 · 兑换码」入口：提交后先走 `POST /api/user/membership/redeem/preview` 自动识别来源——会员卡码展示类型与天数、确认后再核销，兑换码直接走积分 / 订阅核销，邀请码则提示去注册页使用
- **订阅页的卡码表单下线**：只留一行虚线指引（点击把焦点交回顶部唯一入口），既消除了「两个入口该用哪个」的困惑，又保留可发现性
- 版本号：用户端 2.6.1

### 文档 (Docs)
- README 新增「部署」章节：说明 Freebuff Hosting 只构建 React（Vite + React / Next.js / CRA），与本项目 Vue + Python 的形态不兼容，并给出项目自带的 Docker Compose 部署路径

## [2.6.0] - 2026-09-20

### 新增 (Added)
- **卡码体系**（新增 `backend/codes.py`）：注册码 / 续期码 / 白名单码三类卡码，含**诱饵码**（蜜罐：在盗版渠道流通，使用即自动封禁账号并落安全日志）与**指名码**（仅限指定账号使用）；核销入口 `POST /api/user/membership/redeem`（含预检 `preview`，前端先确认类型与天数再核销），注册页凭码注册同样支持类型化授予
- **卡码管理台**：`POST /api/admin/registration-codes/generate`（类型/天数/次数/有效期/随机算法/诱饵/指名）、`GET /registration-codes/stats`（按类型统计 + 诱饵命中 + 累计授予天数）、`GET /registration-codes/list`（类型/状态/关键字筛选）、`PATCH`（停用/备注）与 `DELETE`（未使用的可回收，已核销的保留审计）
- **设备风控**（新增 `backend/devices.py`）：客户端 `AuthenticateByName` 登录即登记设备（名称/客户端/版本/IP/首末次出现），支持**每用户设备上限**（`device_limit_per_user`）与**超限自动踢最久未使用设备**（`device_limit_auto_evict`）；管理端 `GET /api/admin/devices`·`/devices/stats`、`PUT /devices/{id}`（封禁/解封，封禁同时吊销令牌）、`DELETE /devices/{id}`（踢下线）；用户端 `GET /api/user/emby/devices` 与 `DELETE /api/user/emby/devices/{id}` 自助清理
- **登录与安全日志**（新增 `backend/authlog.py` + `LoginLog` 表）：记录门户/客户端登录成功与失败、设备超限被拒、诱饵码触发封禁等事件；管理端 `GET /api/admin/login-logs`（用户名/IP/事件/结果筛选 + 24h 汇总）与 `POST /login-logs/purge`（按保留天数清理，`login_log_retention_days` 可配）
- **下载策略**：站点级 `allow_download` 开关，关闭后客户端下载与拉取一致被拦（管理员不受限）
- 管理端新增「卡码管理 / 设备管理 / 登录与安全日志」页面与侧栏分组；用户端新增钱包「会员卡码」核销面板与个人中心「我的设备」卡

### 修复 (Fixed)
- **`X-Emby-Authorization` 解析丢失客户端名**：首个字段带着认证方案前缀（`MediaBrowser Client="Infuse"`），原实现把 `MediaBrowser Client` 整体当作键名，导致 `Client` 永远取不到、设备审查里所有客户端都显示成默认名。现剥离方案前缀
- **`/Items/{id}/File` 可绕过下载开关**：该路径与 `/Download` 等价但只校验会员身份，站点关闭下载仍能直接拉文件；现由网关级中间件按路径兜底（覆盖 `/Download`、`/Items/{id}/File` 及未来新增的下载类路径）
- **白名单卡码天数语义不一致**：生成时写入 36500 天而展示/授予口径认 `-1` 为永久，导致前端显示「36500 天」；现统一为 `-1`
- **设备封禁未被强制执行**：管理端封禁设备后该设备仍可登录，现于设备登记阶段直接拒绝并提示

### 变更 (Changed)
- 版本号：后端 / 用户端 / 管理端 2.6.0

## [2.5.5] - 2026-09-20

### 新增 (Added)
- **Emby 网关客户端兼容补齐**（对照 Emby 4.7 官方 API 面，新增 40+ 端点）：`Search/Hints` 全局搜索、`Genres`/`Studios`/`Persons` 分类元数据、`Items/Counts` 与 `Items/Filters` 统计筛选、`FavoriteItems` POST/DELETE 规范收藏路由、`Items/{id}/Similar` 相似推荐、`Items/{id}/Ancestors` 祖先链路、`Users/Public`·`Users/Me`·`Users/{id}/Policy` 用户面、`Sessions/Logout`、`System/Endpoint`、`Library/MediaFolders`、`UserViews`、`Videos/ActiveEncodings` 释放转码、`Library/Refresh` 库刷新、`PlaybackInfo` 的 GET 与用户维度变体
- **字幕投递**（新增 `backend/emby_server/subtitles.py`）：`/Videos/{id}/{MediaSourceId}/Subtitles/{Index}/Stream.{Format}` 全路径族（含 `{StartPositionTicks}` 变体）；外挂字幕直出并做中文编码嗅探（UTF-8/GB18030/Big5），内封文本字幕用 ffmpeg 抽取为 WebVTT 并按「条目+轨道」缓存；图片类字幕（PGS/VobSub）明确返回 415
- 用户端网页播放器接入字幕轨：自动挂载服务端标记的默认文本字幕

### 修复 (Fixed)
- **网页端 HLS 播放实际不可用**：master playlist 派生的变体与切片地址只带 `session` 票据、不带 `api_key`，而 hls.js 不会给子请求附加认证头，导致变体与切片全部 401。现变体与切片地址自带 `api_key`
- **外挂字幕永远拉不到**：扫描器写入外挂字幕轨时未设置 `stream_index`（为 `None`），客户端据此拼出 `Subtitles/None`；现按已探测轨道序号顺延分配
- **`/Items/{id}/Images/Backdrop/0` 直接 404**：图片路由只注册了 `Primary/{index}`，其它类型带序号地址无路由；现改为通用 `{Type}/{Index}`
- **列表筛选参数被忽略**：`Filters=IsFavorite|IsPlayed|IsUnplayed|IsResumable`、`Ids` 批量查询、`SortBy=Random` 此前不生效（筛选后返回全量），现已支持
- **条目详情缺 `RunTimeTicks` / `Container`**：客户端无法展示时长与进度条，现已补齐
- **HLS 切片过早 404**：客户端请求切片往往早于 ffmpeg 写出，现短暂等待（播放列表 15s / 切片 12s）并在 ffmpeg 已退出时明确返回 503 而非空列表
- **转码进程与目录泄漏**：同一用户重复请求同一影片会反复 fork ffmpeg，且客户端异常断开不会回收；现复用进行中的会话并回收失效/超龄会话
- **同步能力如实上报**：`SupportsSynchronization` 由 `true` 改为 `false`（未实现 `/Sync/*`），避免客户端发起无法完成的离线同步
- **`/Users/Public` 不泄露账号**：未认证请求返回空列表（Jellyfin 默认隐私策略），强制客户端手动输入用户名

### 变更 (Changed)
- 版本号：后端 / 用户端 2.5.5

## [2.5.4] - 2026-09-20

### 变更 (Changed)
- **首页 Hero 主行动降级为文字级快捷入口**：原本的通栏「进入媒体库」大按钮与会员卡的「立即开通会员」在同一屏抢视觉，且媒体库已在顶栏与底部导航各有一个入口。现改为 13px 文字链接（`进入媒体库 ›` ｜ `继续观看《片名》›`），hover 才点亮主色，把首屏主 CTA 让给会员开通
- **会员卡内 CTA 去重**：未开通时卡内右上角的「开通 ›」文字链与下方通栏按钮重复，现仅在**已开通**时显示「续费 ›」，未开通时只保留唯一的「立即开通会员」
- 首页随之清理不再使用的 `.btn / .btn-primary / .btn-ghost` 样式与 `Play` 图标引用（无死代码残留）
- 版本号：后端 / 用户端 2.5.4

## [2.5.3] - 2026-09-20

### 修复 (Fixed)
- **首页与个人中心的 Emby 账号信息重复**：首页「站点与设备」整块（服务器地址 / 用户名 / 密码 / 复制 / 一键导入）与个人中心的「Emby 账号」卡几乎完全一致，信息重复且两个入口的行为略有不一致。现将凭据与一键导入**收归个人中心**（为个人中心补齐了原本只在首页有的「一键导入到客户端」按钮），首页只保留一行指引入口（标题 + 一句说明 + 跳转）
- 首页随之清理了不再需要的账号卡请求与复制逻辑（少一次请求、少一套重复状态）

### 变更 (Changed)
- 首页分组标题由「站点与设备」改为「站点与账号」，与内容（不再携带凭据）保持一致
- 版本号：后端 / 用户端 2.5.3

## [2.5.2] - 2026-09-20

### 新增 (Added)
- **付费墙（会员门禁）**
  - 新增 `backend/subscriptions.py` 作为订阅判定与门禁的单一事实来源：`has_active_subscription` / `subscription_required` / `can_play` / `ensure_playback_allowed`
  - 开关于 `SystemConfig`：`subscription_required`（布尔，默认开启）、`subscription_gate_message`（自定义拦截文案）
  - 门禁覆盖：`PlaybackInfo`（不发放播放地址）、`/emby/Videos/{id}/stream`（直连拉流）、HLS 转码会话创建（`master.m3u8` / `hls1`，先于 ffmpeg 检查）、`/emby/Items/{id}/Download`（下载）—— 网页端与 Infuse 等外部客户端同一门槛，无法绕过
  - 管理员（`is_staff`）始终放行；关闭开关后全员放行
- **用户端付费墙体验**
  - 播放页在 403 拦截时展示付费墙卡片（权益说明 + 「开通会员」CTA + 返回详情），而不是抛一个播放错误
  - 详情页在付费墙开启且非会员时提前展示会员提示条（可直达订阅页），不再等用户点了播放才知道
  - `/api/user/auth/me` 新增 `subscription_required` 字段，前端 store 暴露 `subscriptionRequired` / `needsSubscription`
- **钱包到账确认**：支付回跳（`?order=` 兼容 `?paid=1`）后自动轮询订单状态（3s × 10 次），到账即刷新积分与会员身份并提示，无需手动刷新
- **钱包订阅页新增当前会员状态行**（套餐 / 剩余天数 / 到期日，未开通时提示付费墙）

### 变更 (Changed)
- **首页布局优化**：Hero 改为双栏（左：问候与主行动；右：会员状态卡——已开通显示套餐与到期进度，未开通显示付费墙引导）；内容区新增「我的内容」「站点与设备」分组标签与节奏；移动端 Hero 自动堆叠，数据条与字距/间距重新校准
- **管理端系统设置新增「付费墙（会员门禁）」分组**：要求有效订阅开关 + 拦截提示文案（配置白名单同步扩充）
- 版本号：后端 / 用户端 2.5.2

## [2.5.1] - 2026-09-20

### 修复 (Fixed)
- **会员身份（VIP）恒不生效**：`GET /api/user/auth/me` 的 `is_vip` 此前硬编码为 `false`，订阅生效后个人中心 / 顶栏的 VIP 徽章永不显示。现由订阅派生：存在 `status=active` 且 `end_date > now` 的订阅即为会员，与后台订阅总览同一判定口径
- **过期订阅仍显示「生效中」**：`GET /api/user/subscriptions` 直接透传库内 `status`（无人随时间翻转），现按 `end_date` 归一生效状态，并新增 `is_current` 字段与 `days_left` 下限保护
- **工单回复无通知**：用户回复工单后管理员收不到任何提醒（代码中为 `TODO`），现落站内消息 + WebSocket 实时推送，与新建工单同一链路
- **工单回复接口契约错误**：回复端点复用「创建工单」请求模型，强制要求 `title`，前端只能传占位标题。现改为独立的 `TicketReplyRequest`，并补上空内容 / 超长（2000 字）校验
- **每日求片上限不可配置**：管理端经济设置白名单未包含 `media_seek_daily_limit`，该限制在用户端硬编码兜底。现纳入白名单并在系统设置页新增入口
- **用户端忽略功能开关**：钱包的兑换 / 充值 / 订阅购买与签到页的签到入口未读取后端开关，管理员关闭后用户仍可操作并收到报错。现关闭时禁用入口并给出提示（钱包新增调用 `GET /api/user/economy/exchange/config`）

### 变更 (Changed)
- 管理端「系统设置」把兑换与求片合并为「兑换码 · 求片」分组，新增「每日求片上限」字段
- 版本号：后端 / 用户端 2.5.1、管理端 2.4.1

## [2.5.0] - 2026-09-20

### 新增 (Added)
- **观看记录（用户端）**
  - `GET /api/user/emby/history`：按条目去重的观看历史（保留最近一次会话的设备/客户端/进度，合并用户媒体数据，支持类型筛选与分页）
  - 用户端新增 `/history` 页面：设备/进度/播放方式一览，可从个人中心与顶栏进入
- **全局搜索**
  - 用户端新增 `/search` 页：跨整个媒体库检索（电影 / 剧集 / 单集分组展示）、最近搜索本地留存、无结果时一键跳转求片
  - 媒体库首页新增搜索入口，顶栏新增搜索图标（移动端抽屉同样可达）
- **我的收藏**
  - 用户端新增 `/favorites` 页：类型筛选 + 一键取消收藏（乐观更新，失败回滚）。此前收藏只能在详情页切换，后端接口存在却没有列表页
- **我的播放会话**
  - `GET /api/user/emby/sessions`：查看自己正在播放的会话（设备 / 客户端 / 进度）
  - `DELETE /api/user/emby/sessions/{key}`：结束自己的播放（同时释放转码进程，越权结束他人会话返回 404）
- **求片能力**
  - `GET /api/user/media-seek/lookup`：提交前库存预检，已在库直接给播放入口且不占额度
  - `GET /api/user/media-seek`：列表返回今日额度（已用 / 上限 / 剩余）
  - `DELETE /api/user/media-seek/{id}`：撤回尚未被处理的求片

### 变更 (Changed)
- 求片提交增加双层校验：同名处理中去重（409）与每日额度上限（`media_seek_daily_limit` 可配，默认 5 条，超限 429）
- 求片中心页重做：库存检查卡片、额度进度、状态筛选、撤回操作，并支持 `/request?name=xxx` 预填片名
- 消息中心重做：按消息类型深链至求片 / 工单 / 积分 / 订阅页面
- 首页重写为「内容 + 状态」仪表盘：账号速览数据条、继续观看、最近入库、站点动态、连接播放器；功能入口归还导航
- 顶栏按业务域分组并新增搜索 / 收藏入口与积分余额徽章；移动端新增底部导航坞（中心凸起签到项）
- 媒体库首页、媒体卡片、媒体行等组件由残留旧绿色硬编码统一切换为 Aurora 设计令牌

### 修复 (Fixed)
- 实现 `notify_staff_users()`：用户提交求片 / 工单后写入站内消息并实时推送给全部启用中的管理员（此前仅 TODO，后台必须手动刷新才能发现新请求）
- 删除死接口 `/api/user/emby-servers`、`/api/user/playback-sessions`（前端已无引用）

## [2.4.0] - 2026-09-20

### 新增 (Added)
- **管理后台缺失接口补齐**
  - `GET /api/admin/announcements`：公告列表（含停用项、`active_only` 过滤）——此前公告页只能发布/编辑，无法列出
  - `GET /api/admin/tickets/{id}/messages`：工单会话内容（含管理员署名）——此前工单只能盲回复
  - `GET /api/admin/users/{id}`：用户 360° 画像（资料 / 订阅历史 / 积分台账 / 订单 / 邀请 / 签到 / 观看）
  - `GET /api/admin/stats/trend`：趋势统计（按日补零：新增用户 / 播放 / 营收 / 签到）
  - `GET /api/admin/economy/subscriptions`：订阅总览（生效中 / 7 天内到期 / 已过期 + 用户名搜索）
- **管理后台页面**
  - 订阅管理页（总览四格 + 延长 / 续订）
  - 系统设置页（注册策略 + 签到 / 兑换 / 支付网关 / 邀请返利分组可视化编辑）
  - 用户管理新增详情抽屉（订阅 / 积分 / 订单 / 邀请四个标签页）与正规操作对话框
  - 数据概览新增待办条、交易概览、SVG 趋势图（7/14/30 天）

### 变更 (Changed)
- 侧边栏按业务域分组（概览 / 用户与订阅 / 运营 / 内容 / 支持 / 系统），顶栏改为面包屑 + 管理员菜单（接上修改密码）
- 管理端主题与用户端 Aurora（电光青 #22d3ee）对齐，Element Plus 组件与表格/抽屉/对话框全部随主题
- 「邀请与积分」页的原始键值设置对话框下线，配置统一收归「系统设置」

### 修复 (Fixed)
- 401 拦截器与页面 catch 重复弹错（同一错误弹两次提示）
- 用户/积分调整由手填数据库 ID 改为用户名远程搜索
- 工单状态 / 优先级、公告停用启用可在界面上直接操作（此前接口存在但前端未接）
- 删除未被引用的死样式文件，补齐缺失的全局重置与 body 背景

## [2025-01-10]

### 新增 (Added)
- **一键部署脚本** (`deploy.sh`)
  - 支持 `--build` 强制重新构建镜像
  - 支持 `--no-cache` 构建时不使用缓存
  - 支持 `--backend` 仅部署后端服务
  - 支持 `--frontend` 仅部署前端服务
  - 支持 `--bot` 仅部署 Telegram Bot
  - 支持 `--rollback` 回滚到上一版本
  - 支持 `--status` 显示服务状态
  - 支持 `--logs` 显示服务日志
  - 支持 `--update` 更新代码并部署
  - 自动环境检查（Docker、Docker Compose、.env 文件）
  - 健康检查功能（本地 + 外部）
  - 旧镜像自动清理

### 功能特性
- 彩色日志输出（INFO/SUCCESS/WARNING/ERROR）
- 服务健康状态检测
- Git 代码自动更新
- 容器状态监控
- 完整的帮助文档

### 使用示例
```bash
./deploy.sh              # 部署所有服务
./deploy.sh --build      # 强制重新构建并部署
./deploy.sh --backend    # 仅部署后端服务
./deploy.sh --update     # 更新代码并部署
./deploy.sh --rollback   # 回滚到上一版本
```

---

## 之前版本

### [初始版本]
- RoyalBot Emby Portal 基础部署配置
- Docker Compose 配置
- Nginx 反向代理配置
- 基础环境变量模板
