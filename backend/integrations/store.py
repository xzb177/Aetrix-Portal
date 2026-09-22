"""能力配置的批量读写

能力模块原先各自写了一个「按 key 查一次 SystemConfig」的小助手，读一次配置要 4~6 次往返
（人机验证挂件一次要问 5 个键：提供方 / 站点密钥 / 私钥 / 两个动作开关）。这里统一成
**一次 IN 查询取回一批**，语义与逐键查询完全一致：

- 行存在 → 用行里的值（**哪怕是空串**，空串是「用户清空过」，不能被默认值顶掉）；
- 行不存在 → 用默认值。

写回同样是批量：一次 IN 查询取回已有行，缺的再补 INSERT，避免每字段一次往返。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from sqlalchemy.orm import Session

from backend import models

DEFAULTS_SENTINEL = object()


def read_values(
    db: Session,
    keys: Iterable[str],
    defaults: Optional[Mapping[str, Any]] = None,
) -> dict[str, str]:
    """一次查询取回一批配置键（缺失的用 defaults 里的值，没有就是空串）"""
    key_list = list(keys)
    if not key_list:
        return {}
    rows = (
        db.query(models.SystemConfig.key, models.SystemConfig.value)
        .filter(models.SystemConfig.key.in_(key_list))
        .all()
    )
    found = {key: ("" if value is None else str(value)) for key, value in rows}
    out: dict[str, str] = {}
    for key in key_list:
        if key in found:
            out[key] = found[key]
            continue
        default = (defaults or {}).get(key, DEFAULTS_SENTINEL)
        out[key] = "" if default is DEFAULTS_SENTINEL or default is None else str(default)
    return out


def read_value(db: Session, key: str, default: str = "") -> str:
    """单键读取（内部仍走一次查询；只有确实只用一个键时才用它）"""
    return read_values(db, [key], {key: default})[key]


def write_values(db: Session, values: Mapping[str, str], descriptions: Optional[Mapping[str, str]] = None) -> int:
    """批量写入（一次查询已有行 + 缺失补插）；返回写入的键数

    只负责写，**不提交**——提交时机由调用方决定（能力保存要把所有字段与审计放在同一个事务里）。
    """
    pairs = {str(k): ("" if v is None else str(v)) for k, v in (values or {}).items()}
    if not pairs:
        return 0
    rows = (
        db.query(models.SystemConfig)
        .filter(models.SystemConfig.key.in_(list(pairs)))
        .all()
    )
    existing = {row.key: row for row in rows}
    for key, value in pairs.items():
        row = existing.get(key)
        if row is not None:
            row.value = value
            continue
        db.add(models.SystemConfig(key=key, value=value,
                                   description=(descriptions or {}).get(key) or None))
    return len(pairs)
