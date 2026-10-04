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
import time
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
    TMDB_API_DEFAULT,
    TMDB_IMAGE_DEFAULT,
    TMDB_API_BASE_CONFIG_KEY,
    TMDB_IMAGE_BASE_CONFIG_KEY,
    TMDB_KEY_COOLDOWN_CONFIG_KEY,
    TMDB_KEY_INVALID_COOLDOWN_CONFIG_KEY,
    TMDB_KEYS_CONFIG_KEY,
    _db_keys,
    _env_keys,
    _split_keys,
    invalidate_settings,
    prewarm_images,
    settings as tmdb_settings,
    tmdb_client,
    validate_base,
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
    """当前 TMDB Key 状态与限速（只返回掩码与数量，不返回原文）

    顺带给出**实际在打**的请求速率：配置里的 ENRICH_TMDB_PER_SEC 只是上限，
    撞 429 会自适应减半、连续成功后再慢慢加回来（见 tmdb._RequestLimiter）。
    """
    meta = tmdb_client.stats()
    cfg = tmdb_settings(db)
    return {
        "configured": tmdb_client.configured,
        "source": tmdb_client.key_source,  # env | db | none
        "count": len(tmdb_client.api_keys),
        "masked": tmdb_client.masked_keys(),
        "env_present": bool(_env_keys()),  # 环境变量有值时后台填写暂不生效
        "rate": meta["rate"],              # 实际请求/秒（自适应后）
        "rate_ceiling": meta["ceiling"],   # 配置上限
        "throttled": meta["throttled"],    # 进程内累计撞 429 次数
        # 密钥池逐把状态：哪把在用、哪把在冷却（还要 xx 秒）、为什么
        "pool": tmdb_client.key_pool(db),
        "keys_cooling": meta.get("keys_cooling", 0),
        # 镜像：空值 = 用官方地址，环境变量优先
        "api_base": cfg["api_base"],
        "image_base": cfg["image_base"],
        "api_base_default": TMDB_API_DEFAULT,
        "image_base_default": TMDB_IMAGE_DEFAULT,
        "api_base_from_env": cfg["api_base_from_env"],
        "image_base_from_env": cfg["image_base_from_env"],
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
    """测单个 key：调 TMDB /configuration（不记录原文）

    走**当前生效的镜像地址**：境内配了反代时，直连官方可能测不通，但反代本身是好的。
    """
    from backend.emby_server import tmdb as tmdb_mod

    try:
        resp = httpx.get(f"{tmdb_mod.api_base()}/configuration",
                         params={"api_key": key}, timeout=10)
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
    """一键测试全部密钥：逐个 key 调 TMDB，只返回序号 / 掩码 / 有效性

    测的是**当前生效的池**（除非传了 ``keys``）。测出 401 / 429 的 key 直接
    放进冷却：测都过不了的 key 没必要继续拿去打真实请求。
    """
    candidates = _split_keys(req.keys) or list(tmdb_client.api_keys)
    testing_pool = not req.keys
    results = []
    for i, key in enumerate(candidates):
        ok, message = _test_one_key(key)
        if testing_pool and key in tmdb_client.api_keys and not ok:
            if "401" in message:
                tmdb_client.note_key_invalid(key)
            else:
                tmdb_client.note_key_throttled(key)
        results.append({
            "index": i + 1,
            "masked": f"****{key[-4:]}" if len(key) > 4 else "****",
            "ok": ok,
            "message": message,
        })
    return {"results": results, "pool": tmdb_client.key_pool(db)}


class TmdbKeyAddRequest(BaseModel):
    key: str = Field(..., min_length=8, max_length=200, description="一把新的 TMDB API Key")


def _save_pool(db: Session, keys: list[str]) -> int:
    """把密钥池写回 SystemConfig 并热生效（返回写入数量）"""
    count = store.write_values(
        db,
        {TMDB_KEYS_CONFIG_KEY: ",".join(keys)},
        {TMDB_KEYS_CONFIG_KEY: "TMDB API Keys（元数据来源，多 key 逗号分隔）"},
    )
    db.commit()
    tmdb_client.refresh_keys(db)
    return count


@admin_emby_router.post("/scrape/tmdb-keys/add")
def add_tmdb_key(
    req: TmdbKeyAddRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """逐把增：往密钥池里追加一把（去重，不覆盖已有）

    环境变量里有 key 时（``TMDB_API_KEYS``）写入仍然成功，但**不会生效**——
    返回里的 ``effective=false`` 就是给界面提示用的，与密钥来源优先级一致。
    """
    key = req.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="密钥不能为空")
    existing = _db_keys(db)
    if key in existing:
        raise HTTPException(status_code=409, detail="这把密钥已经在池子里了")
    _save_pool(db, existing + [key])
    info = tmdb_client.refresh_keys(db)
    return {
        "success": True,
        "count": len(tmdb_client.api_keys),
        "masked": tmdb_client.masked_keys(),
        "effective": tmdb_client.key_source == "db",
        "note": "" if tmdb_client.key_source == "db"
                else "环境变量 TMDB_API_KEYS 优先，后台添加的这把暂不生效",
        **info,
    }


@admin_emby_router.delete("/scrape/tmdb-keys/{index}")
def delete_tmdb_key(
    index: int,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """逐把删：按**序号**（从 1 开始，与界面展示一致）删掉一把"""
    keys = _db_keys(db)
    if index < 1 or index > len(keys):
        raise HTTPException(
            status_code=400,
            detail=f"序号超出范围：密钥池里只有 {len(keys)} 把（删的是后台填写的那部分）",
        )
    removed = keys.pop(index - 1)
    _save_pool(db, keys)
    return {
        "success": True,
        "removed": f"****{removed[-4:]}" if len(removed) > 4 else "****",
        "count": len(tmdb_client.api_keys),
        "masked": tmdb_client.masked_keys(),
    }


@admin_emby_router.post("/scrape/tmdb-keys/cooldown/reset")
def reset_tmdb_key_cooldown(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """清除全部密钥的冷却（换完 key / 网络恢复后手动重来一次）"""
    cleared = tmdb_client.clear_cooldowns()
    return {"success": True, "cleared": cleared, "pool": tmdb_client.key_pool(db)}


class TmdbMirrorRequest(BaseModel):
    api_base: str = Field(default="", description="API 镜像/反代地址（留空 = 官方）")
    image_base: str = Field(default="", description="图片 CDN 镜像地址（留空 = 官方）")


@admin_emby_router.put("/scrape/tmdb-mirror")
def save_tmdb_mirror(
    req: TmdbMirrorRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """保存 TMDB 镜像地址（API 与图片分开；保存即热生效）

    空值 = 回到官方地址；写进 SystemConfig，跨进程靠短 TTL 兜底。
    """
    try:
        api = validate_base(req.api_base, "API 镜像地址")
        image = validate_base(req.image_base, "图片 CDN 镜像地址")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.write_values(
        db,
        {TMDB_API_BASE_CONFIG_KEY: api, TMDB_IMAGE_BASE_CONFIG_KEY: image},
        {
            TMDB_API_BASE_CONFIG_KEY: "TMDB API 镜像/反代地址（留空 = 官方地址）",
            TMDB_IMAGE_BASE_CONFIG_KEY: "TMDB 图片 CDN 镜像地址（留空 = 官方地址）",
        },
    )
    db.commit()
    invalidate_settings()
    cfg = tmdb_settings(db, refresh=True)
    return {
        "success": True,
        "api_base": cfg["api_base"],
        "image_base": cfg["image_base"],
        "defaults": {"api_base": TMDB_API_DEFAULT, "image_base": TMDB_IMAGE_DEFAULT},
    }


@admin_emby_router.get("/scrape/tmdb-mirror")
def get_tmdb_mirror(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """当前生效的镜像地址 + 官方默认值（界面上的“恢复默认”要比对得出差异）"""
    cfg = tmdb_settings(db, refresh=True)
    return {
        "api_base": cfg["api_base"],
        "image_base": cfg["image_base"],
        "api_base_from_env": cfg["api_base_from_env"],
        "image_base_from_env": cfg["image_base_from_env"],
        "defaults": {"api_base": TMDB_API_DEFAULT, "image_base": TMDB_IMAGE_DEFAULT},
        "cooldown_sec": cfg["cooldown_sec"],
        "invalid_cooldown_sec": cfg["invalid_cooldown_sec"],
        "cooldown_config_keys": [TMDB_KEY_COOLDOWN_CONFIG_KEY, TMDB_KEY_INVALID_COOLDOWN_CONFIG_KEY],
    }


# ==================== 条目级重刮 ====================

# 变更摘要里跟踪的字段（只读这些，不碰文件 / 播放相关字段）
_TRACKED_FIELDS = (
    "name", "original_title", "overview", "tagline", "production_year",
    "community_rating", "official_rating", "genres", "studios",
    "tmdb_id", "imdb_id", "aliases", "external_ids",
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


def _rescrape_multisource(db: Session, item: em.MediaItem, kind: str) -> list[str]:
    """手动重刮里的多源环节：总开关关着时返回空列表（行为与升级前一致）"""
    from backend.emby_server.metasources import config as ms_config
    from backend.emby_server.metasources import engine as ms_engine
    from backend.emby_server.metasources import sources as ms_sources

    snapshot = ms_config.read_config(db, ms_sources.SPECS)
    if not snapshot.enabled:
        return []
    try:
        collected = ms_engine.collect(db, item.name or "", item.production_year, kind)
    except Exception as exc:  # noqa: BLE001 — 多源失败不影响已经完成的 TMDB 部分
        logger.warning("多源采集失败 %s: %s", item.name, exc)
        return [f"多源采集失败：{exc}"]
    if not collected.fields:
        return ["多源未命中任何可用数据"]
    prewarm_images(extra=[collected.fields.get("poster")])
    changed = ms_engine.apply_to_item(item, collected, fill_missing_only=False)
    hits = [o.source for o in collected.outcomes if o.hit]
    notes = [f"多源命中：{'、'.join(hits) if hits else '无'}（标题取自 {collected.primary}）"]
    if changed:
        notes.append("多源补齐：" + "、".join(changed))
    failed = [f"{o.source}（{o.error}）" for o in collected.outcomes if not o.ok and o.error]
    if failed:
        notes.append("失败已隔离：" + "；".join(failed))
    return notes


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
            # TMDB 压根没配密钥时，多源（如果开了）就是唯一能拿到东西的路
            notes.extend(_rescrape_multisource(db, item, kind))
        else:
            tmdb_id = (nfo_data or {}).get("tmdb_id") or item.tmdb_id
            if tmdb_id:
                # 有 TMDB ID：跳过搜索，只取详情补缺失的图 / IMDb / 别名
                details = tmdb_client.details(str(tmdb_id), kind)
                if details:
                    # 图先落盘再落字段：写事务里 _set_image 不再发 HTTP（v2.42.9）
                    prewarm_images(details)
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
                    prewarm_images(hit)
                    tmdb_client.apply(item, hit, kind)
                    notes.append(f"TMDB 搜索命中：{hit.get('title') or hit.get('name')}")
                else:
                    notes.append("TMDB 未搜到匹配")
                    # Phase 6b：TMDB 没搜到时，多源总开关开着就把剩下几个源跑一遍
                    #（手动重刮本来就是「用户主动要求认真刮」，不跳多源）
                    notes.extend(_rescrape_multisource(db, item, kind))
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


# ==================== 多源元数据（Phase 6b） ====================

class MetaSourcesSaveRequest(BaseModel):
    enabled: bool = Field(default=False, description="多源补全总开关")
    prefer_chinese: bool = Field(default=True, description="中文信息优先")
    order: list[str] = Field(default_factory=list, description="源顺序（源 id 数组）")
    toggles: dict[str, bool] = Field(default_factory=dict, description="逐源开关")
    rates: dict[str, float] = Field(default_factory=dict, description="逐源请求间隔（秒）")


class MetaSourceProbeRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="要试的片名")
    year: Optional[int] = Field(default=None, ge=1800, le=2200)
    kind: str = Field(default="series", description="series | movie")
    source: str = Field(default="", description="只试这一个源（留空 = 按顺序全试）")


def _meta_sources_view(db: Session, snapshot=None) -> dict:
    """把配置快照 + 运行时状态拼成一份界面直接可用的视图

    **密钥原文不出这个函数**：每把只给掩码、冷却剩余秒数与原因。
    """
    from backend.emby_server.metasources import config as ms_config
    from backend.emby_server.metasources import keypool as ms_keypool
    from backend.emby_server.metasources import sources as ms_sources

    snapshot = snapshot if snapshot is not None else ms_config.read_config(db, ms_sources.SPECS)
    order = [s.id for s in snapshot.sources]
    rows = []
    for position, source_cfg in enumerate(snapshot.sources, start=1):
        spec = ms_sources.SPEC_BY_ID.get(source_cfg.id)
        if source_cfg.id == "tmdb":
            # TMDB 的密钥池归 Phase 6a 的 TmdbClient 管（单一入口）。
            # 这里直接读它的快照，**不再建第二个池**——两处冷却状态各说各话，
            # 管理员会以为同一把钥匙在两个地方表现不一样。
            key_rows = tmdb_client.key_pool(db)
            cooling = len([r for r in key_rows if r.get("cooling")])
        else:
            pool = ms_keypool.pool_for(source_cfg.id, source_cfg.keys)
            key_rows = pool.status()
            cooling = pool.cooling_count()
        rows.append({
            "id": source_cfg.id,
            "label": source_cfg.label,
            "note": spec.note if spec else "",
            "position": position,
            "enabled": source_cfg.enabled,
            "requires_key": source_cfg.requires_key,
            "lang": source_cfg.lang,
            "rate": source_cfg.rate,
            "key_count": len(source_cfg.keys),
            "keys": key_rows,
            "cooling": cooling,
            # 「不参与」的两种原因分别说清楚：手动关掉 vs 缺密钥
            "skipped_reason": ("已在后台关闭" if not source_cfg.enabled
                               else ("需要密钥但一个都没配" if source_cfg.needs_key else "")),
            # key 去哪申请（界面直接给链接与说明，不用去搜索引擎里找）
            "apply_url": spec.apply_url if spec else "",
            "apply_hint": spec.apply_hint if spec else "",
            # 密钥存在哪个配置键：界面据此告诉用户「去哪填」
            "key_storage": source_cfg.key_storage or (spec.key_storage if spec else ""),
            # true = 已废弃的旧键里还有残留（启动自愈会合并，界面提醒看一眼）
            "keys_legacy": source_cfg.keys_legacy,
            # TMDB 的密钥池在 6a 那张卡片里（单一入口），这里不再重复给输入框
            "key_entry": "pool_card" if source_cfg.id == "tmdb" else "inline",
        })
    return {
        "enabled": snapshot.enabled,
        "prefer_chinese": snapshot.prefer_chinese,
        "order": order,
        "sources": rows,
        "default_order": list(ms_config.DEFAULT_ORDER),
        "max_sources": ms_config.MAX_SOURCES,
        "collect_timeout_sec": ms_config.COLLECT_TIMEOUT_SEC,
        "active_count": len([r for r in rows if r["enabled"] and not r["skipped_reason"]]),
    }


@admin_emby_router.get("/scrape/meta-sources")
def get_meta_sources(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """多源配置 + 逐源运行时状态（密钥只给掩码）"""
    return _meta_sources_view(db)


@admin_emby_router.put("/scrape/meta-sources")
def save_meta_sources(
    req: MetaSourcesSaveRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """保存总开关 / 中文优先 / 顺序 / 逐源开关 / 逐源限速（**不动密钥池**）"""
    from backend.emby_server.metasources import config as ms_config
    from backend.emby_server.metasources import sources as ms_sources

    known = {spec.id for spec in ms_sources.SPECS}
    order = [sid for sid in (req.order or []) if sid in known]
    # 顺序里没提到的源追加到末尾（前端漏发不丢源）；重复的丢弃
    order += [sid for sid in ms_config.DEFAULT_ORDER if sid in known and sid not in order]
    toggles = {sid: bool(on) for sid, on in (req.toggles or {}).items() if sid in known}
    rates = {sid: rate for sid, rate in (req.rates or {}).items() if sid in known}
    ms_config.write_config(
        db, enabled=bool(req.enabled), prefer_chinese=bool(req.prefer_chinese),
        order=order, toggles=toggles, rates=rates)
    return _meta_sources_view(db)


class MetaSourceKeyAddRequest(BaseModel):
    key: str = Field(..., min_length=6, max_length=200, description="一把新的密钥")


@admin_emby_router.post("/scrape/meta-sources/{source_id}/keys")
def add_meta_source_key(
    source_id: str,
    req: MetaSourceKeyAddRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """逐源逐把增：追加一把密钥（去重，不覆盖已有）"""
    from backend.emby_server.metasources import config as ms_config
    from backend.emby_server.metasources import sources as ms_sources

    if source_id not in ms_sources.SPEC_BY_ID:
        raise HTTPException(status_code=404, detail=f"未知的数据源：{source_id}")
    key = req.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="密钥不能为空")
    snapshot = ms_config.read_config(db, ms_sources.SPECS)
    existing = list((snapshot.by_id(source_id).keys if snapshot.by_id(source_id) else []))
    if key in existing:
        raise HTTPException(status_code=409, detail="这把密钥已经在池子里了")
    ms_config.write_config(db, enabled=snapshot.enabled,
                            prefer_chinese=snapshot.prefer_chinese,
                            order=[s.id for s in snapshot.sources],
                            toggles={s.id: s.enabled for s in snapshot.sources},
                            rates={s.id: s.rate for s in snapshot.sources},
                            keys={source_id: existing + [key]})
    return _meta_sources_view(db)


@admin_emby_router.delete("/scrape/meta-sources/{source_id}/keys/{index}")
def delete_meta_source_key(
    source_id: str,
    index: int,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """逐源逐把删：按**序号**（从 1 开始，与界面展示一致）删一把"""
    from backend.emby_server.metasources import config as ms_config
    from backend.emby_server.metasources import sources as ms_sources

    if source_id not in ms_sources.SPEC_BY_ID:
        raise HTTPException(status_code=404, detail=f"未知的数据源：{source_id}")
    snapshot = ms_config.read_config(db, ms_sources.SPECS)
    source_cfg = snapshot.by_id(source_id)
    if source_cfg is None:
        raise HTTPException(status_code=404, detail=f"未知的数据源：{source_id}")
    if index < 1 or index > len(source_cfg.keys):
        raise HTTPException(
            status_code=400,
            detail=f"序号超出范围：「{source_cfg.label}」的池子里只有 {len(source_cfg.keys)} 把",
        )
    remaining = [k for i, k in enumerate(source_cfg.keys, start=1) if i != index]
    ms_config.write_config(db, enabled=snapshot.enabled,
                            prefer_chinese=snapshot.prefer_chinese,
                            order=[s.id for s in snapshot.sources],
                            toggles={s.id: s.enabled for s in snapshot.sources},
                            rates={s.id: s.rate for s in snapshot.sources},
                            keys={source_id: remaining})
    return _meta_sources_view(db)


@admin_emby_router.post("/scrape/meta-sources/{source_id}/keys/reset")
def reset_meta_source_cooldown(
    source_id: str,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """清除某个源全部密钥的冷却（换完密钥 / 网络恢复后手动重来一次）"""
    from backend.emby_server.metasources import config as ms_config
    from backend.emby_server.metasources import keypool as ms_keypool
    from backend.emby_server.metasources import sources as ms_sources

    if source_id not in ms_sources.SPEC_BY_ID:
        raise HTTPException(status_code=404, detail=f"未知的数据源：{source_id}")
    snapshot = ms_config.read_config(db, ms_sources.SPECS)
    source_cfg = snapshot.by_id(source_id)
    keys = list(source_cfg.keys) if source_cfg else []
    cleared = ms_keypool.pool_for(source_id, keys).clear()
    return {"success": True, "cleared": cleared, "config": _meta_sources_view(db)}


@admin_emby_router.post("/scrape/meta-sources/test")
def probe_meta_sources(
    req: MetaSourceProbeRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """试采集：用一个片名跑一遍，**不改任何数据**，返回逐源命中与合并后的字段

    这是配置页最有用的一把尺子：开一个源之前先看它到底能不能搜到这部片。
    ``source`` 指定时只问那一个源（用来单独排查“是不是这个站在抽风”）。
    """
    from backend.emby_server.metasources import config as ms_config
    from backend.emby_server.metasources import engine as ms_engine
    from backend.emby_server.metasources import sources as ms_sources

    kind = "movie" if req.kind == "movie" else "series"
    if req.source and req.source not in ms_sources.SPEC_BY_ID:
        raise HTTPException(status_code=404, detail=f"未知的数据源：{req.source}")
    # 试采集要能测「被关掉的源」，所以不走过滤后的 ordered()
    result = ms_engine.collect(db, req.title.strip(), req.year, kind,
                               only=req.source or None, ignore_switch=True)
    snapshot = ms_config.read_config(db, ms_sources.SPECS)
    view = _meta_sources_view(db, snapshot)
    return {
        "success": True,
        "switch_on": snapshot.enabled,
        "probe": result.as_dict(),
        "note": "" if snapshot.enabled
                else "总开关现在是关的，这次是临时试采集（不会真的落库）",
        "sources": view["sources"],
    }


# 只有这些词出现时，才算「密钥自己的问题」。
# 写成一组词而不是逐个源判断，是因为各站的报错文案不一致（OMDb 说 Error: Invalid API key!，
# TheTVDB 说 token 过期，TMDB 直接回 401），而**网络类失败**长得很像（超时 / 拒绝连接 /
# 429 / 403），绝不能误伤——那会把好密钥白白晾起来。
_KEY_FAULT_WORDS = ("401", "403 认证", "密钥无效", "无效密钥", "api key", "apikey",
                    "invalid", "token", "unauthorized", "配额", "quota")


def _is_key_fault(message: str) -> bool:
    text = str(message or "").lower()
    return any(word in text for word in _KEY_FAULT_WORDS)


@admin_emby_router.post("/scrape/meta-sources/{source_id}/test")
def test_meta_source_keys(
    source_id: str,
    req: MetaSourceProbeRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """一键测试某个源的密钥：逐把试一遍，测不通的直接进冷却

    与 TMDB 那套同一口径：测都过不了的密钥没必要继续拿去打真实请求。
    测不出来（非密钥类失败，如网络）**不进冷却**——那不是密钥的锅。
    """
    from backend.emby_server.metasources import config as ms_config
    from backend.emby_server.metasources import keypool as ms_keypool
    from backend.emby_server.metasources import sources as ms_sources

    spec = ms_sources.SPEC_BY_ID.get(source_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"未知的数据源：{source_id}")
    snapshot = ms_config.read_config(db, ms_sources.SPECS)
    source_cfg = snapshot.by_id(source_id)
    keys = list(source_cfg.keys) if source_cfg else []
    if not keys:
        raise HTTPException(status_code=400, detail=f"「{spec.label}」还没有配置密钥")
    pool = ms_keypool.pool_for(source_id, keys)
    kind = "movie" if req.kind == "movie" else "series"
    results = []
    for index, key in enumerate(keys, start=1):
        probe_pool = ms_keypool.KeyPool(source_id, [key])
        gate = ms_keypool.RateGate(source_id, 0.0)   # 测试不等限速
        began = time.monotonic()
        try:
            hit = spec.search(req.title.strip(), req.year, kind,
                              pool=probe_pool, gate=gate)
        except ms_sources.SourceError as exc:
            message = str(exc)
            # 只冷却**密钥自己的锅**（401 / 无效 / token 过期 / 配额耗尽）。
            # 网络超时、限流、反爬一律不冷却：那不是这把密钥的问题，
            # 把它晾起来只会在管理员网络恢复后平白少一把能用的密钥。
            if _is_key_fault(message):
                pool.note_invalid(key)
                message = f"{message}（已冷却，不再使用这把）"
            results.append({"index": index, "masked": ms_keypool.mask(key),
                            "ok": False, "message": message[:140]})
            continue
        results.append({
            "index": index, "masked": ms_keypool.mask(key), "ok": True,
            "hit": hit is not None,
            "message": (f"可用，搜到「{hit.title}」" if hit else "可用，但这片没搜到"),
            "elapsed_ms": int((time.monotonic() - began) * 1000),
        })
    return {"results": results, "config": _meta_sources_view(db)}


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
    excluded: str = Field(default="",
                          description="**排除**监听的库 ID，逗号分隔，空 = 全部启用库都监听")
    # 旧字段（包含清单）：只为还在用老前端的部署保留，后端会换算成排除清单
    libraries: Optional[str] = Field(
        default=None, description="已废弃：旧版包含清单（空 = 全部监听）")


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
    cfg = change_watcher.save_config(db, req.enabled, req.interval,
                                   excluded=req.excluded, libraries=req.libraries)
    return {"success": True, **cfg}


@admin_emby_router.get("/scrape/auto-scan")
def get_auto_scan(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """定时扫描当前配置（开关 / 时间 / 上次执行日期）"""
    return {"success": True, **auto_scan.get_config(db)}


@admin_emby_router.post("/scrape/enrich/retry-unmatched")
def retry_unmatched_items(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """重试未匹配项（处方 5）：把「搜过、没有」终态条目捞回队列重新补搜。

    TMDB 每天新增条目、本地别名（Tier 1.5）也在变好——终态化不等于永久放弃。
    捞回的条目置 enrich_priority=50（repair 之下、默认之上），排在队首。
    """
    from backend.emby_server import enrich_worker
    n = enrich_worker.retry_unmatched(db)
    return {"success": True, "requeued": n}


@admin_emby_router.post("/scrape/probe/retry-failed")
def retry_failed_probes(
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
    limit: int = 5000,
    statuses: str = "",
):
    """重试被标成 failed 的探测条目（v2.42.14 配套）。

    修正分类只阻止**新增**失败；存量行（比如那 2.6 万条「ffprobe 跑完但没时长」
    被误判失败的）要靠这个把它们拉回队列。它们重新探测后大多会落到
    ``probed_no_duration``——可播放，只是时长未知。

    ``statuses`` 是逗号分隔的状态白名单（默认只处理 ``failed``）。**探测手段换了才需要传**：
    v2.42.16 上了双 Range 头尾读取（能读到 moov 在尾的 mp4/mov）之后，已经停在
    ``probed_no_duration`` / ``degraded`` 的条目也得重探一次，否则会一直挂着
    「没时长」的旧结论。用法：
    ``POST /api/admin/emby/scrape/probe/retry-failed?statuses=failed,degraded,probed_no_duration``
    """
    from backend.emby_server import probe_worker

    wanted = tuple(s.strip() for s in statuses.split(",") if s.strip()) or None
    n = probe_worker.retry_failed(db, limit=limit, statuses=wanted)
    return {"success": True, "requeued": n, "statuses": wanted or ("failed",)}


@admin_emby_router.get("/scrape/enrich-progress")
def get_enrich_progress(
    staff: base_models.WebUser = Depends(require_staff),
):
    """补全 worker 进度：enrich 待处理/进行中/成功/失败/重试中 + probe 队列 + 线程数"""
    from backend.emby_server import enrich_worker
    return {"success": True, **enrich_worker.get_progress()}


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


# ==================== 手动绑定 TMDB ID ====================

class TmdbBindRequest(BaseModel):
    tmdb_id: str = Field(default="", description="要绑定的 TMDB ID；留空表示解绑")
    verify: bool = Field(default=True, description="绑定前先向 TMDB 校验该 ID 确实存在")


@admin_emby_router.get("/scrape/items/{item_id}/tmdb-preview")
def preview_tmdb_id(
    item_id: int,
    tmdb_id: str,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """输入 TMDB ID 时实时预览：管理员要先看清「这到底是哪部片」再决定绑不绑。

    预览只读，不写库。返回的 title/year 会显示在确认框里，避免手滑绑错。
    """
    item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    tid = (tmdb_id or "").strip()
    if not tid.isdigit():
        raise HTTPException(status_code=400, detail="TMDB ID 必须是数字")
    if not tmdb_client.configured:
        raise HTTPException(status_code=400, detail="未配置 TMDB Key，无法校验")
    kind = "series" if item.item_type in ("series", "season", "episode") else "movie"
    data = tmdb_client.details(tid, kind)
    if not data:
        raise HTTPException(status_code=404, detail=f"TMDB 上找不到 ID {tid}")
    title = data.get("name") or data.get("title") or ""
    year = (data.get("first_air_date") or data.get("release_date") or "")[:4]
    return {
        "tmdb_id": tid,
        "title": title,
        "year": year or None,
        "poster": data.get("poster_path"),
        "current_name": item.name,
        "current_tmdb_id": item.tmdb_id,
        "matches_current": bool(title) and _norm_name(title) == _norm_name(item.name or ""),
    }


def _norm_name(s: str) -> str:
    """归一化片名用于「是否就是当前这条」的提示（不参与任何写库判断）"""
    import re as _re
    return _re.sub(r"[\s:：·\-—_、,，!！?？~～'\"“”‘’()（）]+", "", (s or "").lower())


@admin_emby_router.post("/scrape/items/{item_id}/bind-tmdb")
def bind_tmdb_id(
    item_id: int,
    req: TmdbBindRequest,
    staff: base_models.WebUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """手动指定 TMDB ID（或解绑）。

    背景：TMDB 对中文剧集/综艺收录偏少，少数条目自动刮削怎么搜都搜不到，
    反复重试也是白试。给管理员一个**手动出口**——比再接第四个数据源更治本。

    绑定后立刻取详情补全（图/简介/评分/别名），省得还要再点一次重刮。
    """
    item = db.query(em.MediaItem).filter(em.MediaItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    if item.item_type not in ("movie", "series", "season", "episode"):
        raise HTTPException(status_code=400, detail=f"不支持的条目类型：{item.item_type}")

    tid = (req.tmdb_id or "").strip()
    notes: list[str] = []

    if not tid:
        # 解绑
        before = item.tmdb_id
        item.tmdb_id = None
        item.last_scraped_at = None
        item.metadata_source = None
        item.enrich_status = "pending"
        item.enrich_attempts = 0
        item.enrich_next_retry_at = None
        db.commit()
        return {
            "success": True, "unbound": True,
            "item": {"id": item.id, "name": item.name, "item_type": item.item_type},
            "notes": [f"已解绑（原 TMDB {before}）并重新排入补全队列"],
        }

    if not tid.isdigit():
        raise HTTPException(status_code=400, detail="TMDB ID 必须是数字")

    if req.verify:
        if not tmdb_client.configured:
            raise HTTPException(status_code=400, detail="未配置 TMDB Key，无法校验")
        kind = "series" if item.item_type in ("series", "season", "episode") else "movie"
        data = tmdb_client.details(tid, kind)
        if not data:
            raise HTTPException(status_code=404, detail=f"TMDB 上找不到 ID {tid}，未绑定")
        notes.append(f"已校验：{data.get('name') or data.get('title')}")

    item.tmdb_id = tid
    item.last_scraped_at = datetime.now()
    item.metadata_source = "tmdb"
    # 绑定了权威 ID 就补齐缺失项（不覆盖 NFO 已提供的文字）
    if req.verify and tmdb_client.configured:
        kind = "series" if item.item_type in ("series", "season", "episode") else "movie"
        data = tmdb_client.details(tid, kind)
        if data:
            prewarm_images(data)
            if not (item.imdb_id and item.aliases):
                tmdb_client.apply_details(item, data)
                notes.append("补齐 IMDb/别名")
            if not (item.poster_path or item.primary_image_url):
                if tmdb_client.apply_images(item, data):
                    notes.append("补齐海报")
    item.enrich_status = "done"
    item.enrich_attempts = 0
    item.enrich_next_retry_at = None
    db.commit()
    return {
        "success": True, "unbound": False,
        "item": {"id": item.id, "name": item.name, "item_type": item.item_type,
                 "tmdb_id": item.tmdb_id},
        "notes": notes,
    }
