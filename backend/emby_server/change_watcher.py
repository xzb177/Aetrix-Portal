"""追新：检测挂载上的新资源，自动触发扫描 + 刮削

设计见 workspace/designs/chase-new.md v2

核心思路：
- 每 N 分钟（用户可配）检查一次
- local 类型挂载（含 rclone 挂载的 Drive/S3 等）：用文件 mtime 检测新增
- 发现新视频文件 → 整库入 scan_queue（trigger="chase-new"）
  → 扫描器增量秒跳，只处理新文件
- 新入库条目自动进 enrich 队列刮削（NFO→TMDB→豆瓣）

v1 范围：
- 本机目录：文件 mtime 检测（``find -newermt``）
- rclone RC 挂载：逐层列举 + ``ModTime`` 窗口过滤（走 ``mounts`` 公共通道）
- 115 直挂暂不直接检测（远端 API 不给可靠的 mtime），依赖每日定时扫描兜底

2026-10：远程检测曾绕过 ``mounts`` 的公共通道直接调 rclone RC，是一条无上限的
旁路（生产 24 小时 5.2 万条报错）。现在统一走 ``build_provider`` → ``list_dir``，
吃缓存 / 单飞 / 限流 / 退避 / 统计，并占用追新自己的小名额。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend import models as base_models
from backend.database import SessionLocal
from backend.emby_server import models as em
from backend.emby_server import mounts as mount_lib
from backend.emby_server import mount_rclone
from backend.emby_server import scan_queue

logger = logging.getLogger(__name__)

CONFIG_ENABLED = "chase_new_enabled"
CONFIG_INTERVAL = "chase_new_interval"
#: v2.45.0：**排除清单**（逗号分隔的库 id）。空 = 全部启用库都监听。
#:
#: 为什么从「包含清单」改成「排除清单」：包含清单空 = 全部，于是想关掉 A 库就必须先去
#: B 库打开开关、让清单被写出来，再回来把 A 删掉——反直觉且容易漏。现在直接往排除
#: 清单里加 A 就行，一次点击到位。
#:
#: 旧键 ``CONFIG_LIBRARIES``（包含清单）只在下述迁移里读一次：新键存在就以新键为准；
#: 新键不存在而旧键非空 = 老部署，把「启用库 − 包含清单」算成排除清单写进去。
#: 不这么做的话，老部署升级后会**静默变成监听全部库**（原来的「只听 A、B」变成全听），
#: 相当于一次扫描风暴。
CONFIG_EXCLUDED = "chase_new_excluded"
CONFIG_LIBRARIES = "chase_new_libraries"
CONFIG_LAST_CHECK = "chase_new_last_check"
CONFIG_LAST_FOUND = "chase_new_last_found"

DEFAULT_INTERVAL = 10  # 分钟
MIN_INTERVAL = 5
MAX_INTERVAL = 120

# 视频扩展名白名单
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".wmv", ".flv", ".mov", ".rmvb", ".mpg", ".mpeg", ".webm"}

# 追新在一个季目录里最多往下钻几层。rclone 的一次递归列举会把整个子树拍平返回，
# 国产剧 1.4 万个文件时生产实测要几分钟、远超任何合理超时。改成逐层走公共通道后
# 每一跳都是「一个小目录」，但仍需要上限：层数不封顶，遇到结构异常深的面粉盘
# 会变成无界遍历。3 层足够盖住「季目录 / 特别篇 / 压制组」这类真实结构。
CHASE_MAX_DEPTH = max(1, int(os.getenv("CHASE_MAX_DEPTH", "3") or 3))
# 单个季目录递归时最多收多少条目：卡住不是因为结构，而是有人往里塞了几万个文件。
CHASE_MAX_ENTRIES = max(100, int(os.getenv("CHASE_MAX_ENTRIES", "5000") or 5000))

_WATCHER_STARTED = False
_WATCHER_LOCK = threading.Lock()


def _get_config(db: Session, key: str, default: str = "") -> str:
    """统一读（只许这一套）：daemon 轮询走直查，永远最新"""
    from backend.integrations import store
    return store.read_value(db, key, default)


def _config_exists(db: Session, key: str) -> bool:
    """配置行是否已存在（区分「没配过」与「配了但值为空」）

    迁移靠它判断能不能走：新键存在 = 已经在新语义下，不必再看旧键。
    """
    row = db.query(base_models.SystemConfig).filter(
        base_models.SystemConfig.key == key).first()
    return row is not None


def _set_config(db: Session, key: str, value: str) -> None:
    row = db.query(base_models.SystemConfig).filter(base_models.SystemConfig.key == key).first()
    if row:
        row.value = value
    else:
        row = base_models.SystemConfig(key=key, value=value)
        db.add(row)
    db.commit()


def _parse_interval(raw: str) -> int:
    """解析轮询间隔，非法值按默认处理"""
    try:
        minutes = int(raw)
    except (ValueError, TypeError):
        logger.warning("[chase-new] 间隔配置非法 %r，按默认 %d 分钟", raw, DEFAULT_INTERVAL)
        return DEFAULT_INTERVAL
    if minutes < MIN_INTERVAL:
        logger.warning("[chase-new] 间隔 %d < 最小 %d，按最小处理", minutes, MIN_INTERVAL)
        return MIN_INTERVAL
    if minutes > MAX_INTERVAL:
        logger.warning("[chase-new] 间隔 %d > 最大 %d，按最大处理", minutes, MAX_INTERVAL)
        return MAX_INTERVAL
    return minutes


def _library_local_paths(library, db: Session) -> list[str]:
    """获取库的本机可读路径（local 类型挂载 + paths 里的本机目录）"""
    paths = []
    # paths 里的本机目录（非 mount:// 开头）
    for raw in (getattr(library, "paths", "") or "").split(","):
        p = raw.strip()
        if p and not p.startswith("mount://") and os.path.isdir(p):
            paths.append(p)
    # mount_ids 引用的 local 类型挂载
    # 注意：按 AGENTS.md 教训，paths 用 mount://子目录时 mount_ids 应为空
    # 这里只处理 mount_ids 指向的 local 挂载的根
    try:
        mount_ids = [int(x.strip()) for x in (getattr(library, "mount_ids", "") or "").split(",") if x.strip().isdigit()]
    except (ValueError, AttributeError):
        mount_ids = []
    if mount_ids:
        mounts = db.query(em.StorageMount).filter(em.StorageMount.id.in_(mount_ids)).all()
        for m in mounts:
            if getattr(m, "mount_type", "") == "local" and getattr(m, "is_enabled", False):
                mp = getattr(m, "mount_path", "") or getattr(m, "local_path", "")
                if mp and os.path.isdir(mp):
                    paths.append(mp)
    return paths


MOUNT_PATH_PREFIX = "mount://"


def _library_mount_sources(library, db: Session) -> list[tuple[int, str]]:
    """库里引用的远程挂载：返回 ``[(mount_id, 挂载内相对目录), ...]``

    追新必须覆盖**远程**媒体源。生产实测全部库都是 ``mount://3/MoviePilot/...``
    （rclone RC），只查本机目录的旧实现等于一个库都没看——线程在跑、
    last_check 在更新，却永远发现不了新资源。
    """
    sources: list[tuple[int, str]] = []
    raw_paths = [p.strip() for p in (getattr(library, "paths", "") or "").split(",") if p.strip()]
    for p in raw_paths:
        if not p.startswith(MOUNT_PATH_PREFIX):
            continue
        rest = p[len(MOUNT_PATH_PREFIX):]
        mid, _, rel = rest.partition("/")
        if not mid.isdigit():
            continue
        sources.append((int(mid), "/" + rel.lstrip("/")))
    return sources


def _chase_provider(mount, db: Session):
    """构造追新要用的提供者（只覆盖**能给出远端 modTime** 的远程挂载）

    返回 None 表示这个挂载追新管不了（cli 模式 / 本机目录 / 未启用 / 构造失败），
    调用方直接跳过。构造失败只记日志不抛：这个挂载坏了不该让整轮追新中断。

    判据是「条目带得上 ``mod_ts``」——追新全靠它做新增窗口过滤。所以：
    - rclone rc 模式：``/operations/list`` 的 ModTime（纳秒，由 parse_mod_ts 归一）；
    - gdrive 原生：Drive ``modifiedTime``（RFC3339）；
    - cli 模式靠子进程列目录、ModTime 口径不同，且追新不是它的主场景，仍然排除。
    """
    if not getattr(mount, "is_enabled", False):
        return None
    try:
        provider = mount_lib.build_provider(mount, db)
    except Exception as exc:  # noqa: BLE001 — 构造失败（含未知类型）= 跳过该挂载
        logger.warning("[chase-new] 挂载 %s 构造提供者失败: %s",
                       getattr(mount, "id", None), exc)
        return None
    kind = getattr(provider, "kind", "")
    if kind != "remote":
        return None                      # 本机目录由 find -newermt 那条路处理
    mode = getattr(provider, "mode", "")
    if mode and mode != mount_rclone.MODE_RC:
        return None                      # rclone cli 模式：ModTime 口径不同，排除
    return provider


def _mount_url(mount_id: int, rel: str) -> str:
    """挂载内相对路径 → ``mount://<id>/<rel>``"""
    return f"{MOUNT_PATH_PREFIX}{int(mount_id)}/{(rel or '').lstrip('/')}"


def _walk_files(provider, rel: str, max_depth: int, max_entries: int) -> list:
    """从 ``rel`` 往下逐层找视频文件（每一跳都走公共通道）

    旧实现是一次 ``recurse=True`` 把整个子树拍平拿回来（国产剧 1.4 万个文件要几分钟、
    超时）。这里改成**逐层列一层**：单次响应小、稳，而且每一跳都吃得到缓存、单飞锁、
    限流名额、熔断保护与统计——这正是这个修复要的东西。

    层数与条目数都有上限：没有上限的话，结构异常深或异常大的目录会变成无界遍历。
    """
    found: list = []
    seen_dirs: set[str] = set()
    current = ["/" + (rel or "").lstrip("/")]
    depth = 0
    while current and depth < max_depth and len(found) < max_entries:
        nxt: list[str] = []
        for one in current:
            try:
                entries = provider.list_dir(one)
            except Exception as exc:  # noqa: BLE001 — 单个目录失败不影响其它
                logger.warning("[chase-new] 列 %s 失败: %s", one, exc)
                continue
            for entry in entries:
                if len(found) >= max_entries:
                    break
                if entry.is_dir:
                    child = "/" + (entry.rel or "").lstrip("/")
                    if child not in seen_dirs:
                        seen_dirs.add(child)
                        nxt.append(child)
                    continue
                if os.path.splitext(entry.name)[1].lower() in VIDEO_EXTS:
                    found.append(entry)
        current = nxt
        depth += 1
    if len(found) >= max_entries:
        logger.warning("[chase-new] %s 递归达到条目上限 %d（可能有异常大的目录），已截断",
                       rel, max_entries)
    return found


def _find_new_videos_remote(db: Session, mount_id: int, rel_dir: str,
                            since_ts: float) -> list[str]:
    """远程挂载（rclone RC）按 ModTime 找新增视频

    直接对整库递归列举在生产是走不通的：国产剧 1.4 万个文件，rclone RC 要几分钟，
    超过任何合理超时，而且 11 个库串行跑一轮远超轮询间隔（每轮都超时）。

    改成**两级**：先只列顶层（一次请求、几百个目录，每个都带 ModTime），
    再对每个顶层目录列一层子目录（季级），只对「ModTime 落在窗口内」的季级
    子目录往下钻。实测顶层 402 个目录全部带 ModTime，正常情况下每轮只钻
    最近变动的少数几个季目录——成本从上万文件降到几十个。

    **不能在顶层按 mtime 过滤**：新出一集只改动 ``Season/`` 子目录的 mtime，
    顶层剧集目录的 mtime 不变（rclone/Drive 只更新直接父目录）。如果在顶层
    按 mtime 筛，"老剧出新集"（追新最主要的场景）会被漏掉。

    2026-10：这里以前直接调 ``rc_call``，是一条**无限流旁路**——绕开了缓存、限流、
    熔断与统计，生产 24 小时把 rclone 打出 5.2 万条报错。现在全部改走
    ``mounts`` 的公共通道（``build_provider`` → ``list_dir``），并用
    ``remote_io_purpose`` 把追新划到**自己的、更小的 RC 名额**上，不与扫描抢。
    """
    mount = db.query(em.StorageMount).filter(em.StorageMount.id == mount_id).first()
    if mount is None:
        return []
    provider = _chase_provider(mount, db)
    if provider is None:
        return []
    base = "/" + (rel_dir or "/").lstrip("/")

    with mount_lib.remote_io_purpose(mount_lib.PURPOSE_CHASE):
        try:
            top = provider.list_dir(base)
        except Exception as exc:  # noqa: BLE001 — 顶层列不出来就跳过该库，不拖垮整轮
            logger.warning("[chase-new] 列 %s 顶层失败: %s", base, exc)
            return []

        found: list[str] = []
        for it in top:
            if not it.is_dir:
                # 顶层散片
                if (os.path.splitext(it.name)[1].lower() in VIDEO_EXTS
                        and it.mod_ts > since_ts):
                    found.append(_mount_url(mount_id, it.rel))
                continue
            # 顶层目录（剧集）：不按 mtime 过滤，直接列第二级（季目录/散文件）
            try:
                subs = provider.list_dir(it.rel)
            except Exception as exc:  # noqa: BLE001 — 单个剧集目录失败不影响其它
                logger.warning("[chase-new] 列 %s 第二级失败: %s", it.rel, exc)
                continue
            for sub in subs:
                if not sub.is_dir:
                    # 剧集目录下直接放视频（无季目录结构）
                    if (os.path.splitext(sub.name)[1].lower() in VIDEO_EXTS
                            and sub.mod_ts > since_ts):
                        found.append(_mount_url(mount_id, sub.rel))
                    continue
                if sub.mod_ts <= since_ts:
                    continue
                # 季目录在窗口内变动：逐层往下钻（每一跳都受缓存/限流/熔断保护）
                for entry in _walk_files(provider, sub.rel, CHASE_MAX_DEPTH,
                                         CHASE_MAX_ENTRIES):
                    if entry.mod_ts <= since_ts:
                        continue
                    found.append(_mount_url(mount_id, entry.rel))
    return found


def _find_new_videos(paths: list[str], since_ts: float) -> list[str]:
    """找出 since_ts 之后新增/修改的视频文件（用 find -newermt，C 实现比 os.walk 快）"""
    import subprocess
    from datetime import datetime, timezone

    new_files = []
    since_str = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    # 构建 find 的扩展名过滤：\( -iname "*.mp4" -o -iname "*.mkv" ... \)
    ext_args = []
    for i, ext in enumerate(sorted(VIDEO_EXTS)):
        if i > 0:
            ext_args.append("-o")
        ext_args.extend(["-iname", f"*{ext}"])

    for base in paths:
        try:
            cmd = ["find", base, "-type", "f", "-newermt", since_str, "("] + ext_args + [")", "-print"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                new_files.extend(line for line in result.stdout.strip().split("\n") if line)
            elif result.returncode != 0:
                logger.warning("[chase-new] find %s 失败: %s", base, result.stderr[:200])
        except subprocess.TimeoutExpired:
            logger.warning("[chase-new] find %s 超时（60s），跳过", base)
        except Exception as e:
            logger.warning("[chase-new] find %s 异常: %s", base, e)
    return new_files


#: 库 id 的合理上限（SQLite/PG 的主键都是 64 位整数）。粘进来的超长数字串直接丢掉，
#: 不让它在配置里越攒越长
_MAX_LIBRARY_ID = 2 ** 63 - 1


def _parse_ids(raw) -> list[int]:
    """把 "1,2,  3" 这种字串解析成去重后的整数列表（脏值忽略，不报错）"""
    out: list[int] = []
    for part in str(raw or "").replace("，", ",").split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        value = int(part)
        if 0 < value <= _MAX_LIBRARY_ID and value not in out:
            out.append(value)
    return out


def _enabled_library_ids(db: Session) -> list[int]:
    return [row[0] for row in db.query(em.Library.id)
            .filter(em.Library.is_enabled == True).all()]


def resolve_excluded(db: Session) -> list[int]:
    """当前生效的**排除清单**（含旧包含清单的一次性迁移）

    迁移只做一次：新键写成功后旧键清空，之后就只认新键。
    """
    stored = _get_config(db, CONFIG_EXCLUDED, "")
    if _config_exists(db, CONFIG_EXCLUDED):
        return _parse_ids(stored)
    legacy = _get_config(db, CONFIG_LIBRARIES, "")
    if not _parse_ids(legacy):
        # 旧键也是空 = 本来就是「全部监听」，新语义一致，不用写
        return []
    included = set(_parse_ids(legacy))
    migrated = sorted(i for i in _enabled_library_ids(db) if i not in included)
    _set_config(db, CONFIG_EXCLUDED, ",".join(str(i) for i in migrated))
    _set_config(db, CONFIG_LIBRARIES, "")
    logger.info("[chase-new] 旧包含清单 %s 已迁移为排除清单 %s",
                legacy, ",".join(str(i) for i in migrated))
    return migrated


def _check_once() -> None:
    """执行一轮检查"""
    db = SessionLocal()
    try:
        enabled = _get_config(db, CONFIG_ENABLED, "0") == "1"
        if not enabled:
            return

        interval = _parse_interval(_get_config(db, CONFIG_INTERVAL, str(DEFAULT_INTERVAL)))
        # 用 2 倍间隔作为 mtime 阈值，防漏检
        since_ts = time.time() - (interval * 2 * 60)

        # 解析要监听的库：**排除清单里没有的**全部启用库都监听
        excluded = set(resolve_excluded(db))
        query = db.query(em.Library).filter(em.Library.is_enabled == True)
        libraries = [lib for lib in query.all() if lib.id not in excluded]

        total_found = 0
        for lib in libraries:
            try:
                found_paths = _find_new_videos(_library_local_paths(lib, db), since_ts)
                for mid, rel in _library_mount_sources(lib, db):
                    try:
                        found_paths += _find_new_videos_remote(db, mid, rel, since_ts)
                    except Exception as exc:  # noqa: BLE001 — 单个挂载失败不影响其它库
                        logger.warning("[chase-new] 库《%s》远程挂载 %s 检查失败: %s",
                                       getattr(lib, "name", lib.id), mid, exc)
                if found_paths:
                    total_found += len(found_paths)
                    logger.info("[chase-new] 库《%s》发现 %d 个新文件，触发扫描",
                                getattr(lib, "name", lib.id), len(found_paths))
                    scan_queue.enqueue(lib, trigger="chase-new")
            except Exception as e:
                logger.error("[chase-new] 库《%s》检查失败: %s", getattr(lib, "id", "?"), e)

        _set_config(db, CONFIG_LAST_CHECK, datetime.now(timezone.utc).isoformat())
        _set_config(db, CONFIG_LAST_FOUND, str(total_found))
        if total_found:
            logger.info("[chase-new] 本轮共发现 %d 个新文件", total_found)
    except Exception as e:
        logger.error("[chase-new] 轮询异常: %s", e)
    finally:
        db.close()


def _watcher_loop() -> None:
    """轮询线程主循环"""
    logger.info("[chase-new] 追新线程启动")
    while True:
        try:
            db = SessionLocal()
            try:
                enabled = _get_config(db, CONFIG_ENABLED, "0") == "1"
                interval = _parse_interval(_get_config(db, CONFIG_INTERVAL, str(DEFAULT_INTERVAL)))
            finally:
                db.close()
            if enabled:
                _check_once()
            # 每 60 秒检查一次开关，间隔到了才真正轮询
            # 简化：直接按间隔 sleep，开关变化最多延迟一个周期
            time.sleep(interval * 60)
        except Exception as e:
            logger.error("[chase-new] 线程异常: %s", e)
            time.sleep(60)


def get_config(db: Session) -> dict:
    """追新当前配置（管理后台展示）

    ``excluded`` 是排除清单（v2.45.0 起的唯一口径）；``libraries`` 保留为空串，
    因为老前端还在读它——给一个非空值会让老前端把排除清单当成包含清单用。
    """
    return {
        "enabled": _get_config(db, CONFIG_ENABLED, "0") == "1",
        "interval": _parse_interval(_get_config(db, CONFIG_INTERVAL, str(DEFAULT_INTERVAL))),
        "excluded": ",".join(str(i) for i in resolve_excluded(db)),
        "libraries": "",
        "last_check": _get_config(db, CONFIG_LAST_CHECK, ""),
        "last_found": int(_get_config(db, CONFIG_LAST_FOUND, "0") or "0"),
    }


def save_config(db: Session, enabled: bool, interval: int,
                excluded: str = "", libraries: Optional[str] = None) -> dict:
    """保存追新配置，立即生效

    ``excluded`` 是排除清单。``libraries`` 是**旧字段**（包含清单），只为老调用方保留：
    传了它就按老语义换算成排除清单（启用库 − 包含清单），而不是直接当排除清单存——
    否则一个还在用老前端的部署会把清单含义整个反过来。
    """
    minutes = _parse_interval(str(interval))
    _set_config(db, CONFIG_ENABLED, "1" if enabled else "0")
    _set_config(db, CONFIG_INTERVAL, str(minutes))
    if libraries is not None and not excluded:
        included = set(_parse_ids(libraries))
        ids = sorted(i for i in _enabled_library_ids(db) if i not in included)
    else:
        ids = _parse_ids(excluded)
    _set_config(db, CONFIG_EXCLUDED, ",".join(str(i) for i in ids))
    # 旧键清空：万一还有进程在按老口径读，它看到的是「空 = 全部监听」，
    # 与新语义下的“排除为空”一致，不会出现两边理解打架。
    _set_config(db, CONFIG_LIBRARIES, "")
    logger.info("[chase-new] 配置已保存: enabled=%s interval=%d excluded=%s",
                enabled, minutes, ",".join(str(i) for i in ids))
    return get_config(db)


def start_chase_new_watcher() -> None:
    """启动追新线程（幂等）"""
    global _WATCHER_STARTED
    with _WATCHER_LOCK:
        if _WATCHER_STARTED:
            return
        _WATCHER_STARTED = True
    t = threading.Thread(target=_watcher_loop, daemon=True, name="chase-new-watcher")
    t.start()
    logger.info("[chase-new] 已启动")
