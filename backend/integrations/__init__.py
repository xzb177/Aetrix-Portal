"""外部服务能力中心

**只提供能力，不带任何内置凭据**：端点、密钥、账号一律由管理员在后台自己填，填完即可用
（每个能力都带「测试连接」）。项目本身不内置任何 AI key / SMTP 密码 / 地图 key。

架构：一个能力一个模块，模块暴露三样东西（后两样可选）：

- ``SPEC``：能力元数据与字段表（``fields`` 决定后台表单长什么样，前端不写死任何字段）；
- ``apply(db)``：保存后需要落地的副作用（例如代理要写进进程环境变量）；
- ``test(db, payload)``：真实连通性测试，成功与否与失败原因原样回给管理员。

配置统一落在 ``system_configs``（沿用既有配置表，多机部署共享同一套配置）。密钥类字段
（``secret``）读回来只报「已配置」，前端提交 ``******`` 表示不修改——与经济设置的约定一致。
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend import models

logger = logging.getLogger(__name__)

MASK = "******"
FIELD_TYPES = ("str", "secret", "int", "bool", "select")

# 能力清单：顺序即后台展示顺序；模块里再声明 title / desc / group
CAPABILITY_MODULES: tuple[str, ...] = (
    "proxy", "captcha", "mail", "telegram", "ai", "geoip",
)


def _module(slug: str):
    if slug not in CAPABILITY_MODULES:
        raise KeyError(slug)
    return importlib.import_module(f"backend.integrations.{slug}")


def _spec(slug: str) -> dict:
    return dict(_module(slug).SPEC)


def _coerce(field: dict, raw: Any) -> str:
    """按字段声明把前端传来的值规整成配置表里的字符串"""
    kind = field.get("type", "str")
    if kind == "bool":
        if isinstance(raw, bool):
            return "true" if raw else "false"
        return "true" if str(raw).strip().lower() in ("true", "1", "on", "yes") else "false"
    if kind == "int":
        try:
            return str(int(str(raw).strip() or 0))
        except (TypeError, ValueError):
            return str(int(field.get("default") or 0))
    text = "" if raw is None else str(raw).strip()
    if kind == "select":
        options = [str(o) for o in field.get("options") or []]
        return text if text in options else str(field.get("default") or "")
    return text


def _read(db: Session, field: dict) -> str:
    row = db.query(models.SystemConfig).filter(
        models.SystemConfig.key == field["key"]).first()
    if row and row.value is not None:
        return str(row.value)
    return str(field.get("default") or "")


def raw_values(db: Session, slug: str) -> dict:
    """读原始值（含密钥明文，仅供后端内部使用）"""
    return {f["key"]: _read(db, f) for f in _spec(slug)["fields"]}


def mask_values(slug: str, values: dict) -> dict:
    """对外序列化：密钥只报「是否已配置」"""
    out: dict = {}
    for field in _spec(slug)["fields"]:
        value = values.get(field["key"], "")
        if field.get("type") == "secret":
            out[field["key"]] = MASK if value else ""
        else:
            out[field["key"]] = value
    return out


def is_enabled(values: dict, slug: str) -> bool:
    """能力当前是否生效

    模块可自定义判定（例如人机验证要看「选没选提供方」，而不是某个 ``*_enabled`` 布尔），
    没自定义时按字段表里第一个 ``*_enabled`` 布尔判。
    """
    module = _module(slug)
    checker = getattr(module, "is_enabled", None)
    if callable(checker):
        return bool(checker(values))
    for field in _spec(slug)["fields"]:
        if field["key"].endswith("_enabled"):
            return str(values.get(field["key"], "")).lower() == "true"
    return True


def is_configured(slug: str, values: dict) -> bool:
    """是否「配齐了」：模块可自定义判定（如 GeoIP 两种提供方任选其一）

    只看字段是否齐全，不看开关：后台用「已配置 + 是否启用」两个维度给卡片打标，
    所以「关了但配过」与「压根没填」必须能区分开。
    """
    module = _module(slug)
    checker = getattr(module, "is_configured", None)
    if callable(checker):
        return bool(checker(values))
    # 默认：非密钥字段里标了 required 的都要有值
    for field in _spec(slug)["fields"]:
        if field.get("required") and not str(values.get(field["key"]) or "").strip():
            return False
    return True


def list_capabilities(db: Session) -> list[dict]:
    """能力总览（后台「系统设置」中心页用）"""
    items = []
    for slug in CAPABILITY_MODULES:
        values = raw_values(db, slug)
        spec = _spec(slug)
        items.append({
            "slug": slug,
            "title": spec.get("title", slug),
            "desc": spec.get("desc", ""),
            "group": spec.get("group", "外部服务"),
            "docs_hint": spec.get("docs_hint", ""),
            "enabled": is_enabled(values, slug),
            "configured": is_configured(slug, values),
            "fields": mask_values(slug, values),
            "test_label": spec.get("test_label", "测试连接"),
        })
    return items


def get_capability(db: Session, slug: str) -> dict:
    values = raw_values(db, slug)
    spec = _spec(slug)
    try:
        items = list_capabilities(db)
        item = next(i for i in items if i["slug"] == slug)
    except StopIteration:  # pragma: no cover — slug 已校验过
        item = {"slug": slug, "title": spec.get("title", slug), "desc": spec.get("desc", "")}
    return {"spec": spec, "item": item, "values": mask_values(slug, values)}


def save_capability(db: Session, slug: str, values: dict) -> dict:
    """保存能力配置；保存后调用 apply 落地副作用

    密钥字段的三条规矩（前端把已配好的密钥预填成 ``******``，所以这三种情况不会撞车）：

    - 字段**没提交**（键不存在）或值为 ``None`` → 不修改；
    - 值是掩码 ``******`` → 不修改；
    - 值是空串 → **清空已保存的密钥**（用户手动删掉了它）。

    第三条是必要的：否则密钥只换不撤——代理密码改了、Bot Token 不想再用了，都没办法删掉。
    """
    spec = _spec(slug)
    fields = {f["key"]: f for f in spec["fields"]}
    for key, raw in (values or {}).items():
        field = fields.get(key)
        if field is None:
            continue
        if field.get("type") == "secret" and (raw is None or str(raw) == MASK):
            continue
        row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        new_value = _coerce(field, raw)
        if row:
            row.value = new_value
            if field.get("label") and not row.description:
                row.description = f"{spec.get('title', slug)} · {field['label']}"
        else:
            db.add(models.SystemConfig(
                key=key, value=new_value,
                description=f"{spec.get('title', slug)} · {field.get('label') or ''}",
            ))
    db.commit()
    apply_capability(db, slug)
    return get_capability(db, slug)


def apply_capability(db: Session, slug: str) -> None:
    """落地副作用；失败只记日志，不能让保存动作整体失败"""
    module = _module(slug)
    hook = getattr(module, "apply", None)
    if not callable(hook):
        return
    try:
        hook(db)
    except Exception as exc:  # noqa: BLE001 — 例如代理不可达、通知渠道刷新失败
        logger.warning("能力 %s 的 apply 失败（可忽略）: %s", slug, exc)


def apply_all(db: Session) -> None:
    """启动时把所有能力落地一遍（目前只有代理需要）"""
    for slug in CAPABILITY_MODULES:
        apply_capability(db, slug)


def test_capability(db: Session, slug: str, payload: Optional[dict] = None) -> dict:
    """真实连通性测试（走真实网络/真实投递，不写配置）"""
    module = _module(slug)
    hook = getattr(module, "test", None)
    if not callable(hook):
        return {"ok": False, "message": "该能力不支持测试"}
    try:
        result = hook(db, payload or {})
    except Exception as exc:  # noqa: BLE001 — 测试就是把真实原因报出来
        logger.info("能力 %s 测试失败: %s", slug, exc)
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    if not isinstance(result, dict):
        return {"ok": bool(result), "message": ""}
    result.setdefault("ok", False)
    result.setdefault("message", "")
    return result
