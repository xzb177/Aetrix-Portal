# 管理后台页面与功能清单

> 生成方式：`admin_frontend/src/router/index.ts` 的路由表 + 各视图源码的控件统计。
> 重新生成见文末命令。**这份清单是排查基线**：改后台时对着它看有没有漏掉的入口。

## 一、规模

- **页面 28 个**（另有 `/login` 登录页、`/setup` 首次运行向导，以及 2 个旧地址跳转）
- **API 封装 191 个**（`admin.ts` 154 / `economy.ts` 31 / `capabilities.ts` 4 / `site.ts` 2）
- **写操作鉴权**由 `admin_roles.SUPER_ONLY_PREFIXES` 统一管：只读角色任何写都不行，
  运营角色额外被挡在「超管专属」前缀之外

## 二、逐页清单

`按钮 / 表单控件 / 表格` 为该页源码里的 `el-*` 控件数量，可当作「这个页面有多少可点的东西」的粗略口径。

| 路由 | 页面 | 视图 | 行数 | 按钮 | 表单控件 | 表格 |
|---|---|---|---|---|---|---|
| `/` | 仪表盘 | Dashboard.vue | 938 | 0 | 4 | 0 |
| `/users` | 用户 | Users.vue | 1164 | 22 | 13 | 0 |
| `/subscriptions` | 订阅与权益 | Subscriptions.vue | 550 | 8 | 9 | 0 |
| `/goods` | 商品管理 | Goods.vue | 377 | 11 | 19 | 0 |
| `/orders` | 运营·订单 | Orders.vue | 511 | 9 | 7 | 0 |
| `/exchange-codes` | 运营·兑换码 | ExchangeCodes.vue | 247 | 6 | 11 | 0 |
| `/coupons` | 运营·优惠券 | Coupons.vue | 767 | 16 | 37 | 0 |
| `/invitations` | 运营·邀请与积分 | Invitations.vue | 791 | 13 | 19 | 0 |
| `/codes` | 卡码管理 | RegistrationCodes.vue | 568 | 11 | 24 | 0 |
| `/devices` | 设备与安全 | Devices.vue | 374 | 6 | 2 | 0 |
| `/login-logs` | 登录日志 | LoginLogs.vue | 231 | 3 | 4 | 0 |
| `/share-guard` | 防共享 | ShareGuard.vue | 514 | 5 | 6 | 0 |
| `/access-guard` | 访问拦截 | AccessGuard.vue | 500 | 4 | 10 | 0 |
| `/announcements` | 公告管理 | Announcements.vue | 303 | 11 | 5 | 0 |
| `/tickets` | 工单 | Tickets.vue | 289 | 4 | 4 | 0 |
| `/media-seek` | 求片管理 | MediaSeek.vue | 458 | 8 | 6 | 0 |
| `/emby` | 媒体库 | EmbyAdmin.vue | 2265 | 27 | 19 | 0 |
| `/library-scope` | 媒体库可见范围 | LibraryScope.vue | 613 | 10 | 6 | 0 |
| `/metadata-sources` | 元数据来源 | MetadataSources.vue | 1183 | 27 | 15 | 0 |
| `/mounts` | 存储来源 | StorageMounts.vue | 1050 | 17 | 15 | 0 |
| `/pan115` | 115 账号 | Pan115Accounts.vue | 522 | 13 | 5 | 0 |
| `/settings` | 系统设置 | Settings.vue | 1124 | 11 | 15 | 0 |
| `/admins` | 管理员与权限 | Admins.vue | 435 | 8 | 4 | 0 |
| `/client-policy` | 客户端策略 | ClientPolicy.vue | 977 | 8 | 16 | 0 |
| `/logs` | 操作日志 | Logs.vue | 205 | 1 | 3 | 0 |
| `/health` | 服务健康 | SystemHealth.vue | 218 | 3 | 2 | 0 |
| `/realms` | 服管理 | Realms.vue | 602 | 11 | 11 | 0 |
| `/servers` | 服务器与线路 | Servers.vue | 1500 | 24 | 13 | 0 |

## 三、自动化的部分：契约门禁

「30 个页面逐个点三遍」是人天的活，而且改完又得重来。所以把能自动化的那部分固化成门禁：

| 检查 | 拦什么 |
|---|---|
| `scripts/check_admin_api_contract.py` | 前端调用了不存在的端点（运行时 404 = 按钮点了没反应）；顺带报出靠 URL 归一化才生效的脆弱路径 |
| `scripts/check_auth_coverage.py` | 写端点漏鉴权 |
| `scripts/check_admin_audit_coverage.py` | 写端点漏审计 |
| `scripts/check_frontend_routes.py` | 跳转到不存在的路由 |
| `scripts/check_frontend_tokens.py` | 引用了没人定义的 CSS 变量 |
| `tests/test_admin_roles_super_only.py` | 超管专属前缀漏项（越权写操作） |

新增页面 / 端点时跑一遍 `python scripts/check_admin_api_contract.py` 即可；
它 introspect 的是**运行时**路由表，所以「源码写了但忘了 include_router」的幽灵端点
也会被正确判定为不存在。

## 四、重新生成上表

```bash
python - <<'PY'
import re, pathlib
router = pathlib.Path('admin_frontend/src/router/index.ts').read_text(encoding='utf-8')
pat = re.compile(r"path:\s*'(?P<path>[^']*)',\s*(?:alias:[^,]*,\s*)?name:\s*'(?P<name>[^']*)',\s*"
                 r"component:\s*\(\)\s*=>\s*import\('@/views/(?P<view>[^']+)'\)", re.S)
for m in pat.finditer(router):
    src = (pathlib.Path('admin_frontend/src/views') / m.group('view')).read_text(encoding='utf-8')
    print(m.group('path'), m.group('view'),
          len(re.findall(r'<el-button', src)),
          len(re.findall(r'<el-(?:input|select|switch|checkbox|radio)', src)))
PY
```