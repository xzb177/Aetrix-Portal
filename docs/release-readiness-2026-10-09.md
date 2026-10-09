# 发布准备度核查（2026-10-09）

> 临时产物：本文件是 `cline/gd6enahn` 保存分支上的核查记录，不是正式文档，未加入 `docs/README.md` 索引。
> 核查对象：`main` @ `18cc793`（Merge PR #423）。工作树无改动。

## 结论

**代码是绿的，但"发布定稿"没做，因此当前不能直接发布。**

- ✅ 4 项必需状态检查在本地全部复现通过（见 §1）。
- ❌ `VERSION` 仍是上一版 `2.48.0`，未抬升。
- ❌ `CHANGELOG.md` 顶部有 7 个 `[未发布]` 段落未定稿（其中 2 段重复），且落后于 `main`（PR #411–#423 的改动完全没记录）。

## 1. 4 项必需检查的本地复现结果

| 必需检查 | 结果 | 证据 |
|---|---|---|
| 前端 · user_frontend | ✅ 4/4 | 路由契约 / 令牌契约 / `vue-tsc` / `vite build` 退出码均 0；dist 44 个文件 |
| 前端 · admin_frontend | ✅ 4/4 | 同上；`base: '/admin/'` 正确，`dist/index.html` 无裸 `/assets/` 泄漏 |
| 后端 · 冒烟测试 | ✅ 59/59 步骤 | pytest **1941 passed / 0 failed**；46 条 smoke 脚本全绿；3 处环境性 SKIP |
| 后端 · 部署自检 | ✅ | `scripts/deploy_check.py`：真起 uvicorn + 真发 HTTP，「部署自检全部通过」，2 条警告（无 ffprobe / 未设 SECRET_KEY） |

环境性 SKIP（不判红）：2 处 ffmpeg/HLS（本机无 ffmpeg）、1 处 TMDB 密钥未配。

未在本地验证的 CI job（不在 4 项必需之列）：`后端 · PG 兼容冒烟`（需要 Postgres 服务，本沙箱无）。

### 记录在案的一处脆弱性（非阻断）

`python -m pytest tests/` **不能单独在干净库上跑通**：`tests/test_bind_tmdb.py` 的 fixture teardown 会把
全局 `SessionLocal` 回退到默认 engine，而默认 engine 指向 job 级 `DATABASE_URL`（CI 里是 `./ci-smoke.db`）。
真实 CI 中该库已被前序 smoke 步骤建好 61 张表，所以绿；若单独用空库跑 pytest，会出现
`no such table: emby_libraries`（实测 36F/79E）。即**测试套件隐式依赖 CI 的步骤顺序与库副作用**，
对"本地单跑 pytest"不友好。CI 口径下不影响发布。

## 2. 版本号与 CHANGELOG 现状

- `VERSION` = `2.48.0`；`check_version.py` 绿（VERSION / 两个前端 `package.json` + lock / `branding.ts` `APP_VERSION` 全部对齐）。
- 最后一次定稿版本：`## [2.48.0] - 2026-10-04`（CHANGELOG 第 323 行）。
- 顶部 7 个 `[未发布]` 段落（行号 5 / 85 / 143 / 169 / 194 / 233 / 280）：
  稳定性性能整改、媒体信息探测 worker 重构、安全修复（3 严重 + 5 高危）、恢复 2d7d996 误删功能、
  后端清理、**安全修复（3 严重 + 5 高危）← 与第 143 行基本重复**、用户端「暗房影院」改版。
- 仓库惯例是**一个版本号一段**（108 个历史版本段落，无重复版本号）；发布由专门提交完成，
  一次可补齐多个版本段落（先例：`版本号 2.39.0 → 2.42.0，补齐 2.40.0/2.41.0/2.42.0`）。
  → 发布前应把 7 段**逐段升为独立版本号 + 日期**，而不是合并成一段。
- **CHANGELOG 落后于 main**：`grep -cE '单一播放路径|片头缓存|硬件转码|CPU 自适应' CHANGELOG.md` = 0。
  2026-10-08 09:13 之后合入的 PR #411–#423（单一播放路径重构、CPU 自适应、用户级转码开关、
  硬件转码自检、片头缓存增删、`header_cache.py` 删除）不在任何段落里。

## 3. 发布机制（澄清）

本仓库的"发布"= **CI 全绿后自动把镜像推到 ghcr.io**：

- `publish-images.yml` 由 `workflow_run` 监听 `CI` 完成；仅当 `conclusion==success && event==push && head_branch==main` 才发布。
- 镜像 `ghcr.io/xzb177/aetrix-api` / `aetrix-web`，各打 3 个 tag：`<VERSION>` / `sha-<短哈希>` / `latest`；tag 来自根目录 `VERSION`。
- **不打 git tag、不建 GitHub Release、不改 CHANGELOG**（仓库 tag 与 Release 数量均为 0，这是设计而非缺陷）。
- 所以"发版"的实际动作 = 改 `VERSION` + 定稿 `CHANGELOG` → 提 PR 合入 `main` → 等 CI 绿 → 镜像自动出。

## 4. 其它已知项（非阻断）

- `env.example` 已列出 CHANGELOG 承诺的全部新变量（`RELAY_*` / `EMBY_TRANSCODE_IDLE|ABANDON` /
  `REDIS_BREAKER_*` / `WORKER_RESTART_*` / `ITEMS_DEDUP_MAX_*` / `PROBE_*`，行 351–401）。
- 但 `scripts/check_env_contract.py` **不覆盖**这些变量（它只查 compose.prod ↔ env.example），
  即这批调优项没有机器门禁保护。
- 管理端"探测进度卡片"未实现（后端 `GET /api/admin/emby/scrape/probe-progress` 已就绪，
  `admin_frontend/src` 内无对应 UI）——CHANGELOG 第 141 行已自认。
- `backend/notifications.py:730` 有一处描述历史的 `TODO`，非待办。

## 5. 要发布还差什么

1. 拍定目标版本号（代码/`env.example` 里的特性标签最高到 `v2.53.0`，跨度约 2.49–2.53）。
2. 抬升 `VERSION`，并同步两个前端 `package.json` + `package-lock.json` + `admin_frontend/src/composables/branding.ts` 的 `APP_VERSION`。
3. 定稿 `CHANGELOG`：7 段逐段成版、去重、补记 PR #411–#423。
4. 提 PR 合入 `main`，等 4 项必需检查全绿；绿了镜像自动发到 ghcr.io。
