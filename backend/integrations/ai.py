"""能力：AI 模型设置（OpenAI 兼容端点 + 多密钥）

只提供能力：端点、模型、密钥全部由管理员自己填，项目不内置任何 key。任何 OpenAI 兼容
服务（官方 / 中转 / 本地 Ollama、vLLM、one-api…）改 ``base_url`` 即可用。

- **多密钥**：一行一个（也支持逗号分隔），每次调用轮换，单把 key 被限流时不会整体不可用；
- **用户侧消费点**：``POST /api/user/ai/ask``（登录用户，按 ``ai_daily_limit`` 限流）；
- **测试**：真实发一次极小的 completion，把模型回显给管理员看。
"""
from __future__ import annotations

import itertools
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend import models

SPEC = {
    "title": "AI 模型设置",
    "desc": "AI 提供商、模型、API 端点与多密钥；用于用户端「AI 客服」。",
    "group": "AI 与智能",
    "docs_hint": "OpenAI 兼容接口：Base URL 通常以 /v1 结尾。密钥一行一个，会轮换使用。",
    "fields": [
        {"key": "ai_enabled", "label": "启用 AI 能力", "type": "bool", "default": "true"},
        {"key": "ai_base_url", "label": "API 端点（Base URL）", "type": "str",
         "default": "https://api.openai.com/v1", "required": True,
         "placeholder": "https://api.openai.com/v1"},
        {"key": "ai_api_keys", "label": "API 密钥（可多把）", "type": "secret",
         "hint": "一行一个或逗号分隔；轮换使用"},
        {"key": "ai_model", "label": "模型", "type": "str", "default": "gpt-4o-mini",
         "required": True, "placeholder": "gpt-4o-mini / deepseek-chat / qwen2.5:7b"},
        {"key": "ai_system_prompt", "label": "系统提示词", "type": "str",
         "default": "你是本站的客服助手，回答要简短、友好，只回答与本站使用相关的问题。",
         "placeholder": "客服人设 / 回答边界"},
        {"key": "ai_temperature", "label": "温度", "type": "str", "default": "0.7"},
        {"key": "ai_max_tokens", "label": "单次最大回复长度", "type": "int", "default": "512"},
        {"key": "ai_timeout", "label": "超时（秒）", "type": "int", "default": "60"},
        {"key": "ai_daily_limit", "label": "每用户每日提问上限", "type": "int", "default": "20",
         "hint": "0 = 不限制"},
    ],
    "test_label": "测试模型",
}

_lock = threading.Lock()
_counter = itertools.count()

# 每用户当日用量（问一句记一次）。与限流器同一取舍：进程内计数，单进程部署即准确；
# 多进程下每个 worker 各记一份，最坏情况相当于配额放宽到「上限 × 进程数」。
_usage_lock = threading.Lock()
_usage: dict[int, tuple[str, int]] = {}


def _value(db: Session, key: str, default: str = "") -> str:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if row and row.value is not None:
        return str(row.value).strip()
    return default


def enabled(db: Session) -> bool:
    return _value(db, "ai_enabled", "true").lower() == "true"


def api_keys(db: Session) -> list[str]:
    """多密钥：换行 / 逗号 / 分号都认"""
    raw = _value(db, "ai_api_keys")
    parts = raw.replace(";", "\n").replace(",", "\n").split("\n")
    return [p.strip() for p in parts if p.strip()]


def config(db: Session) -> dict:
    try:
        temperature = float(_value(db, "ai_temperature", "0.7") or 0.7)
    except ValueError:
        temperature = 0.7
    try:
        max_tokens = int(_value(db, "ai_max_tokens", "512") or 512)
    except ValueError:
        max_tokens = 512
    try:
        timeout = float(_value(db, "ai_timeout", "60") or 60)
    except ValueError:
        timeout = 60.0
    return {
        "base_url": (_value(db, "ai_base_url", "https://api.openai.com/v1") or "").rstrip("/"),
        "model": _value(db, "ai_model", "gpt-4o-mini"),
        "system_prompt": _value(db, "ai_system_prompt"),
        "temperature": temperature,
        "max_tokens": max(1, max_tokens),
        "timeout": max(1.0, timeout),
    }


def _next_key(db: Session) -> str:
    keys = api_keys(db)
    if not keys:
        return ""
    with _lock:
        index = next(_counter)
    return keys[index % len(keys)]


def chat(db: Session, messages: list[dict], *, max_tokens: Optional[int] = None,
         use_system_prompt: bool = True) -> dict:
    """发一次 chat/completions；返回 ``{ok, answer, model, key_index, message}``"""
    cfg = config(db)
    keys = api_keys(db)
    if not cfg["base_url"] or not cfg["model"]:
        return {"ok": False, "message": "未配置 API 端点或模型"}
    if not keys:
        return {"ok": False, "message": "未配置 API 密钥"}
    key = _next_key(db)
    payload_messages = []
    if use_system_prompt and cfg["system_prompt"]:
        payload_messages.append({"role": "system", "content": cfg["system_prompt"]})
    payload_messages.extend(messages)
    import httpx

    try:
        with httpx.Client(timeout=cfg["timeout"]) as client:
            resp = client.post(
                f"{cfg['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": cfg["model"],
                    "messages": payload_messages,
                    "temperature": cfg["temperature"],
                    "max_tokens": int(max_tokens or cfg["max_tokens"]),
                },
            )
        if resp.status_code >= 400:
            detail = resp.text[:300]
            return {"ok": False, "message": f"上游 HTTP {resp.status_code}：{detail}",
                    "detail": {"model": cfg["model"]}}
        body = resp.json()
    except Exception as exc:  # noqa: BLE001 — 上游不可达要如实报出
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}", "detail": {"model": cfg["model"]}}
    choices = body.get("choices") or []
    answer = ""
    if choices:
        answer = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not answer:
        return {"ok": False, "message": "上游没有返回内容", "detail": {"model": cfg["model"]}}
    usage = body.get("usage") or {}
    return {"ok": True, "answer": answer, "model": body.get("model") or cfg["model"],
            "message": "", "detail": {"usage": usage, "keys": len(keys)}}


def ask(db: Session, question: str, history: Optional[list[dict]] = None) -> dict:
    """用户侧问答入口（history 为 ``[{role, content}]``，最多取最近 8 轮）

    history 来自客户端，因此只接受 user / assistant 两种角色——否则用户可以直接塞一条
    ``role=system`` 把自己变成系统提示词，绕开管理员设定的人设与回答边界。
    """
    messages: list[dict] = []
    for turn in list(history or []):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip().lower()
        content = turn.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        messages.append({"role": role, "content": content[:4000]})
    messages = messages[-8:]
    messages.append({"role": "user", "content": question})
    return chat(db, messages)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def used_today(user_id: int) -> int:
    """今日已提问次数（跨天自动归零）"""
    with _usage_lock:
        day, count = _usage.get(user_id, ("", 0))
        return count if day == _today() else 0


def record_usage(user_id: int) -> int:
    """记一次提问，返回今日累计次数"""
    day = _today()
    with _usage_lock:
        if len(_usage) > 20000:  # 兜底：异常场景下不让这张表无限长大
            _usage.clear()
        current_day, count = _usage.get(user_id, ("", 0))
        count = count + 1 if current_day == day else 1
        _usage[user_id] = (day, count)
        return count


def daily_limit(db: Session) -> int:
    """每用户每日提问上限（0 = 不限）"""
    try:
        return max(0, int(_value(db, "ai_daily_limit", "20") or 0))
    except ValueError:
        return 0


def configured(db: Session) -> bool:
    """能力是否已配齐（端点 + 模型 + 至少一把密钥）"""
    cfg = config(db)
    return bool(cfg["base_url"]) and bool(cfg["model"]) and bool(api_keys(db))


def available(db: Session) -> bool:
    """是否可用：启用且已配齐"""
    return enabled(db) and configured(db)


def is_configured(values: dict) -> bool:
    """端点、模型、密钥都齐了才算配过（不看开关）"""
    return (bool(values.get("ai_api_keys")) and bool(values.get("ai_model"))
            and bool(values.get("ai_base_url")))


def is_enabled(values: dict) -> bool:
    return str(values.get("ai_enabled") or "").lower() == "true" and is_configured(values)


def test(db: Session, payload: dict) -> dict:
    cfg = config(db)
    if not api_keys(db):
        return {"ok": False, "message": "未配置 API 密钥（保存后再测）"}
    result = chat(db, [{"role": "user", "content": "回复两个字：可用"}], max_tokens=16)
    if not result.get("ok"):
        return {"ok": False, "message": result.get("message") or "调用失败",
                "detail": {"base_url": cfg["base_url"], "model": cfg["model"]}}
    return {"ok": True,
            "message": f"模型可用：{result['model']} → {result['answer'][:60]}",
            "detail": {"base_url": cfg["base_url"], "keys": result.get("detail", {}).get("keys")}}
