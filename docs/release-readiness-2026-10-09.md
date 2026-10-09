# 发布准备度核查（2026-10-09）

> 临时产物：本文件是 `cline/gd6enahn` 保存分支上的核查记录，不是正式文档，未加入 `docs/README.md` 索引。
> 核查对象：`main` @ **`636ba05`**（Merge PR #416，2026-10-09 13:28）。首轮核查针对 `18cc793`，main 前进后已复验。

## 结论

**代码是绿的，但"发布定稿"没做，因此当前不能直接发布。**

- ✅ 4 项必需状态检查在本地全部复现通过（见 §1）。
- ❌ `VERSION` 仍是上一版 `2.48.0`，未抬升。
- ❌ `CHANGELOG.md` 顶部有 7 个 `[未发布]` 段落未定稿（其中 2 段重复），且落后于 `main`。
- ❌ PR #416 刚删掉预提取，而 `env.example` / 模块 docstring / CHANGELOG 都还在描述它（见 §4）。

## 1. 4 项必需检查的本地复现结果

| 必需检查 | 结果 | 证据 |
|---|---|---|
| 前端 · user_frontend | ✅ 4/4 | 路由契约 / 令牌契约 / `vue-tsc` / `vite build` 退出码均 0（基于 `18cc793`；`18cc793..636ba05` **未触碰任何前端文件**，故结论对新 main 同样成立） |
| 前端 · admin_frontend | ✅ 4/4 | 同上；`base: '/admin/'` 正确，`dist/index.html` 无裸 `/assets/` 泄漏 |
| 后端 · 冒烟测试 | ✅ 59/59 步骤 | 在 `636ba05` 的独立 worktree 上按 CI 顺序重跑：58 条脚本步骤全绿，pytest **1940 passed / 0 failed**（比 `18cc793` 少 1 条，系 PR #416 删除 `tests/test_mediainfo_persist.py` 的用例） |
| 后端 · 部署自检 | ✅ | 在 `636ba05` 上跑 `scripts/deploy_check.py`：「部署自检全部通过」，4 条警告（2 条构建产物时间戳、无 ffprobe、未设 SECRET_KEY） |

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
  PR #411–#423（单一播放路径重构、CPU 自适应、用户级转码开关、硬件转码自检、片头缓存增删、
  `header_cache.py` 删除）以及 **PR #416（删除预提取/秒播助手）** 都不在任何段落里。

## 3. 发布机制（澄清）

本仓库的"发布"= **CI 全绿后自动把镜像推到 ghcr.io**：

- `publish-images.yml` 由 `workflow_run` 监听 `CI` 完成；仅当 `conclusion==success && event==push && head_branch==main` 才发布。
- 镜像 `ghcr.io/xzb177/aetrix-api` / `aetrix-web`，各打 3 个 tag：`<VERSION>` / `sha-<短哈希>` / `latest`；tag 来自根目录 `VERSION`。
- **不打 git tag、不建 GitHub Release、不改 CHANGELOG**（仓库 tag 与 Release 数量均为 0，这是设计而非缺陷）。
- 所以"发版"的实际动作 = 改 `VERSION` + 定稿 `CHANGELOG` → 提 PR 合入 `main` → 等 CI 绿 → 镜像自动出。

## 4. 其它已知项（非阻断，但影响发布说明准确性）

- **`PROBE_PREEXTRACT_INTERVAL_SEC` 已是死变量**：PR #416 移除了它的全部读取点
  （`probe_worker.py` 里只剩 `PROBE_TRIAGE_CHUNK`），但 `env.example:401` 仍把它注释为
  「队列整理（triage）间隔」，`probe_worker.py:30` 的模块 docstring 也仍在引用它。
  用户按文档设置该变量将**毫无效果**。
- **CHANGELOG 与代码相互矛盾**：`[未发布]` 第 85 行那段把「预提取」写成了新设计的组成部分，
  而 PR #416 已把预提取整体删除。
- `env.example` 已列出 CHANGELOG 承诺的其余新变量（`RELAY_*` / `EMBY_TRANSCODE_IDLE|ABANDON` /
  `REDIS_BREAKER_*` / `WORKER_RESTART_*` / `ITEMS_DEDUP_MAX_*` / `PROBE_*`，行 351–401）。
- 但 `scripts/check_env_contract.py` **不覆盖**这些变量（它只查 compose.prod ↔ env.example），
  即这批调优项（含上面那个死变量）没有机器门禁保护——**这正是死变量能溜进来的原因**。
- 管理端"探测进度卡片"未实现（后端 `GET /api/admin/emby/scrape/probe-progress` 已就绪，
  `admin_frontend/src` 内无对应 UI）——CHANGELOG 第 141 行已自认。
- `backend/notifications.py:730` 有一处描述历史的 `TODO`，非待办。
## 6. 发布动作（已执行）

- 分支 `chore/release-2.55.0`（从 `origin/main` @ `636ba05` 切出），PR **#425**。
- `VERSION` 2.48.0 → **2.53.0**（按维护者要求落在 2.53.x，并与代码里最高的 `v2.53` 标注对齐）；
  同步两个 `package.json` + lock + `branding.ts` 的 `APP_VERSION`。
- CHANGELOG：7 段 `[未发布]` 压缩定稿为 **2.49.0–2.53.0**（2.53.0 = 播放链路与转码改造 + 探测 worker 重构、
  2.52.0 = 稳定性/性能、2.51.0 = 安全修复 + 恢复误删、2.50.0 = 后端清理、2.49.0 = 用户端主题），并补记此前完全没进 CHANGELOG 的 PR #413–#416 / #420 / #422 / #423；
  删掉与第 143 行重复的安全修复段（其「升级须知」并入 2.52.0）。
- **版本映射是推断的**：依据「一版一段 + 顶部最新（=版本降序）」惯例，并用代码里的两处标注交叉印证
  （`v2.51.0 演员表` ↔ 「恢复误删功能」段、`v2.53 探测 worker` ↔ 第 2 段）。需要维护者确认；
  代码里另有 `v2.49.0 文件名解析` / `v2.50.0 增量扫描` / `v2.52.0 Drive Changes` 等标注，
  这些功能在 CHANGELOG 里**没有任何段落**，属于仍缺的记录。
- 本地已验证：后端冒烟 job 59/59（pytest 1940 passed）、部署自检通过、两个前端契约 + 类型检查 + 构建全绿。

## 7. 顺带发现并修掉的真回归（PR #416 遗留）

- `_preprobe_loop` 被删时，把挂在它上面的 **triage 调度一起删了** → `triage()` / `_run_triage_once()`
  只剩定义、全仓无调用点 → 2.53.0 承诺的「启动时及每 6 小时纠正状态、给最近播放过的条目提权」
  在生产上**一次都不执行**。
- 维护者知情但只在测试里绕过：`tests/test_probe_worker_redesign.py` 有注释
  「PR #416 删除 preprobe 后，triage 可能未及时运行」，并显式调用 `probe_worker.triage(db)`。
- 已在 PR #425 接回 `_triage_loop()` / `_spawn_triage()` / `_restart_triage()`，注册为 `probe_triage`，
  间隔变量改为语义正确的 `PROBE_TRIAGE_INTERVAL_SEC`；回归测试改为断言调度已注册、
  且 `series` 条目无需手动干预即被标成 `skipped`。
- `PROBE_PREEXTRACT_INTERVAL_SEC` 是死变量（代码无任何读取点，`env.example` 仍在文档化），已随本 PR 清掉。

## 8. 另一处风险：镜像 tag 被反复覆盖

`VERSION` 长期停在 `2.48.0`，而 `publish-images.yml` 是「CI 全绿 + push 到 main 就发布」，
因此**每次合并 main 都会把 `ghcr.io/xzb177/aetrix-api:2.48.0` / `:latest` 覆盖成当时的 main**
（`gh run list --workflow=publish-images.yml` 最近 12 次全 success，其中多次是真构建）。
客户按 `DEPLOY.md` 的说明 pin `2.48.0` 拿到的并不是 2.48.0 的内容。PR #425 抬升版本号后，
下一次发布才会产生新 tag。


## 5. 要发布还差什么

1. 拍定目标版本号（代码/`env.example` 里的特性标签最高到 `v2.53.0`，跨度约 2.49–2.53）。
2. 抬升 `VERSION`，并同步两个前端 `package.json` + `package-lock.json` + `admin_frontend/src/composables/branding.ts` 的 `APP_VERSION`。
3. 定稿 `CHANGELOG`：7 段逐段成版、去重、补记 PR #411–#423 与 #416，并修正第 85 行关于预提取的描述。
4. 清掉 `PROBE_PREEXTRACT_INTERVAL_SEC` 的残留（env.example / docstring）。
5. 提 PR 合入 `main`，等 4 项必需检查全绿；绿了镜像自动发到 ghcr.io。
