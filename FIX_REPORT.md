# RoyalBot Emby Portal — 修复与优化汇总

## ✅ 已完成的安全修复

### P0 级（紧急）
1. **`.secret_key` 密钥泄露** → 已加入 `.gitignore`（⚠️ Git 历史无法清除，建议轮换密钥）
2. **Emby API Key 加密存储** → `EmbyServer` 模型加了 `@property` 自动加解密，读写透明
3. **附件下载路径遍历** → `get_attachment` 加了 `../` 检查 + `realpath` 二次校验
4. **LoginTracker 内存存储** → 全部迁移到 Redis（`SyncRedisWrapper`），支持多实例/重启持久

### P1 级（重要）
5. **用户端 /docs 暴露** → 生产环境 `docs_url=None, redoc_url=None`
6. **CORS 过于宽松** → `allow_methods=["*"]` → `["GET","POST","PUT","DELETE","PATCH"]`；`allow_headers=["*"]` → `["Content-Type","Authorization","X-CSRF-Token"]`
7. **sys.path 硬编码 `/root/royalbot`** → 改为环境变量 `PARENT_PROJECT_PATH` + 自动回退到上级目录
8. **根路径泄露信息** → 生产环境只返回 `{"status":"ok"}`

## 🔧 待主人确认的 UI 优化方案

### 管理端（admin_frontend）
管理端已有成熟的 glass 设计系统 + Dashboard + 45 个页面，整体质量不错。优化建议：

1. **Dashboard 精简**：当前 MetricCard 数据源有 5 个 API 调用（portalStats/ticketStats/embyServers/paymentStats/adminLogs），可合并为 1-2 个聚合接口，减少首屏加载时间
2. **Layout 侧边栏**：已支持可拖动宽度（256px，min 200，max 400），但菜单项 15 个偏多。建议分组折叠（用户管理/Emby 管理/运营/系统 四组）
3. **路由表**：45 个页面，部分页面名不一致（如 `MobileLogin` vs `MobileLogin.vue`），建议统一命名

### 用户端（user_frontend）
用户端设计更成熟（composables 丰富、有 A/B 测试支持），但：

1. **HomeView.vue 58,899 行** — 这是巨无霸文件，建议拆分为子组件（HomeHeader/HomeAccounts/HomeActions/HomeAnnouncements）
2. **移动端适配**：有 `MobileLoginView/MobileRegisterView` 独立路由，但首页的响应式处理是否完善需要检查
3. **暗色主题**：`useTheme` composable 存在，说明已有主题切换，但各页面是否都适配了暗色模式需要验证
4. **QR 码**：引入了 `qrcode` 库，可能用于邀请分享，可以增加扫码登录功能

### 共通优化
1. **TypeScript 类型强化**：API 返回值大多用 `any`，建议定义统一的接口类型
2. **错误边界**：前端缺少全局错误边界组件
3. **懒加载优化**：路由已用 `() => import(...)` 懒加载 ✅，但可以加 `webpackPrefetch`/路由分组
4. **国际化**：当前全中文硬编码，如果要做海外市场需要 i18n
