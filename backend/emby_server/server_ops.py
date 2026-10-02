"""服务器维度的媒体运维：把「跑」这个动作从库上移到节点上

## 为什么要有这一层

按库配置（路径、刮削策略、挂载）是**配置**，本来就该一个库一份，放在「媒体库」页
逐个改没问题。但「跑」是**执行**：一个节点一次能并行扫几个库、哪些库在排队、
这台机器最近扫成功过没有、扫描流水里哪几轮失败了——这些问题**天然是按服务器问的**，
逐库去看等于把一台机器的运行状况拆成 N 份碎片。

所以这里只做两件事，边界很硬：

- **配置不动**：路径、策略、挂载仍然在「媒体库」页按库改，本模块只读；
- **执行上移**：一键扫描 / 转发、整服扫描历史、任务流水，都以「这台节点」为单位。

## 「整理 / 传输任务」在本项目里到底是什么

原需求里的「整理/传输任务」在别的产品里指文件转存与入库整理的队列。本项目
**没有**那一层，而且是有理由的没有：115 分享链接转存任务在 v2.18.0 被移除
（见 ``emby_server/transfer115`` 的模块说明），现在 115 是直挂（列目录、换直链）。
内容进库的流水线就是「扫描 → 入库 → 刮削补全 → 修复」，所以这里给的是这一条链上
真实存在的任务与流水，并**按来源标注清楚**：

- ``queue``：扫描队列（正在跑 / 排队 / 最近完成）——入库整理；
- ``pipeline``：刮削补全（enrich）与探测（probe）的条目分布 + 待修复队列；
- ``handoff``：求片批准后转交 MoviePilot / qBittorrent 的流水——内容转交下载与
  整理入库。**这一类是服级的**（外部服务全服共用，不由某台 EA 执行），字段里
  明写 ``scope``，面板不能把它说成「这台服务器在转存」。

## 边界

- 这里的每个数字都来自既有事实表（``ScanRun`` / ``MediaItem`` / ``MovieRequest`` /
  扫描队列），**不新建任何状态**；快照是纯读，问一次算一次。
- 读不到就说「读不到」：配置缺失、扫描由别的进程执行、挂载名对不上时，
  返回的说明字段（``notes`` / ``scope`` / ``view``）会写明，面板不需要猜。
- 阈值不做成配置项：只截断「一次最多入队多少库 / 流水最多回多少条」这类**响应体大小**
  的上限，超限就截断并把真实范围写进 ``notes``，绝不静默少做。
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, realms
from backend.emby_server import models as em
from backend.emby_server import mounts as mount_lib
from backend.emby_server import nodes as node_lib
from backend.emby_server import scan_queue, scanner

# 一次「整服扫描」最多入队多少个库、流水最多回多少条。
# 只影响「点一次推多少活 / 回包多大」，所以是模块常量而不是配置项：
# 真要调整宁可改这里，也不要把阈值散进前端。
MAX_SCAN_LIBS = 200
MAX_RUNS = 200
DEFAULT_RUNS = 40
DEFAULT_HANDOFF = 10
REPAIR_LIMIT = 20


# ==================== 范围：这台节点负责哪些库 ====================

def scope_libraries(db: Session, server, include_unassigned: bool = False
                    ) -> tuple[list, list]:
    """(本节点负责的库, 同服里还没分配给任何节点的库)

    「未分配」是一个真实存在的状态而不是错误：``Library.node_id`` 为空的库由面板
    自己扫（旧部署与「刚加完节点还没分配」的过渡期都是这样）。运维视图必须把它们
    与本节点的库分开说，否则会出现「面板说这台节点管 3 个库、其中 2 个其实不归它」。
    """
    realm_id = getattr(server, "realm_id", None)
    rows = (realms.scope_inclusive(db.query(em.Library), em.Library.realm_id, realm_id)
            .order_by(em.Library.id).all())
    assigned = [lib for lib in rows if getattr(lib, "node_id", None) == getattr(server, "id", None)]
    unassigned = [lib for lib in rows if not getattr(lib, "node_id", None)]
    return (assigned + unassigned if include_unassigned else assigned), unassigned


def _library_payload(lib) -> dict:
    """一个库在这台节点视角下的只读事实（配置项原样带出，面板只展示不改）"""
    live = scan_queue.live_payload(lib)
    paths = [p for p in (lib.paths or "").split(",") if p]
    return {
        "id": lib.id,
        "name": lib.name,
        "enabled": bool(lib.is_enabled),
        "virtual": bool(getattr(lib, "is_virtual", False)),
        "platform": lib.platform,
        "item_count": int(lib.item_count or 0),
        "paths": len(paths),
        "mount_ids": list(mount_lib.parse_mount_ids(lib)),
        "last_scan_at": lib.last_scan_at.isoformat() if lib.last_scan_at else None,
        "last_scan": scanner.scan_result_payload(lib),
        # live 有值 = 此刻在队列里 / 在扫（含「由归属节点在扫」这种 source=other）
        "live": live,
        "state": (live or {}).get("state") or "idle",
    }


# ==================== 任务：扫描队列 ====================

def _queue_payload(library_ids: set) -> dict:
    """扫描队列里属于这个范围的行（其余节点 / 未分配库的任务不混进来）"""
    snap = scan_queue.snapshot()
    scope = {int(i) for i in (library_ids or set())}

    def keep(task: dict) -> bool:
        return int(task.get("library_id") or 0) in scope

    running = [t for t in (snap.get("running") or []) if keep(t)]
    waiting = [t for t in (snap.get("waiting") or []) if keep(t)]
    history = [t for t in (snap.get("history") or []) if keep(t)]
    # 挂载名字只带这几个任务真的在等的那些：面板显示「在等挂载 X」时不必去
    # 存储来源页对号，也不必把全量挂载名塞进回包。
    needed = {int(m) for task in running + waiting for m in (task.get("waiting_for") or [])}
    names = {key: name for key, name in (snap.get("mount_names") or {}).items()
             if int(key) in needed}
    return {
        "view": snap.get("view"),
        "enabled": bool(snap.get("enabled")),
        "max_parallel": snap.get("max_parallel"),
        "mount_serial": bool(snap.get("mount_serial")),
        "running": running,
        "waiting": waiting,
        "history": history,
        "mount_names": names,
        "remote": snap.get("remote"),
    }


# ==================== 任务：刮削补全 / 探测 / 修复 ====================

def _pipeline_payload(db: Session, library_ids: Iterable[int]) -> dict:
    """这个范围内条目的补全 / 探测状态分布 + 待修复队列

    按库聚合而不是取全局计数：全局数字回答不了「是这台机器的哪批库卡住了」。
    """
    ids = [int(i) for i in (library_ids or [])]
    breakers = _breaker_rows(db)
    if not ids:
        return {
            "items": 0,
            "enrich": {},
            "probe": {},
            "repair": {"total": 0, "items": []},
            "mount_breakers": breakers,
            "note": "这个范围里还没有媒体库",
        }

    enrich_rows = (db.query(em.MediaItem.enrich_status, func.count(em.MediaItem.id))
                   .filter(em.MediaItem.library_id.in_(ids))
                   .group_by(em.MediaItem.enrich_status).all())
    probe_rows = (db.query(em.MediaItem.probe_status, func.count(em.MediaItem.id))
                  .filter(em.MediaItem.library_id.in_(ids))
                  .group_by(em.MediaItem.probe_status).all())
    repair_filter = (em.MediaItem.library_id.in_(ids),
                     em.MediaItem.repair_requested_at.isnot(None))
    repair_total = db.query(func.count(em.MediaItem.id)).filter(*repair_filter).scalar() or 0
    repair_rows = (db.query(em.MediaItem)
                   .filter(*repair_filter)
                   .order_by(em.MediaItem.repair_requested_at.desc())
                   .limit(REPAIR_LIMIT).all())

    return {
        "items": db.query(func.count(em.MediaItem.id))
                   .filter(em.MediaItem.library_id.in_(ids)).scalar() or 0,
        "enrich": {status or "unknown": int(count) for status, count in enrich_rows},
        "probe": {status or "unknown": int(count) for status, count in probe_rows},
        "repair": {
            "total": int(repair_total),
            "items": [{
                "id": row.guid,
                "name": row.name,
                "type": row.item_type,
                "library_id": row.library_id,
                "requested_at": row.repair_requested_at.isoformat() if row.repair_requested_at else None,
                "file_exists": bool(row.file_path and os.path.isfile(row.file_path)),
            } for row in repair_rows],
        },
        # 正在熔断的挂载：坏挂载会把这一台的扫描一起拖慢，属于节点级运维信息
        "mount_breakers": breakers,
    }


def _breaker_rows(db: Session) -> list:
    """正在熔断的挂载 + 挂载名

    熔断器快照里只有 ``mount_id``（它是进程内状态，不带名字）；运维页面上写
    「挂载 #7 正在熔断」没人能对号，所以在这里补一次名字查询。
    """
    open_list = mount_lib.mount_breaker_stats().get("open") or []
    ids = [int(row["mount_id"]) for row in open_list if row.get("mount_id") is not None]
    names = dict(db.query(em.StorageMount.id, em.StorageMount.name)
                 .filter(em.StorageMount.id.in_(ids)).all()) if ids else {}
    return [{**row, "mount_name": names.get(int(row.get("mount_id") or 0)) or ""}
            for row in open_list]


# ==================== 任务：内容转交（求片 → 外部下载整理） ====================

def _handoff_payload(db: Session, realm_id: Optional[int],
                     limit: int = DEFAULT_HANDOFF) -> dict:
    """求片批准后转交 MoviePilot / qBittorrent 的流水（**服级**，不是这台节点在跑）

    转交这一层由外部服务完成（它自己搜索、下载、整理入库），EA 不参与传输。
    所以这里明确带 ``scope: "realm"`` 与一句说明，避免面板把它写成
    「这台服务器在转存」这种不存在的因果。
    """
    if realm_id is None:
        return {
            "scope": "none",
            "total": 0,
            "items": [],
            "note": "这台服务器没有归属服，无法按服看内容转交",
        }
    base = (db.query(models.MovieRequest)
            .filter(models.MovieRequest.realm_id == realm_id,
                    models.MovieRequest.push_target.isnot(None),
                    models.MovieRequest.push_target != ""))
    rows = base.order_by(models.MovieRequest.id.desc()).limit(max(1, int(limit or 1))).all()
    total = base.count()
    return {
        "scope": "realm",
        "realm_id": realm_id,
        "total": int(total),
        "items": [{
            "id": row.id,
            "movie_name": row.movie_name,
            "type": row.type,
            "season": row.season,
            "status": row.status,
            "push_target": row.push_target,
            "push_status": row.push_status,
            "push_message": row.push_message,
            "pushed_at": row.pushed_at.isoformat() if row.pushed_at else None,
        } for row in rows],
        "note": "内容转交是服级的：MoviePilot / qBittorrent 自己找片、下载与整理入库，EA 只在扫描时入库",
    }


# ==================== 快照 ====================

def ops_snapshot(db: Session, server, *, include_unassigned: bool = False,
                 runs_limit: int = DEFAULT_RUNS) -> dict:
    """这台节点的媒体运维快照（纯读：一次组装，面板一页展示）"""
    targets, unassigned = scope_libraries(db, server, include_unassigned)
    ids = [lib.id for lib in targets]
    names = {lib.id: lib.name for lib in targets}

    limit = max(1, min(int(runs_limit or DEFAULT_RUNS), MAX_RUNS))
    runs = scanner.recent_scan_runs(db, ids, limit=limit)
    for run in runs:
        run["library_name"] = names.get(run.get("library_id"), "")

    enabled = [lib for lib in targets if lib.is_enabled and not getattr(lib, "is_virtual", False)]
    notes = _notes(server, targets, unassigned, enabled, include_unassigned, runs)

    return {
        "server_id": getattr(server, "id", None),
        "realm_id": getattr(server, "realm_id", None),
        "scope": {
            "include_unassigned": bool(include_unassigned),
            "libraries": len(targets),
            "enabled": len(enabled),
            "unassigned": len(unassigned),
            "runs_limit": limit,
            # 一键扫描最多会推多少个库（截断时 notes 里会说明，不会静默少做）
            "scan_cap": MAX_SCAN_LIBS,
        },
        "libraries": [_library_payload(lib) for lib in targets],
        "runs": runs,
        "queue": _queue_payload(set(ids)),
        "pipeline": _pipeline_payload(db, ids),
        "handoff": _handoff_payload(db, getattr(server, "realm_id", None)),
        "notes": notes,
    }


def _notes(server, targets, unassigned, enabled, include_unassigned: bool, runs) -> list:
    """把「这台视图意味着什么」写成人话：面板直接展示，不自己推断"""
    notes: list[str] = []
    if not targets:
        notes.append(
            "这个范围里还没有媒体库：去「媒体库」页把库分配给这台节点（或设为未分配、由面板扫描）"
        )
    if unassigned:
        notes.append(
            f"同服还有 {len(unassigned)} 个库没分配给任何节点：由面板扫描，不算在这台节点名下"
        )
    virtuals = len([lib for lib in targets if getattr(lib, "is_virtual", False)])
    if virtuals:
        notes.append(f"其中 {virtuals} 个是虚拟库：没有自己的目录，不参与扫描")
    if enabled:
        notes.append(f"一键扫描会把这 {len(enabled)} 个启用库推入扫描队列"
                     + (f"（上限 {MAX_SCAN_LIBS} 个）" if len(enabled) > MAX_SCAN_LIBS else ""))
    else:
        notes.append("没有可扫的启用库：先在「媒体库」页启用至少一个库")
    if not runs:
        notes.append("还没有扫描流水：这些库从没被扫过，或流水已被回收")
    if not getattr(server, "node_key", None):
        notes.append(
            "这台还没有登记 NODE_KEY：面板无法把媒体库分配给它（单台 EA 不影响，扫描仍由面板代跑）"
        )
    return notes


# ==================== 一键扫描（入队计划 + 本地入队） ====================

def scan_plan(db: Session, server, include_unassigned: bool = False) -> dict:
    """算清「这一键会扫哪些库」并把本地能跑的推入队列

    返回值里的三类互不重叠，面板照原样显示即可：

    - ``queued`` / ``already``：本地入队的（已在队列或正在扫的算 already，不重复推）；
    - ``forward``：归别的节点扫的库 —— **只计划不执行**，由路由层 await 转发
      （``nodes.push_scan`` 是网络调用，不能在同步函数里做）；
    - ``skipped``：停用 / 虚拟 / 超上限被跳过的，写明原因。
    """
    targets, _unassigned = scope_libraries(db, server, include_unassigned)
    self_id = node_lib.self_node_id(db)
    queued: list[dict] = []
    already: list[dict] = []
    forward: list[dict] = []
    skipped: list[dict] = []
    admitted = 0

    for lib in targets:
        entry = {"id": lib.id, "name": lib.name}
        if getattr(lib, "is_virtual", False):
            skipped.append({**entry, "reason": "虚拟库没有自己的目录"})
            continue
        if not lib.is_enabled:
            skipped.append({**entry, "reason": "已停用"})
            continue
        if admitted >= MAX_SCAN_LIBS:
            skipped.append({**entry, "reason": f"超过单次上限 {MAX_SCAN_LIBS} 个，本次未推"})
            continue
        admitted += 1
        owner = node_lib.library_owner(db, lib)
        if owner is not None and owner.id != self_id:
            forward.append({**entry, "node_id": owner.id, "node_name": owner.name, "url": owner.url})
            continue
        result = scan_queue.enqueue(lib, trigger="manual")
        task = result.get("task") or {}
        row = {**entry, "message": task.get("message") or ""}
        if result.get("created"):
            queued.append(row)
        else:
            already.append({**row, "state": task.get("state")})

    return {"queued": queued, "already": already, "forward": forward, "skipped": skipped}


__all__ = [
    "DEFAULT_HANDOFF",
    "DEFAULT_RUNS",
    "MAX_RUNS",
    "MAX_SCAN_LIBS",
    "ops_snapshot",
    "scan_plan",
    "scope_libraries",
]
