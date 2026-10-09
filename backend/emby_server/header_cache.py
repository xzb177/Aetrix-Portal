# -*- coding: utf-8 -*-
"""视频片头本地缓存（通用能力）

热门视频的文件头缓存到本地 SSD，起播时直接从本地读，跳过 Drive 延迟。

环境变量：
- HEADER_CACHE_ENABLED: 0/1，默认 1
- HEADER_CACHE_DIR: 缓存目录，默认 /data/header_cache
- HEADER_CACHE_SIZE_MB: 每个文件缓存多少 MB，默认 50
- HEADER_CACHE_MAX_GB: 缓存总上限 GB，默认 5
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

def _enabled() -> bool:
    return os.getenv("HEADER_CACHE_ENABLED", "1") != "0"

def _cache_dir() -> Path:
    return Path(os.getenv("HEADER_CACHE_DIR", "/data/header_cache"))

def _cache_size_bytes() -> int:
    try:
        mb = int(os.getenv("HEADER_CACHE_SIZE_MB", "50"))
    except ValueError:
        mb = 50
    return max(1, mb) * 1024 * 1024

def _max_total_bytes() -> int:
    try:
        gb = int(os.getenv("HEADER_CACHE_MAX_GB", "5"))
    except ValueError:
        gb = 5
    return max(1, gb) * 1024 * 1024 * 1024

def _cache_path(guid: str) -> Path:
    # 用 guid 的 hash 做文件名，避免特殊字符
    h = hashlib.md5(guid.encode()).hexdigest()[:16]
    return _cache_dir() / f"{h}.header"

def get_cached_header(guid: str, file_path: str) -> Path | None:
    """获取已缓存的片头文件路径，不存在返回 None"""
    if not _enabled():
        return None
    p = _cache_path(guid)
    if p.exists() and p.stat().st_size > 0:
        # 更新访问时间用于 LRU
        try:
            os.utime(p, None)
        except Exception:
            pass
        return p
    return None

def warm_header_async(guid: str, file_path: str) -> None:
    """后台异步缓存文件头（不阻塞）"""
    if not _enabled():
        return
    if get_cached_header(guid, file_path):
        return  # 已有缓存
    
    def _do_warm():
        try:
            cache_dir = _cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            # 检查总大小，超了就清理最老的
            _evict_if_needed()
            
            target = _cache_path(guid)
            # 用临时文件写完再改名，避免半截文件
            tmp = target.with_suffix(".tmp")
            size = _cache_size_bytes()
            
            with open(file_path, "rb") as src, open(tmp, "wb") as dst:
                remaining = size
                while remaining > 0:
                    chunk = src.read(min(1024*1024, remaining))
                    if not chunk:
                        break
                    dst.write(chunk)
                    remaining -= len(chunk)
            
            tmp.rename(target)
            logger.info(f"片头缓存完成: {guid} ({target.stat().st_size // 1024 // 1024}MB)")
        except Exception as e:
            logger.debug(f"片头缓存失败 {guid}: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    
    threading.Thread(target=_do_warm, daemon=True).start()

def _evict_if_needed() -> None:
    """LRU 清理：超总上限时删最久未访问的"""
    try:
        cache_dir = _cache_dir()
        if not cache_dir.exists():
            return
        
        files = [(p, p.stat()) for p in cache_dir.glob("*.header")]
        total = sum(s.st_size for _, s in files)
        max_total = _max_total_bytes()
        
        if total <= max_total:
            return
        
        # 按访问时间排序，删最老的
        files.sort(key=lambda x: x[1].st_atime)
        for p, s in files:
            if total <= max_total * 0.8:  # 清到 80% 就停
                break
            try:
                p.unlink()
                total -= s.st_size
                logger.info(f"片头缓存 LRU 清理: {p.name}")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"缓存清理失败: {e}")
