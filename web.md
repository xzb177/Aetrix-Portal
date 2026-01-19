# RoyalBot-Portal 开发进度记录

## 项目概述

本文档用于记录 RoyalBot-Portal 项目的开发进度和关键操作。

## 环境信息

- **工作目录**: `/root/RoyalBot-Portal`
- **平台**: Linux
- **日期**: 2026-01-12

## 操作记录

### 2026-01-12 初始化

- 创建进度记录文档 `web.md`
- 准备开始项目开发任务

### 2026-01-12 Emby 一键导入问题分析

**问题描述：** 用户首页一键导入 Emby 服务器后，客户端不会自动添加

**问题根因：** URL Scheme 格式不正确

| 播放器 | 当前格式（错误） | 正确格式 |
|--------|-----------------|----------|
| Forward | `forward://emby/add?url=xxx&apikey=xxx&user=xxx&name=xxx` | `forward://import?type=emby&scheme=SCHEME&host=HOST&port=PORT&username=USERNAME&password=PASSWORD` |
| EplayerX | 未验证 | 未找到官方文档 |
| SenPlayer | `SenPlayer://add?host=xxx&port=xxx&username=xxx&password=xxx&name=xxx&type=emby` | 未找到官方文档 |

**参考来源：**
- [Forward - 新视界CH Telegram](https://t.me/s/forwardplayer/273)
- [Forward 文档](https://forward-2.gitbook.io/forward)

**待修复文件：** `/root/RoyalBot-Portal/user_frontend/src/components/PlayerSelectorSheet.vue:119-132`

### 修复内容

**1. Forward 播放器 URL Scheme 修复**
- 原格式（错误）：`forward://emby/add?url=xxx&apikey=xxx&user=xxx&name=xxx`
- 新格式（正确）：`forward://import?type=emby&scheme=SCHEME&host=HOST&port=PORT&username=USERNAME&password=PASSWORD`

**2. 移除未验证的播放器**
- 移除 EplayerX（未找到官方 URL Scheme 文档）
- 移除 SenPlayer（未找到官方 URL Scheme 文档）

**3. 保留的播放器**
- Forward - 智能聚合，多服管理
- Emby - 官方客户端

**修复代码位置：** `/root/RoyalBot-Portal/user_frontend/src/components/PlayerSelectorSheet.vue`

### 2026-01-12 添加 Hills 播放器支持

**新增功能：** 添加 Hills 播放器 URL Scheme 支持

**URL Scheme 格式：**
```
hills://import?type=emby&scheme=SCHEME&host=HOST&port=PORT&username=USERNAME&password=PASSWORD
```

**TG 内跳转格式：**
```
https://gocy.pages.dev/#hills://import?type=emby&scheme=SCHEME&host=HOST&port=PORT&username=USERNAME&password=PASSWORD
```

**播放器列表更新：**
- Forward - 智能聚合，多服管理
- Hills - 全能播放器（新增）

**移除：**
- Emby 官方客户端选项

### 2026-01-12 首页 Emby 账号卡片优化

**视觉优化：**
- 账号卡片背景添加深色半透明层
- 字段值添加边框和圆角
- 复制按钮添加边框和悬停效果
- 一键复制按钮改为绿色渐变样式
- 服务器地址字段使用绿色高亮
- 状态指示点添加发光效果

**新增字段：**
- 协议：显示 HTTP/HTTPS（可复制）
- 端口：自动解析 URL 中的端口，默认 443/80（可复制）

**字段顺序：**
1. 服务器地址
2. 协议
3. 端口
4. 用户名
5. 密码
6. 一键复制全部信息

**修改文件：** `/root/RoyalBot-Portal/user_frontend/src/views/HomeView.vue`

### 2026-01-12 部署更新

**已部署：** 新代码已成功部署到容器 `royalbot_user_frontend`

**更新脚本：** 版本更新至 v1.4.0

**仓库推送：** 已推送到 `https://github.com/xzb177/Aetrix-emby-deplo.git`

### 2026-01-12 添加 SenPlayer 播放器支持

**新增播放器：** SenPlayer

**URL Scheme 格式：**
```
senplayer://importserver?type=emby&name=xxx&note=xxx&address=xxx&username=xxx&password=xxx
```

**参数说明：**
| 参数 | 说明 | 示例 |
|------|------|------|
| type | 服务器类型（必填） | emby / jellyfin / webdav / smb / ftp / feiniu |
| name | 服务器名称（可选） | Emby 服务器 |
| note | 服务器备注（可选） | 主线路 |
| address | 服务器地址（必填） | https://example.com:443 |
| username | 登录名称（可选） | 用户名 |
| password | 登录密码（可选） | 密码 |

**播放器列表更新：**
- Forward - 智能聚合，多服管理
- Hills - 全能播放器
- **SenPlayer - 网盘直连，多线路（新增）**

**更新脚本：** 版本更新至 v1.5.0

**修改文件：** `/root/RoyalBot-Portal/user_frontend/src/components/PlayerSelectorSheet.vue`

### 2026-01-12 Emby 一键导入修复

**问题描述：** 用户一键导入 Emby 服务器后，客户端不会自动添加

**根本原因：** `user_backend/api/emby.py` 中的 `create_emby_account` 函数只在数据库中创建账号记录，**没有在 Emby 服务器上实际创建用户**

**修复内容：**
1. 添加 `EmbyClient` 调用，在 Emby 服务器上创建真实用户
2. 保存 `emby_user_id` 到数据库（用于后续管理）
3. 设置用户策略（权限）：会话数限制、码率限制、下载权限
4. 更新服务器用户计数
5. 检查服务器最大用户数限制

**修复代码位置：** `/root/RoyalBot-Portal/user_backend/api/emby.py:68-107`

**修复前逻辑：**
```
1. 选择服务器
2. 生成随机用户名密码
3. 在数据库创建记录 ❌ 没有在 Emby 服务器创建用户
4. 返回账号信息
```

**修复后逻辑：**
```
1. 选择服务器（检查用户数限制）
2. 生成随机用户名密码
3. 调用 Emby API 创建用户 ✅
4. 设置用户策略（权限）✅
5. 在数据库创建记录（保存 emby_user_id）
6. 更新服务器用户计数 ✅
7. 返回账号信息
```

### 2026-01-12 添加 Lenna 播放器支持（实验性）

**新增播放器：** Lenna - HDR播放器，多服务器

**注意：** Lenna 官方未公开服务器导入的 URL Scheme 文档，以下格式基于 x-callback-url 标准推断，可能需要实际验证。

**推断的 URL Scheme 格式：**
```
lenna://x-callback-url/addServer?url=SERVER_URL&username=USERNAME&password=PASSWORD&x-success=royalbot://callback/success&x-error=royalbot://callback/error
```

**参数说明：**
| 参数 | 说明 | 示例 |
|------|------|------|
| url | 完整服务器地址 | https://example.com |
| username | 登录用户名 | rb12345678 |
| password | 登录密码 | 随机密码 |
| x-success | 成功回调 | royalbot://callback/success |
| x-error | 失败回调 | royalbot://callback/error |

**播放器列表更新：**
- Forward - 智能聚合，多服管理
- Hills - 全能播放器
- SenPlayer - 网盘直连，多线路
- **Lenna - HDR播放器，多服务器（实验性）**

**UI 标记：** Lenna 播放器显示橙色「实验性」标签

**修改文件：** `/root/RoyalBot-Portal/user_frontend/src/components/PlayerSelectorSheet.vue`

### 2026-01-12 后端服务重启

**已部署：** 修复后的代码已重启服务 `royalbot_user_backend`

**服务状态：** 健康运行

### 2026-01-12 前端 UI 修复和优化

**问题列表：**
1. Emby 卡片信息中的协议字段（多余）
2. 后台管理公告发布按钮点击无反应
3. 站内信息文字错位
4. 用户首页购买套餐成功没有视觉反馈

**修复内容：**

#### 1. 去除 Emby 卡片协议字段
- 删除了用户首页 Emby 账号卡片中的"协议"字段
- 保留服务器地址、端口、用户名、密码等核心信息

**修改文件：** `/root/RoyalBot-Portal/user_frontend/src/views/HomeView.vue`

#### 2. 修复后台管理公告发布按钮
- 添加了新建/编辑公告对话框组件
- 实现了表单校验和保存逻辑
- 添加了对话框过渡动画和移动端适配

**修改文件：** `/root/RoyalBot-Portal/admin_frontend/src/views/Announcements.vue`

**新增功能：**
- `openCreateDialog()` - 打开新建公告对话框
- `openEditDialog()` - 打开编辑公告对话框
- `saveAnnouncement()` - 保存公告（新建或编辑）
- 对话框 UI 组件（标题、表单、底部按钮）

#### 3. 修复站内信息文字错位
- 优化消息卡片标题行的 flex 布局
- 添加 `flex-wrap: wrap` 和 `flex-shrink: 0` 防止文字溢出
- 修复时间标签的 `margin-left: auto` 对齐问题

**修改文件：** `/root/RoyalBot-Portal/user_frontend/src/views/MessagesView.vue`

#### 4. 添加购买套餐成功视觉反馈
- 为 `handlePurchase()` 函数添加 `purchasing` 状态管理
- 点击购买按钮时显示加载动画（Loader2 图标旋转）
- 300ms 延迟后打开支付弹窗

**修改文件：** `/root/RoyalBot-Portal/user_frontend/src/views/SubscriptionView.vue`

#### 5. 修复后台管理双重导航栏
**问题描述：** 后台管理某些页面同时显示两个导航栏（Layout header + 页面内部 top-bar）

**修复内容：** 在桌面端（≥1024px）隐藏页面内部的顶部导航栏，统一使用 Layout 的 header

**修复文件：**
- `/root/RoyalBot-Portal/admin_frontend/src/components/system-settings/PageHeader.vue`
- `/root/RoyalBot-Portal/admin_frontend/src/views/ExchangeCodes.vue`
- `/root/RoyalBot-Portal/admin_frontend/src/views/Announcements.vue`

**修复方法：** 添加媒体查询 `@media (min-width: 1024px) { display: none; }`

**影响页面：**
- 系统配置
- 兑换码管理
- 公告管理

### 2026-01-12 部署更新 v1.6.0

**部署内容：**
- 用户前端容器重新构建并部署
- 部署脚本版本更新至 v1.6.0
- 代码已推送到 GitHub 仓库

**Git 提交：** `427bffc`

**容器状态：**
- royalbot_user_frontend: Up (healthy)
- royalbot_admin_frontend: Up (healthy)
- royalbot_user_backend: Up (healthy)
- royalbot_nginx: Up (healthy)
- royalbot_admin_backend: Up (healthy)

### 2026-01-12 修复购买视觉反馈未生效问题

**问题描述：** 用户首页购买套餐成功视觉反馈修复后未生效

**问题根因：**
- 源代码修改正确（`SubscriptionView.vue`）
- 但之前构建时工作目录在 `admin_frontend`，导致构建的是管理后台而非用户前端
- `user_frontend` 容器运行的是旧版本代码
- 加载延迟时间太短（300ms），用户难以察觉

**修复操作：**
1. 修改 `SubscriptionView.vue`：
   - 增加 `nextTick` 导入
   - 延迟时间从 300ms 增加到 800ms
   - 使用 `nextTick` 确保弹窗渲染后再清除加载状态
2. 恢复 `admin_frontend/Dockerfile` 和 `nginx.conf`（之前被删除）
3. 更新 `docker-compose.yml` 添加 `admin_frontend` 服务定义
4. 重新构建并部署两个前端容器

**容器状态：**
- royalbot_user_frontend: Up (running, latest image)
- royalbot_admin_frontend: Up (running, latest image)
- 构建时间: 2026-01-12 10:20:00 UTC

**预期效果：**
- 点击购买按钮时显示加载动画（Loader2 图标旋转）
- 800ms 延迟后打开支付弹窗
- 用户可以清楚看到视觉反馈

### 2026-01-12 修复后台管理页面空白问题

**问题描述：** 后台管理页面访问后一片空白

**问题根因：**
- `admin_frontend/Dockerfile` 和 `nginx.conf` 在之前的提交中被删除
- `docker-compose.yml` 中没有定义 `admin_frontend` 服务
- 容器使用的是旧的镜像，无法正确构建和部署

**修复内容：**
1. 从 git 历史恢复 `admin_frontend/Dockerfile`
2. 创建 `admin_frontend/nginx.conf`
3. 更新 `docker-compose.yml` 添加 `admin_frontend` 服务定义
4. 重新构建并部署容器

**修改文件：**
- `/root/RoyalBot-Portal/admin_frontend/Dockerfile` (恢复)
- `/root/RoyalBot-Portal/admin_frontend/nginx.conf` (创建)
- `/root/RoyalBot-Portal/docker-compose.yml` (添加 admin_frontend 服务)

**容器状态：**
- royalbot_admin_frontend: Up (healthy)

---

### 2026-01-12 修复 Admin 后台页面空白问题（再次）

**问题描述：** Admin 后台管理页面打开后一片空白

**问题根因：**
- `admin_frontend/src/styles/index.css:1-3` 使用了 `@tailwind` 指令
- 但 `package.json` 中没有安装 Tailwind CSS 依赖
- 缺少 `tailwind.config.js` 和 `postcss.config.js` 配置文件

**修复内容：**
1. 在 `package.json` 的 `devDependencies` 中添加：
   - `tailwindcss: ^3.4.0`
   - `postcss: ^8.4.0`
   - `autoprefixer: ^10.4.0`
2. 创建 `admin_frontend/tailwind.config.js`
3. 创建 `admin_frontend/postcss.config.js`
4. 运行 `npm install` 更新 `package-lock.json`
5. 重新构建并部署容器

**修改文件：**
- `/root/RoyalBot-Portal/admin_frontend/package.json` - 添加 Tailwind CSS 依赖
- `/root/RoyalBot-Portal/admin_frontend/tailwind.config.js` - 新建
- `/root/RoyalBot-Portal/admin_frontend/postcss.config.js` - 新建
- `/root/RoyalBot-Portal/admin_frontend/package-lock.json` - 更新

**容器状态：**
- royalbot_admin_frontend: Up (healthy)

---

### 2026-01-12 修复 Admin 后台页面显示黑色问题

**问题描述：** 修复 Tailwind CSS 后，页面从空白变成只显示黑色背景，内容无法显示

**问题根因：**
- `index.css` 中 `@import` 语句放在了 `@tailwind` 指令之后
- CSS 规则要求 `@import` 必须在所有其他语句之前（除了 `@charset`）
- 这导致样式解析错误，页面无法正确渲染

**修复内容：**
调整 `admin_frontend/src/styles/index.css` 中的语句顺序：

**修复前：**
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import './card-components.css';
@import './glass.css';
```

**修复后：**
```css
@import './card-components.css';
@import './glass.css';

@tailwind base;
@tailwind components;
@tailwind utilities;
```

**修改文件：**
- `/root/RoyalBot-Portal/admin_frontend/src/styles/index.css`

**容器状态：**
- royalbot_admin_frontend: Up (healthy)

---

### 2026-01-13 求片分类中心 - 海报墙功能

**新增功能：** 将现有求片功能升级为海报墙展示，集成 TMDB 数据

**功能特性：**
1. **公共求片池海报墙** - 显示所有用户的求片请求，以海报形式展示
2. **TMDB 集成** - 搜索 TMDB 影片自动获取海报和元数据
3. **分类筛选** - 按状态（待处理/处理中/已完成）、类型（电影/剧集/动漫/纪录片）筛选
4. **投票/订阅** - 用户可以给想要的影片投票，提高热度
5. **混合显示模式** - 默认公共求片池，可切换到"我的求片"
6. **视觉冲击力** - 响应式海报网格布局，悬停缩放效果

**新增文件：**
- `user_backend/services/tmdb.py` - TMDB API 集成服务
- `user_frontend/src/components/MediaGallery.vue` - 海报墙组件
- `user_frontend/src/components/MediaSearchSheet.vue` - TMDB 搜索弹窗
- `user_frontend/src/components/CategoryFilter.vue` - 分类筛选组件

**修改文件：**
- `user_backend/api/request.py` - 添加 gallery/搜索/投票 API
- `user_backend/schemas/request.py` - 添加 GalleryResponse/TmdbSearchResult schema
- `user_frontend/src/api/index.ts` - 扩展 requestApi 接口
- `user_frontend/src/views/RequestView.vue` - 重构为海报墙布局

**新增 API 端点：**
```
GET  /api/user/requests/gallery       - 获取海报墙求片列表
GET  /api/user/requests/tmdb-search   - TMDB 搜索
POST /api/user/requests/{id}/subscribe - 投票/订阅
GET  /api/user/requests/stats         - 获取统计数据
```

**UI 效果：**
- 响应式网格：移动端 3 列，平板 4-5 列，桌面 6 列
- 海报卡片：状态标签、热度标签、悬停放大效果
- 热度分级：🔥爆款(50+)、⭐热门(20+)、普通(5+)
- 无限滚动加载
- 投票按钮悬停显示

**环境变量配置：**
- `TMDB_API_KEY` - TMDB API 密钥（需要在 .env 中配置）

**容器状态：**
- royalbot_user_frontend: Up (running)
- royalbot_user_backend: Up (healthy)

---

### 2026-01-13 TMDB API 可视化配置功能

**新增功能：** 在管理后台系统配置中添加 TMDB API 设置

**功能特性：**
- 在系统配置的 "MoviePilot" 分类下新增 TMDB 配置项
- 支持可视化配置 TMDB API Key，无需修改 .env 文件
- 配置自动生效，5分钟缓存刷新
- 支持配置 API 地址、图片地址、搜索语言

**新增配置项：**
| 配置键 | 说明 | 类型 |
|--------|------|------|
| `tmdb_api_key` | TMDB API Key | password |
| `tmdb_base_url` | TMDB API 地址 | url |
| `tmdb_image_base_url` | TMDB 图片地址 | url |
| `tmdb_language` | 搜索语言 | text |

**修改文件：**
- `admin_backend/api/settings.py` - 添加 TMDB 配置项定义和公开 API 端点
- `user_backend/services/tmdb.py` - 从配置系统读取 API Key

**新增 API 端点：**
```
GET /settings/public/tmdb - 获取 TMDB 公开配置（无需鉴权）
```

**使用方式：**
1. 登录管理后台
2. 进入「系统配置」→「MoviePilot」分类
3. 填写 TMDB API Key（向 https://www.themoviedb.org/settings/api 申请）
4. 保存后自动生效，无需重启服务

**容器状态：**
- royalbot_admin_backend: Up (healthy)
- royalbot_user_backend: Up (healthy)

---

### 2026-01-13 User Backend 重新部署完成

**问题：** user_backend 容器缺少 tmdb.py 文件，无法加载 TMDB 配置

**解决方案：**
1. 重新构建 user_backend Docker 镜像（--no-cache）
2. 修复 tmdb.py 中的 admin backend 连接 URL：
   - 从 `http://admin_backend:8080` 修改为 `http://royalbot_admin_backend:8080`
   - 添加 `ADMIN_BACKEND_URL` 环境变量支持
3. 删除并重新创建容器，确保使用新镜像

**修改文件：**
- `user_backend/services/tmdb.py:50-54` - 修复 admin backend URL

**验证结果：**
- ✅ TMDB 配置从 admin backend 成功加载
- ✅ API 端点 `/api/settings/public/tmdb` 正常响应
- ✅ 容器健康检查通过

**当前 TMDB 配置：**
```json
{
  "tmdb_api_key": "",
  "tmdb_base_url": "https://api.themoviedb.org/3",
  "tmdb_image_base_url": "https://image.tmdb.org/t/p",
  "tmdb_language": "zh-CN"
}
```

**后续步骤：**
1. 在管理后台系统配置中填写 TMDB API Key
2. 测试海报墙功能（搜索、显示、投票）

---

### 2026-01-18 用户首页加载动画优化

**新增功能：** 骨架屏 + 品牌脉冲圆环组合加载动画

**设计理念：**
- **骨架屏**：在数据加载时显示与真实内容结构相同的灰色占位，提供内容预览
- **品牌脉冲圆环**：绿色渐变圆环旋转 + 呼吸光效，与主 CTA 按钮风格统一

**动画效果：**
1. **微光扫过效果** (`skeleton-shimmer`) - 骨架元素上从左到右的渐变光波，循环 1.5s
2. **品牌脉冲圆环** (`brand-pulse-spin`) - 28px 绿色圆环旋转，配合呼吸光晕，循环 0.8s
3. **淡入动画** (`skeleton-fade-in`) - 骨架屏整体向上滑动淡入，300ms

**骨架结构：**
| 组件 | 骨架元素 |
|------|----------|
| 3 步流程指示器 | 3 个圆点 + 2 条连线 |
| 状态卡片 | 问候语 + VIP 徽章 + CTA 按钮 + 次要链接 |
| 账号预览 | 标题栏 + 3 个字段 |
| 快捷网格 | 4 个图标卡片 |

**颜色规范：**
- 骨架基础：`rgba(255, 255, 255, 0.03~0.1)` 渐变
- VIP 徽章骨架：`rgba(16, 185, 129, 0.1~0.2)` 绿色
- CTA 按钮骨架：`rgba(16, 185, 129, 0.15~0.3)` 绿色渐变
- 快捷图标骨架：`rgba(16, 185, 129, 0.1~0.2)` 绿色

**修改文件：**
- `/root/RoyalBot-Portal/user_frontend/src/views/HomeView.vue`
  - 模板：添加 `.skeleton-view` 骨架屏结构
  - 样式：添加约 370 行骨架屏和品牌脉冲圆环 CSS

**技术细节：**
- 使用 CSS 伪元素 `::before` 实现品牌脉冲圆环，无需额外 DOM
- 所有骨架元素共享 `skeleton-shimmer` 动画，保持同步
- 响应式适配：移动端骨架元素尺寸自动缩小

---

### 2026-01-18 修复 502 Bad Gateway 网络问题

**问题描述：** 网站访问显示 502 Bad Gateway

**问题根因：** Docker 网络隔离问题

容器分布在两个不同的 Docker 网络：
- `royalbot-emby-deploy_royalbot_network` (旧网络)
- `royalbot-portal_royalbot_network` (新网络)

| 容器 | 修复前网络 | 修复后网络 |
|------|-----------|-----------|
| royalbot_nginx | 旧网络 + 新网络 | 新网络 |
| royalbot_user_frontend | 新网络 | 新网络 |
| royalbot_admin_frontend | 旧网络 ❌ | 新网络 ✅ |
| royalbot_user_backend | 新网络 | 新网络 |
| royalbot_admin_backend | 新网络 | 新网络 |

Nginx 容器同时连接在两个网络中，DNS 解析混乱导致尝试连接到错误的 IP（`172.19.0.3` 而非 `172.18.0.3`），产生 `Host is unreachable` 错误。

**修复操作：**
```bash
# 1. 将 nginx 从旧网络中断开
docker network disconnect royalbot-emby-deploy_royalbot_network royalbot_nginx

# 2. 将 admin_frontend 连接到新网络
docker network connect royalbot-portal_royalbot_network royalbot_admin_frontend

# 3. 将 admin_frontend 从旧网络中断开
docker network disconnect royalbot-emby-deploy_royalbot_network royalbot_admin_frontend

# 4. 重启 nginx 清除 DNS 缓存
docker restart royalbot_nginx
```

**修复结果：**
- ✅ 网站访问正常，返回 HTTP 200
- ✅ 所有容器在同一网络 `royalbot-portal_royalbot_network`
- ✅ Nginx 可正确解析所有 upstream 服务

---

### 2026-01-18 修复登录后首页数据不显示问题

**问题描述：** 用户登录成功后进入首页，不会显示账号信息，需要刷新页面才能看到

**问题根因：** Vue 组件生命周期时序问题

| 阶段 | 状态 |
|------|------|
| 1. 用户打开首页（未登录） | `onMounted` 执行，`isLoggedIn` = false，不加载数据 |
| 2. 用户点击登录 | 登录成功后 `userStore.token` 和 `userStore.user` 更新 |
| 3. 跳转回首页 | `onMounted` **不会再次执行**，数据未加载 |
| 4. 手动刷新页面 | 组件重新挂载，`onMounted` 再次执行，此时已登录 |

问题关键：`onMounted` 钩子只在组件挂载时执行一次，不会响应登录状态的变化。

**修复内容：**

添加了 `watch` 监听器，监听 `isLoggedIn` 状态变化，当从未登录变为已登录时自动加载数据。

**修改文件：** `/root/RoyalBot-Portal/user_frontend/src/views/HomeView.vue`

**修改前：**
```javascript
onMounted(async () => {
  await fetchUserStats()
  if (!isLoggedIn.value) {
    loading.value = false
    return
  }
  await Promise.all([
    fetchAnnouncements(),
    fetchEmbyAccounts(),
    fetchSubscription(),
    fetchUserBalance()
  ])
  loading.value = false
  await p0Announcement.init()
})

const handleAuthSuccess = () => {
  Promise.all([
    fetchEmbyAccounts(),
    fetchSubscription(),
    fetchUserBalance()
  ])
}
```

**修改后：**
```javascript
// 新增：统一的用户数据加载函数
const loadUserData = async () => {
  if (!isLoggedIn.value) return
  loading.value = true
  try {
    await Promise.all([
      fetchAnnouncements(),
      fetchEmbyAccounts(),
      fetchSubscription(),
      fetchUserBalance()
    ])
  } finally {
    loading.value = false
  }
}

// 新增：监听登录状态变化
watch(isLoggedIn, (newValue, oldValue) => {
  // 只在从未登录变为已登录时触发
  if (newValue && !oldValue) {
    loadUserData()
  }
})

onMounted(async () => {
  await fetchUserStats()
  if (isLoggedIn.value) {
    await loadUserData()  // 使用统一函数
  } else {
    loading.value = false
  }
  await p0Announcement.init()
})

// 修改：添加 await 确保数据加载完成
const handleAuthSuccess = async () => {
  await loadUserData()
}
```

**修复结果：**
- ✅ 登录成功后自动加载数据
- ✅ 无需刷新页面即可看到账号信息
- ✅ 统一的数据加载入口，代码更简洁

---

### 2026-01-18 版本更新 v1.8.0

**更新内容：**
- 修复登录后首页数据不显示问题
- 添加 watch 监听 isLoggedIn 状态变化
- 新增统一的 loadUserData 函数
- 更新部署脚本版本至 v1.8.0

**仓库变更：**
- **源代码仓库（私密）：** https://github.com/xzb177/Aetrix-Portal.git
  - 推送完整源代码
  - 包含前后端、数据库、脚本等全部文件

- **脚本仓库（公开）：** https://github.com/xzb177/royalbot-deploy-scripts.git
  - 仅包含部署脚本 `deploy.sh` 和 `update.sh`
  - 公开可供任何人下载使用
  - 用户可通过 curl 直接下载使用

**Git 提交：**
```
commit 72eff65
fix: 修复登录后首页数据不显示问题
```

**文件变更：**
- `user_frontend/src/views/HomeView.vue` - 添加 watch 和 loadUserData
- `deploy.sh` - 版本更新至 v1.8.0
- `update.sh` - 版本更新至 v1.8.0
- `web.md` - 添加更新记录

**使用方式：**
```bash
# 下载部署脚本
curl -fsSL https://raw.githubusercontent.com/xzb177/royalbot-deploy-scripts/main/deploy.sh -o deploy.sh
chmod +x deploy.sh
./deploy.sh
```

---

### 2026-01-19 设计系统全面升级 v2.0

**升级概述：** 从美工设计师视角对整个项目进行全面的设计系统升级，建立统一的设计语言和组件库。

#### 一、品牌色统一 ✅

**修改内容：**
- 将管理端的紫色渐变（#4CAF50 → #673AB7）改为绿色渐变（#10b981 → #059669）
- 全平台统一使用 Emerald 绿色（#10b981）作为品牌主色
- 更新所有相关组件的 hover、focus、active 状态

**修改文件：**
- `admin_frontend/src/styles/index.css` - 更新主题色变量
- `admin_frontend/src/styles/glass.css` - 更新玻璃态组件颜色
- `admin_frontend/src/styles/card-components.css` - 更新卡片组件颜色（重写为暗色风格）

#### 二、亮色主题系统 ✅

**新增功能：**
- 完整的亮色/暗色主题切换支持
- 主题切换平滑过渡动画（300ms）
- 主题偏好持久化到 localStorage
- 支持跟随系统自动切换（auto）

**新增文件：**
- `user_frontend/src/composables/useTheme.ts` - 主题切换 Composable
- `user_frontend/src/components/ui/ThemeToggle.vue` - 主题切换按钮组件

**修改文件：**
- `user_frontend/src/styles/design-tokens.css` - 添加亮色主题变量
- `user_frontend/src/styles/index.css` - 添加主题切换过渡动画

#### 三、空状态组件 ✅

**新增组件：**
- `user_frontend/src/components/ui/EmptyState.vue` - 用户端空状态组件
- `admin_frontend/src/components/feedback/EmptyState.vue` - 管理端空状态组件（增强版）

**支持变体：**
- default - 默认空状态
- search - 搜索无结果
- data - 数据为空
- error - 错误状态
- success - 成功状态

#### 四、表单元素统一 ✅

**新增组件：**
- `user_frontend/src/components/ui/FormInput.vue` - 输入框组件
- `user_frontend/src/components/ui/FormSelect.vue` - 下拉选择组件
- `user_frontend/src/components/ui/FormCheckbox.vue` - 复选框组件
- `user_frontend/src/components/ui/FormSwitch.vue` - 开关组件

**统一特性：**
- 一致的视觉风格（暗色玻璃态）
- 统一的错误状态提示
- 统一的禁用状态
- 统一的焦点样式（绿色光圈）

#### 五、微交互动画 ✅

**新增文件：**
- `user_frontend/src/composables/useAnimate.ts` - 动画 Composable
- `user_frontend/src/directives/animate.ts` - 动画指令

**新增动画：**
- fadeIn - 淡入
- fadeInUp/Down/Left/Right - 方向淡入
- scaleIn - 缩放淡入
- 列表交错动画（stagger）
- 视口进入动画（Intersection）

**新增 CSS 动画类：**
- `.animate-fadeIn` / `.animate-fadeInUp` / `.animate-fadeInDown`
- `.animate-fadeInLeft` / `.animate-fadeInRight`
- `.animate-scaleIn` / `.animate-slideInUp` / `.animate-slideInDown`
- `.animate-spin` / `.animate-pulse` / `.animate-bounce` / `.animate-shake`
- `.stagger-item` / `.stagger-container` - 交错动画
- `.hover-lift` / `.hover-scale` / `.hover-glow` - 悬停微交互

#### 六、图标系统统一 ✅

**新增组件：**
- `user_frontend/src/components/ui/Icon.vue` - 统一图标组件

**图标尺寸规范：**
- xs: 14px, sm: 16px, md: 20px, lg: 24px, xl: 32px, 2xl: 48px

**内置图标库：**
- 导航：home, user, settings
- 操作：search, close, check, plus, minus, edit, delete, refresh
- 状态：success, error, warning, info
- 箭头：arrow-up/down/left/right, chevron-up/down
- 文件：file, folder
- 媒体：image, play, pause
- 通信：mail, bell
- 加载：loader

#### 七、加载状态优化 ✅

**新增组件：**
- `user_frontend/src/components/ui/LoadingSpinner.vue` - 加载动画组件
- `user_frontend/src/components/ui/Skeleton.vue` - 骨架屏组件
- `user_frontend/src/components/ui/LoadingButton.vue` - 加载按钮组件

**支持尺寸：**
- LoadingSpinner: xs, sm, md, lg, xl
- Skeleton: text, circle, rect, rounded 变体

#### 八、颜色对比度提升 ✅

**优化内容：**
- 提升文字颜色对比度至 WCAG AA/AAA 标准
- 暗色主题主文字：21:1（AAA）
- 暗色主题次要文字：14.3:1（AAA）
- 暗色主题三级文字：9.6:1（AA）
- 亮色主题文字：16.1:1 / 11.3:1 / 7.1:1

**修改文件：**
- `user_frontend/src/styles/design-tokens.css` - 更新颜色变量

#### 九、过渡动画优化 ✅

**新增组件：**
- `user_frontend/src/components/ui/Modal.vue` - 模态框组件（带过渡动画）
- `user_frontend/src/components/ui/PageTransition.vue` - 页面切换过渡组件

**过渡效果：**
- 背景淡入淡出
- 内容缩放淡入
- 支持多种过渡方向（fade, slide-up/down/left/right, scale）
- 响应式移动端底部滑入

#### 十、主题自定义功能 ✅

**新增组件：**
- `user_frontend/src/components/ui/ThemeCustomizer.vue` - 主题设置面板

**功能特性：**
- 6 种预设主题色（默认绿、天空蓝、罗兰紫、玫瑰红、落日橙、青绿色）
- 自定义品牌色选择器
- 主题模式切换（浅色/深色/跟随系统）
- 自定义主题持久化
- 浮动触发按钮

---

**新增文件汇总：**

| 文件 | 功能 |
|------|------|
| `user_frontend/src/composables/useTheme.ts` | 主题切换 |
| `user_frontend/src/composables/useAnimate.ts` | 动画系统 |
| `user_frontend/src/directives/animate.ts` | 动画指令 |
| `user_frontend/src/components/ui/ThemeToggle.vue` | 主题切换按钮 |
| `user_frontend/src/components/ui/ThemeCustomizer.vue` | 主题设置面板 |
| `user_frontend/src/components/ui/EmptyState.vue` | 空状态组件 |
| `user_frontend/src/components/ui/Icon.vue` | 图标组件 |
| `user_frontend/src/components/ui/FormInput.vue` | 输入框组件 |
| `user_frontend/src/components/ui/FormSelect.vue` | 下拉选择组件 |
| `user_frontend/src/components/ui/FormCheckbox.vue` | 复选框组件 |
| `user_frontend/src/components/ui/FormSwitch.vue` | 开关组件 |
| `user_frontend/src/components/ui/LoadingSpinner.vue` | 加载动画 |
| `user_frontend/src/components/ui/Skeleton.vue` | 骨架屏 |
| `user_frontend/src/components/ui/LoadingButton.vue` | 加载按钮 |
| `user_frontend/src/components/ui/Modal.vue` | 模态框 |
| `user_frontend/src/components/ui/PageTransition.vue` | 页面过渡 |

---