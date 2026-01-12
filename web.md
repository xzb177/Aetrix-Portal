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