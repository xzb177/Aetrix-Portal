# RoyalBot Emby 后台管理系统 - 开发备忘录

> 本文档记录开发进度，每次更新保留历史内容，添加新内容到顶部。

---

## 2026-01-05 项目初始化与基础功能完成

### 1. 搞定了什么

✅ **完整的后台管理系统已上线运行**

- 后端 FastAPI 服务：http://localhost:8080
- 前端 Vue3 界面：http://localhost:5173
- 实现了用户管理、Emby 管理、推送管理、活动管理、统计分析等完整功能
- 多角色权限系统（super_admin/admin/operator）
- 所有核心 API 测试通过

### 2. 关键信息

**项目结构**
```
/root/royalbot/admin_backend/    # 后端 FastAPI
/root/royalbot/admin_frontend/   # 前端 Vue3
```

**启动命令**
```bash
# 后端
cd /root/royalbot/admin_backend
python3 main.py

# 前端
cd /root/royalbot/admin_frontend
npm run dev
```

**默认管理员**
- 用户名：`admin`
- 密码：`admin123456`

**关键修改的文件**

后端：
- `admin_database.py` - 使用本地简化模型，避免与主项目模型冲突
- `admin_models.py` - 创建匹配实际数据库的简化模型
- `api/users.py` - 移除不存在的字段（registered_date、guild_id等）
- `api/stats.py` - 修复新用户统计逻辑
- `schemas/user.py` - 简化用户数据结构

前端：
- `src/utils/request.ts` - **关键修复**：开发环境使用 `/api` 代理，避免网络错误

**环境变量**
- 后端：`ADMIN_FRONTEND_URLS=http://localhost:5173,http://localhost:3000`
- 前端：`VITE_API_BASE_URL=http://localhost:8080`（生产环境使用）

**数据库**
- 复用主项目数据库：`/root/royalbot/data/magic.db`
- 管理员表独立：`admin_users`、`admin_roles`、`admin_logs`

### 3. 接下来该干嘛

**下次开发的第一步：**
```bash
# 1. 进入后端目录
cd /root/royalbot/admin_backend

# 2. 启动后端
python3 main.py

# 3. 启动前端（另一个终端）
cd /root/royalbot/admin_frontend
npm run dev
```

**待完善功能（优先级排序）：**
1. 前端 UI 美化优化
2. 更多数据可视化图表
3. 用户头像从 Telegram 获取
4. 实时数据刷新
5. 推送功能测试
6. 部署到生产环境

---

## API 端点清单

| 方法 | 路径 | 功能 | 权限 |
|------|------|------|------|
| POST | /api/auth/login | 登录 | - |
| GET | /api/users | 用户列表 | users.view |
| GET | /api/users/{id} | 用户详情 | users.view |
| PUT | /api/users/{id} | 更新用户 | users.edit |
| POST | /api/users/{id}/vip | VIP切换 | users.vip |
| DELETE | /api/users/{id} | 删除用户 | users.delete |
| GET | /api/emby/stats | Emby统计 | emby.view |
| GET | /api/activities | 活动列表 | activities.view |
| GET | /api/stats/overview | 概览统计 | stats.view |
| GET | /api/stats/ranking | 排行榜 | stats.view |
| GET | /api/stats/logs | 操作日志 | system.logs |

---

*本文档持续更新中...*

---

## 2026-01-12 更新

### 一键导入客户端功能优化

**问题描述：**
用户反馈一键导入客户端功能点击后只打开 app 但没有添加服务器配置。

**解决方案：**
1. 研究了多个开源项目的 URL Scheme 实现：
   - [alistWebLaunchExternalPlayer](https://greasyfork.org/zh-CN/scripts/494829-alistweblaunchexternalplayer/code)
   - [embyLaunchPotplayer](https://greasyfork.org/en/scripts/514529-embylaunchpotplayer)
   - [embyToLocalPlayer](https://github.com/kjtsune/embyToLocalPlayer)

2. 更新 URL Scheme 格式：
   - **SenPlayer**: `SenPlayer://add?host=xxx&port=xxx&username=xxx&password=xxx&type=emby`
   - **Forward**: `forward://emby/add?url=xxx&apikey=xxx&user=xxx&name=xxx`
   - **EplayerX**: `eplayerx://emby/add?url=xxx&apikey=xxx&user=xxx&name=xxx`
   - **Emby 官方**: `emby://host#username@password`

3. 发现 URL Schemes 分为两类：
   - 播放媒体：使用 `x-callback-url/play?url=` 格式
   - 添加服务器：使用 `add?` 格式带服务器参数

**修改文件：**
- `user_frontend/src/components/PlayerSelectorSheet.vue`

**参考来源：**
- [Totoro Hub - SenPlayer支持一键导入Emby信息](https://totoro.im/thread-1209.htm)
- [Forward - 新视界 | FORWARD食用指南](https://forward-2.gitbook.io/forward)

