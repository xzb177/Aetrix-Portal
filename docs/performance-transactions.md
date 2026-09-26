# 事务范围：写事务里绝不出现 IO（v2.38.0）

`docs/performance.md` 讲的是「别让慢活儿占住事件循环」。这一篇讲的是另一件同样致命、
但方向相反的事：**别让慢活儿占住 SQLite 的写锁**。

## 一、线上现场

后台点一次媒体库**全量扫描**，然后：

- 日志里 2 分钟内 9 次 `sqlite3.OperationalError: database is locked`（持续中）；
- SQLite 的 WAL 文件长期 4.3MB 不 checkpoint；
- 前端 axios 30 秒超时（`timeout of 30000ms exceeded`）。

**WAL 与 `busy_timeout` 都没问题**（`backend/database.py` 里 30 秒是合理配置），
也不是索引或 SQL 写法的问题——是**事务范围**。SQLite 只有一个写者，写锁从第一次写一直握到
`COMMIT`；扫描器把网络 IO 夹在了这两个点之间：

| 位置（旧实现） | 夹在事务里的 IO |
| --- | --- |
| `scanner._scan_library_body` 外挂字幕段 | 先 `db.flush()` 写入，再 `scan_file.provider.list_dir()` 列远程目录、`find_external_subtitles*()` 找字幕，然后才随批次 `commit` |
| 同一函数的 TMDB 刮削段 | `search` / `enrich` / `refresh_images` 三次网络调用与 `apply()` 的 session 写交织在同一段未提交事务里 |
| 同一函数的探测段 | `_result(pending.probe)` 在写库循环里**等** ffprobe 子进程（第一个批次必然等到） |
| `maintenance.prune_scan_runs` | 先删孤儿行（写事务由此打开）→ 再逐库查询第 N 行之后 → 才提交 |
| `image_store.prune` | 读引用之后事务一直挂着，中间去删几万个磁盘文件 |

于是别的写请求（后台改设置、用户注册、卡码核销……）都排在一段「等 rclone 的写事务」后面，
一路等到 `busy_timeout`（30 秒）耗尽就报 `database is locked`；前端正好也是 30 秒超时，
表现成「点一下没反应，然后报错」。

## 二、改法：预取在事务外，事务只包纯 DB 写

| 位置 | 现在 |
| --- | --- |
| `scanner._prepare_and_prefetch` | 批次开头把这一批的 IO（ffprobe / 目录列举 / TMDB 搜索与详情）**全部提交并取回**，结果存成纯值挂在 `_Pending` 上（`probe_data` / `side_data` / `tmdb_hit` / `tmdb_details`） |
| `scanner._scan_library_body` | 写库循环只读纯值：探测读 `probe_data`、图片与字幕读 `side_data`、刮削用预取的 `tmdb_hit`；详情走新增的 `tmdb.apply_details` / `apply_images`（只套用已取回的数据，不发请求） |
| 详情预取口径 | 从「应该会用到」改成「**覆盖**写库那一步所有可能用到的分支」——少预取一次，写库那一步就会在事务里补一次网络请求 |
| `maintenance.prune_scan_runs` | 先把要删的 id 全查出来（此时还没有任何写），再一次性删 + 提交 |
| `image_store.prune` | 引用读完就结束读事务（`rollback`），之后再慢慢删磁盘文件 |

业务语义一个字没改：扫描结果、外挂字幕 `stream_index` 的合成规则、`Subtitles/{Index}` 的拼地址
逻辑都与升级前一致（`smoke_test_scan_budget.py` / `smoke_test_scan_incremental.py` /
`smoke_test_playback_chain.py` 逐条钉住）。

## 三、兜底：写锁退避重试（这不是解法，是兜底）

事务范围干净之后，还会有**别人**短暂占着写锁：另一台 EA / 另一个进程也在写同一个库、
运维手工 `sqlite3`、备份工具、`VACUUM` / WAL checkpoint 恰好和这次提交撞上。这类失败退避
几十毫秒再试就能成功，所以写路径统一走 `backend/db_retry.py`：

- `retry_write` / `commit_with_retry`：指数退避（0.25 → 0.5 → 1 秒），最多 3 次（含第一次）；
- **只对「写锁」这一类错误重试**（`database is locked` / `table is locked` / `schema is locked`），
  其它 `OperationalError`（磁盘满、库损坏、语法错）原样抛出；
- 重试到底仍失败才抛给上层——宁可这一次扫描 / 退款失败，也不能把错误吞掉假装成功。

重试的语义：这里重试的是一次**提交**。`COMMIT` 撞锁失败时事务还在、改动没丢，退避后重提是安全的；
而 `flush` 阶段的失败会把会话置成「需要回滚」，那类失败不在这里重试（调用方回滚后用同一批数据
重跑整段写，见 `scanner._iter_prepared`）。

已经换成它的写路径：扫描批次提交（`scanner._iter_prepared.commit_batch`）、扫描状态写回
（`_write_scan_state` / `_finish_scan_run` / `begin_scan`）、维护周期的几处清理、
卡码核销 / 注册落库 / 订单退款 / 人工补单。

## 四、顺带修掉的四个资金链路 bug

写锁问题之外，这一批一起收口的都是「两个请求同时进来会各成功一次」的读-改-写：

| 位置 | 病根 | 改法 |
| --- | --- | --- |
| `codes.redeem_code` / `consume` | 先读 `use_count` 判断可用、再 +1：并发提交同一张 `max_uses=1` 的卡码，两边都读到 0，各发一份会员天数 | 发奖前用条件 `UPDATE ... WHERE 仍可用` 原子占位（`codes.claim_code`），`rowcount=0` 直接拒绝 |
| `orders_admin.refund_order` | 状态检查 → 冲正积分 / 回滚会员天数（`_reverse_points` / `_rollback_subscription` **不是幂等**的）→ 写回 `refunded`：并发点两次退款，两边都读到 `paid`，各扣一次 | 条件 `UPDATE` 把 `paid` 原子推进到 `refunded`（与 `economy._claim_order` 同一写法），抢不到的那一边直接返回「已处理」 |
| `economy._fulfill_order` | 下单后、支付回调前套餐被删（或用户被删）：`if user and plan:` 不成立就什么都不做，订单却被标成 `paid`、优惠券照常 `consume`——用户什么都没拿到，还没有任何报错 | 抛 `FulfillmentError` → 回调回滚并返回 `fail`（网关会重试，或者转人工补单），订单保持未支付；后台「人工补单」遇到同样情况返回可读的 400 |
| `codes.grant_membership_days` / `consume` 内部提交 | 发奖一次提交、记消耗再一次提交：中间崩一次就是「码烧了、会员没到账」；注册流程顺序相反则可能「会员到了、码还能用」——两阶段提交不一致 | 去掉内部 `commit`，改为 `flush` 拿主键，由调用方**一个事务**提交（与 `economy._grant_subscription` 的无 commit 设计一致） |

## 五、怎么验证

```bash
# 扫描 × 写接口并发：写事务里零 IO（探针先自证有效）+ 并发写接口延迟，CI 会跑
python scripts/smoke_test_scan_write_concurrency.py

# 卡码并发核销 / 退款并发（同一张卡码、同一笔订单各只许成功一次）
python scripts/smoke_test_concurrency.py

# 履约缺料：套餐被删 / 用户被删必须 fail（不许静默 success）
python scripts/smoke_test_refunds.py

# 扫描本身没有退化（批次 / 并行 / 目录只列一次 / 清理仍然工作）
python scripts/smoke_test_scan_budget.py
python scripts/smoke_test_scan_incremental.py
```

### 扫描 × 写接口并发（`scripts/smoke_test_scan_write_concurrency.py`）

给扫描器真正会走的 IO 出口（`os.listdir` / ffprobe / TMDB 会话）装上探针，判据只有一条：
**这个 IO 有没有落在当前线程未提交的写事务里**。探针先自证有效（人为在写事务里做一次
同样的 IO，必须记到 1 次违规），再跑真实扫描；同时另一个线程循环打真实的写接口
`POST /api/admin/economy/plans`：

| 观测项 | 实测（132 个文件 / 多批次） | 旧形态 |
| --- | --- | --- |
| 写事务里发生的 IO | **0 次** | 每个文件的列目录 / 刮削 / 等待探测都算 |
| 扫描期间最长的一段写事务 | **约 150 ms** | 等于那一批的网络 IO 时长（远程挂载上直接超过 30 秒） |
| 并发写接口延迟（92~96 次请求） | 中位 **14 ms** / 最大 **0.18 s** | 排队到 `busy_timeout`，前端 30 秒超时 |
| `database is locked` 日志 | **0 条** | 2 分钟 9 次 |
| 写锁兜底重试 | **0 次** | — |

### 并发核销 / 并发退款（`scripts/smoke_test_concurrency.py`）

- 4 个线程同时核销同一张 `max_uses=1` 的注册码：只有 1 个成功，`use_count` 恰好 1、
  用满自动停用、会员天数只多发 30 天、`used_by` 只记一个账号；
- 用尽后再核销一次被拒，且不再发天数；
- 4 个线程同时退款同一笔已支付订单：只有 1 次真正冲正，其余返回「已处理」（不是 500），
  积分只扣回一次、冲正流水只记一笔。

### 履约缺料（`scripts/smoke_test_refunds.py` 第 7 节）

- 套餐在下单之后被删：回调返回 `fail`、订单保持 `pending`、不给用户发订阅、
  优惠券额度**没有**被 `consume`（还留在 `reserved`）；
- 用户在下单之后被删：同上；
- 后台「人工补单」遇到缺料返回 400 + 说明，而不是 500，也不会把订单标成已支付；
- 修好之后（套餐重建）回调恢复正常并真的发出订阅——这一条保证改动没有把正常路径挡掉。
