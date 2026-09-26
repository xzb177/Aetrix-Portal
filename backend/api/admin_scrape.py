"""管理后台 · 元数据与刮削

TMDB API Key 后台填写（SystemConfig 落库，保存即热生效，无需重启）与
手动元数据刮削（条目级立即重刮 / 库级触发重新刮削扫描）。

前端入口在 EmbyAdmin.vue 的「元数据与刮削」分组（用户布局要求：与元数据 /
刮削设置放一起，不放在通用系统设置页）。路由挂在 admin_emby_router 上
（/api/admin/emby/scrape/*），成功写操作的审计由 emby_server/audit.py
中间件统一记录，本模块不再手写 _audit。
"""
from __future__ import annotations

import logging
import os
import posixpath
import threading
from dataclasses import replace
from datetime import datetime
from typing import Optional

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import models as base_models
from backend.database import SessionLocal, get_db
from backend.emby_server import models as em
from backend.emby_server import mounts as mount_lib
from backend.emby_server import nfo as nfo_lib
from backend.emby_server import nodes as node_lib
from backend.emby_server import auto_scan
from backend.emby_server import change_watcher
from backend.emby_server import scan_queue
from backend.emby_server.portal import admin_emby_router, require_staff
from backend.emby_server.tmdb import (
    TMDB_API,
    TMDB_KEYS_CONFIG_KEY,
    _env_keys,
    _split_keys,
    tmdb_client,
)
from backend.integrations import store

logger = logging.getLogger(__name__)


# ==================== TMDB API Keys ====================

class TmdbKeysSaveRequest(BaseModel):
    keys: str = Field(default="", description="多 key：逗号 / 换行 / 空白分隔")


class TmdbTestRequest(BaseModel):
    keys: str = Field(default="", description="为空则测当前生效的 key，否则测这批候选 key")


@admin_emby_router.get("/scrape/tmdb-keys")
def get_tmdb_keys(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """当前 TMDB Key 状态（只返回掩码与数量，不返回原文）"""
    return {
        "configured": tmdb_client.configured,
        "source": tmdb_client.key_source,  # env | db | none
        "count": len(tmdb_client.api_keys),
        "masked": tmdb_client.masked_keys(),
        "env_present": bool(_env_keys()),  # 环境变量有值时后台填写暂不生效
    }


@admin_emby_router.put("/scrape/tmdb-keys")
def save_tmdb_keys(
    req: TmdbKeysSaveRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """保存 TMDB API Keys：SystemConfig 落库后立即热生效，无需重启"""
    keys = _split_keys(req.keys)
    store.write_values(
        db,
        {TMDB_KEYS_CONFIG_KEY: ",".join(keys)},
        {TMDB_KEYS_CONFIG_KEY: "TMDB API Keys（元数据与刮削，多 key 逗号分隔）"},
    )
    db.commit()
    info = tmdb_client.refresh_keys(db)
    return {"success": True, "saved": len(keys), **info}


def _test_one_key(key: str) -> tuple[bool, str]:
    """测单个 key：调 TMDB /configuration（不记录原文）"""
    try:
        resp = httpx.get(f"{TMDB_API}/configuration", params={"api_key": key}, timeout=10)
    except Exception as e:  # noqa: BLE001 — 网络异常直接当测试失败
        return False, f"网络异常：{type(e).__name__}"
    if resp.status_code == 200:
        return True, "有效"
    if resp.status_code == 401:
        return False, "无效（401 未授权）"
    return False, f"HTTP {resp.status_code}"


@admin_emby_router.post("/scrape/tmdb-test")
def test_tmdb_keys(
    req: TmdbTestRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """测试连接：逐个 key 调 TMDB，只返回序号 / 掩码 / 有效性"""
    candidates = _split_keys(req.keys) or list(tmdb_client.api_keys)
    results = []
    for i, key in enumerate(candidates):
        ok, message = _test_one_key(key)
        results.append({
            "index": i + 1,
            "masked": f"****{key[-4:]}" if len(key) > 4 else "****",
            "ok": ok,
            "message": message,
        })
    return {"results": results}


# ==================== 条目级重刮 ====================

# 变更摘要里跟踪的字段（只读这些，不碰文件 / 播放相关字段）
_TRACKED_FIELDS = (
    "name", "original_title", "overview", "tagline", "production_year",
    "community_rating", "official_rating", "genres", "studios",
    "tmdb_id", "imdb_id", "aliases",
    "poster_path", "primary_image_url", "backdrop_path", "backdrop_image_url",
)


def _read_sibling_text(
    db: Session, file_path: Optional[str], candidates: list[str], parent_levels: int = 0
) -> Optional[str]:
    """读 file_path 同目录（或上 parent_levels 级目录）里的候选 NFO 文本。

    本机路径直接读文件；mount:// 路径经挂载 provider 读。读不到返回 None。
    """
    if not file_path or not candidates:
        return None
    parsed = mount_lib.parse_mount_path(file_path)
    if parsed:
        mount_id, rel = parsed
        try:
            provider = mount_lib.build_provider(mount_lib.load_mount(db, mount_id), db)
        except Exception:  # noqa: BLE001 — 挂载不可用就当没有 NFO
            return None
        d = posixpath.dirname(rel)
        for _ in range(parent_levels + 1):
            for cand in candidates:
                try:
                    return provider.read_text(posixpath.join(d, cand))
                except Exception:  # noqa: BLE001 — 单个候选读不到就试下一个
                    continue
            d = posixpath.dirname(d) or "/"
        return None
    d = os.path.dirname(file_path)
    for _ in range(parent_levels + 1):
        for cand in candidates:
            try:
                with open(os.path.join(d, cand), "r", encoding="utf-8-sig", errors="ignore") as f:
                    return f.read()
            except OSError:
                continue
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _discover_nfo(db: Session, item: em.MediaItem) -> Optional[dict]:
    """给条目找 NFO（电影/剧集优先；季/集按 NFO 能力处理）"""
    kind = item.item_type
    if kind == "movie":
        stem = posixpath.splitext(posixpath.basename(item.file_path or ""))[0]
        cands = [f"{stem}.nfo", "movie.nfo"] if stem else ["movie.nfo"]
        text = _read_sibling_text(db, item.file_path, cands)
    elif kind == "series":
        # 用第一集定位剧集目录：tvshow.nfo 在剧集目录（或季目录的父级）
        ep = (
            db.query(em.MediaItem)
            .filter(em.MediaItem.series_id == item.id, em.MediaItem.item_type == "episode")
            .first()
        )
        text = _read_sibling_text(db, ep.file_path if ep else None, ["tvshow.nfo"], parent_levels=1)
    elif kind == "episode":
        stem = posixpath.splitext(posixpath.basename(item.file_path or ""))[0]
        text = _read_sibling_text(db, item.file_path, [f"{stem}.nfo"] if stem else [])
    elif kind == "season":
        ep = (
            db.query(em.MediaItem)
            .filter(em.MediaItem.parent_id == item.id, em.MediaItem.item_type == "episode")
            .first()
        )
        text = _read_sibling_text(db, ep.file_path if ep else None, ["season.nfo"])
    else:
        return None
    return nfo_lib.parse_nfo(text) if text else None


def _rescrape_one(db: Session, item: em.MediaItem) -> dict:
    """条目级重刮：NFO 管文字（有则重读覆盖），TMDB 只补缺失项。幂等：重复调用结果一致。"""
    kind = item.item_type
    before = {k: getattr(item, k, None) for k in _TRACKED_FIELDS}
    notes: list[str] = []

    nfo_data = _discover_nfo(db, item)
    if nfo_data:
        nfo_lib.apply_nfo(item, nfo_data, kind)
        notes.append("已重读 NFO（文字以 NFO 为准）")
    else:
        notes.append("未找到 NFO")

    if kind in ("movie", "series"):
        if not tmdb_client.configured:
            notes.append("未配置 TMDB Key，跳过 TMDB")
        else:
            tmdb_id = (nfo_data or {}).get("tmdb_id") or item.tmdb_id
            if tmdb_id:
                # 有 TMDB ID：跳过搜索，只取详情补缺失的图 / IMDb / 别名
                details = tmdb_client.details(str(tmdb_id), kind)
                if details:
                    if not (item.imdb_id and item.aliases):
                        tmdb_client.apply_details(item, details)
                        notes.append("TMDB 补齐 IMDb/别名")
                    if not (item.poster_path or item.primary_image_url):
                        if tmdb_client.apply_images(item, details):
                            notes.append("TMDB 补图")
                else:
                    notes.append("TMDB 详情获取失败")
            else:
                # 无 TMDB ID：按名称 + 年份搜索后全量应用（手动触发才走这条路）
                hit = tmdb_client.search(item.name, item.production_year, kind)
                if hit:
                    tmdb_client.apply(item, hit, kind)
                    notes.append(f"TMDB 搜索命中：{hit.get('title') or hit.get('name')}")
                else:
                    notes.append("TMDB 未搜到匹配")
        item.last_scraped_at = datetime.now()

    changed = {
        k: str(getattr(item, k, "") or "")[:80]
        for k in _TRACKED_FIELDS
        if (before[k] or "") != (getattr(item, k, "") or "")
    }
    db.commit()
    return {"notes": notes, "changed": changed, "nfo_found": bool(nfo_data)}


@admin_emby_router.post("/scrape/items/{item_id}/rescrape")
def rescrape_item(
    item_id: int,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """条目级手动刮削：同步执行，电影/剧集优先，季/集按 NFO 能力处理"""
    item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    if item.item_type not in ("movie", "series", "episode", "season"):
        raise HTTPException(status_code=400, detail=f"不支持的条目类型：{item.item_type}")
    summary = _rescrape_one(db, item)
    return {
        "success": True,
        "item": {"id": item.id, "name": item.name, "item_type": item.item_type},
        "summary": summary,
    }


# ==================== 库级重刮 ====================

class LibraryRescrapeRequest(BaseModel):
    policy: str = Field(default="missing_only", description="missing_only | all")


def _run_library_rescrape(library_id: int, policy: str) -> None:
    """后台线程跑 scan_library_sync（与 scan_queue 工作线程同构：独立 Session）。

    不走 scan_queue.enqueue：policy 覆盖是本轮快照的一次性行为，不改库配置。
    """
    from backend.emby_server import scan_instrument
    from backend.emby_server.scanner import (
        LibrarySnapshot,
        ScanInProgress,
        normalize_scrape_policy,
        scan_library_sync,
    )

    db = SessionLocal()
    try:
        lib = db.query(em.Library).filter(em.Library.id == library_id).first()
        if not lib:
            logger.warning("重新刮削：媒体库 %s 不存在", library_id)
            return
        snap = LibrarySnapshot.of(lib)
        if policy == "all":
            snap = replace(snap, scrape_policy=normalize_scrape_policy("all"))
        scan_instrument.install()  # 幂等：进度上报点
        scan_library_sync(db, lib, snap, trigger="rescrape")
    except ScanInProgress:
        logger.info("重新刮削：媒体库 %s 正在扫描中，本次触发跳过", library_id)
    except Exception:  # noqa: BLE001 — 后台线程异常只记日志，不影响接口已返回
        logger.exception("重新刮削：媒体库 %s 失败", library_id)
    finally:
        db.close()


@admin_emby_router.post("/scrape/libraries/{library_id}/rescrape")
def rescrape_library(
    library_id: int,
    req: LibraryRescrapeRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """库级手动刮削：触发一次该库扫描，policy 只覆盖本轮快照，不改库配置"""
    lib = db.query(em.Library).filter(em.Library.id == library_id).first()
    if not lib:
        raise HTTPException(status_code=404, detail="媒体库不存在")
    policy = req.policy if req.policy in ("missing_only", "all") else "missing_only"
    owner = node_lib.library_owner(db, lib)
    if owner is not None and owner.id != node_lib.self_node_id(db):
        raise HTTPException(
            status_code=409,
            detail=f"该库归节点「{owner.name}」扫描，请在该节点面板操作",
        )
    if scan_queue.is_busy(library_id):
        return {
            "success": True,
            "started": False,
            "already": True,
            "message": "该媒体库正在扫描中，稍后再试",
        }
    threading.Thread(
        target=_run_library_rescrape,
        args=(library_id, policy),
        daemon=True,
        name=f"rescrape-lib-{library_id}",
    ).start()
    return {
        "success": True,
        "started": True,
        "library_id": library_id,
        "policy": policy,
        "message": f"已触发重新刮削（{policy}），后台运行中",
    }


# ==================== 定时扫描（用户可控的自动扫描计划） ====================

class AutoScanSaveRequest(BaseModel):
    enabled: bool = Field(default=False, description="总开关")
    time: str = Field(default="03:00", description="每天执行时间，HH:MM（24 小时制，服务器本地时间）")


class ChaseNewSaveRequest(BaseModel):
    enabled: bool = Field(default=False, description="追新总开关")
    interval: int = Field(default=10, description="轮询间隔（分钟），5-120")
    libraries: str = Field(default="", description="监听的库 ID，逗号分隔，空=全部启用库")


@admin_emby_router.get("/scrape/chase-new")
def get_chase_new(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """追新当前配置（开关 / 间隔 / 监听库 / 上次检查）"""
    return {"success": True, **change_watcher.get_config(db)}


@admin_emby_router.put("/scrape/chase-new")
def save_chase_new(
    req: ChaseNewSaveRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """保存追新配置：立即生效，无需重启"""
    cfg = change_watcher.save_config(db, req.enabled, req.interval, req.libraries)
    return {"success": True, **cfg}


@admin_emby_router.get("/scrape/auto-scan")
def get_auto_scan(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """定时扫描当前配置（开关 / 时间 / 上次执行日期）"""
    return {"success": True, **auto_scan.get_config(db)}


@admin_emby_router.get("/scrape/enrich-progress")
def get_enrich_progress(
    staff: base_models.WebUser = Depends(require_staff),
):
    """补全 worker 进度：enrich 待处理/进行中/成功/失败/重试中 + probe 队列 + 线程数"""
    from backend.emby_server import enrich_worker
    return {"success": True, **enrich_worker.get_progress()}


@admin_emby_router.get("/scrape/quota-breaker")
def get_quota_breaker(
    staff: base_models.WebUser = Depends(require_staff),
):
    """查询 403 熔断器状态：是否触发、连续 403 数、阈值、触发时间"""
    from backend.emby_server import probe_worker
    return {"success": True, **probe_worker.quota_breaker_status()}


@admin_emby_router.post("/scrape/quota-breaker/reset")
def reset_quota_breaker(
    staff: base_models.WebUser = Depends(require_staff),
):
    """手动重置 403 熔断器（配额恢复后调用，worker 恢复工作）"""
    from backend.emby_server import probe_worker
    probe_worker.quota_breaker_reset()
    return {"success": True, "message": "熔断器已重置，worker 恢复"}


@admin_emby_router.put("/scrape/auto-scan")
def save_auto_scan(
    req: AutoScanSaveRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """保存定时扫描配置：立即生效，无需重启；时间格式非法返回 400"""
    try:
        cfg = auto_scan.save_config(db, req.enabled, req.time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, **cfg}
