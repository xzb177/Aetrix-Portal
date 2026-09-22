"""能力：人机验证（Turnstile / reCAPTCHA / hCaptcha）

为登录、注册等动作加一道人机验证。站点密钥与私钥由管理员自己申请后填进来——项目不内置任何
密钥，也不锁定任何一家提供方。

行为约定：

- 没选提供方 / 没填密钥 → **直接放行**（不能把站点锁在门外），后台只提示「未配置」；
- 打开保护的动作要求请求体带 ``captcha_token``（前端挂件生成），校验失败一律 400；
- 校验走提供方 ``siteverify``，失败原因原样返回（便于排查密钥、域名或时效问题）。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend import models

SPEC = {
    "title": "人机验证",
    "desc": "为登录、注册等动作配置 Turnstile、reCAPTCHA 或 hCaptcha。",
    "group": "网络与安全",
    "docs_hint": "保护的是用户端登录 / 注册；私钥只报「已配置」，前端挂件用站点密钥。",
    "fields": [
        {"key": "captcha_provider", "label": "提供方", "type": "select", "default": "none",
         "options": ["none", "turnstile", "recaptcha", "hcaptcha"]},
        {"key": "captcha_site_key", "label": "站点密钥（Site Key）", "type": "str", "default": ""},
        {"key": "captcha_secret_key", "label": "私钥（Secret Key）", "type": "secret", "default": ""},
        {"key": "captcha_protect_login", "label": "保护用户端登录", "type": "bool", "default": "true"},
        {"key": "captcha_protect_register", "label": "保护用户端注册", "type": "bool", "default": "true"},
    ],
    "test_label": "测试密钥",
}

VERIFY_URLS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "recaptcha": "https://www.google.com/recaptcha/api/siteverify",
    "hcaptcha": "https://hcaptcha.com/siteverify",
}
PROVIDER_LABELS = {"turnstile": "Cloudflare Turnstile", "recaptcha": "Google reCAPTCHA",
                   "hcaptcha": "hCaptcha"}
# 前端挂件需要的脚本地址（后台下发，前端不写死）
WIDGET_SCRIPTS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit",
    "recaptcha": "https://www.google.com/recaptcha/api.js?render=explicit",
    "hcaptcha": "https://js.hcaptcha.com/1/api.js?render=explicit",
}


def _value(db: Session, key: str, default: str = "") -> str:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if row and row.value is not None:
        return str(row.value).strip()
    return default


def provider(db: Session) -> str:
    name = _value(db, "captcha_provider", "none").lower()
    return name if name in VERIFY_URLS else "none"


def secret_key(db: Session) -> str:
    return _value(db, "captcha_secret_key")


def is_protected(db: Session, action: str) -> bool:
    """某个动作（login / register）是否要校验"""
    if provider(db) == "none" or not secret_key(db):
        return False
    return _value(db, f"captcha_protect_{action}", "true").lower() == "true"


def widget_info(db: Session) -> dict:
    """给前端挂件的信息（只含公开的站点密钥；未启用时不给任何密钥）"""
    name = provider(db)
    site_key = _value(db, "captcha_site_key")
    enabled = name != "none" and bool(secret_key(db)) and bool(site_key)
    return {
        "enabled": enabled,
        "provider": name if enabled else "none",
        "label": PROVIDER_LABELS.get(name, "") if enabled else "",
        "site_key": site_key if enabled else "",
        "script_url": WIDGET_SCRIPTS.get(name, "") if enabled else "",
        "actions": {a: is_protected(db, a) for a in ("login", "register")},
    }


def verify_token(db: Session, token: Optional[str], ip: str = "") -> tuple[bool, str]:
    """调用提供方 siteverify；未配置时视为通过"""
    name = provider(db)
    if name == "none" or not secret_key(db):
        return True, ""
    token = (token or "").strip()
    if not token:
        return False, "请完成人机验证"
    import httpx

    data = {"secret": secret_key(db), "response": token}
    if ip:
        data["remoteip"] = ip
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(VERIFY_URLS[name], data=data)
        body = resp.json() if resp.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001 — 提供方不可达时不能把用户挡在门外太久
        return False, f"人机验证服务不可达：{type(exc).__name__}"
    if body.get("success"):
        return True, ""
    codes = body.get("error-codes") or []
    return False, f"人机验证失败（{', '.join(str(c) for c in codes) or resp.status_code}）"


def verify_request(db: Session, action: str, token: Optional[str], ip: str = "") -> tuple[bool, str]:
    """端点里用的入口：没开保护直接放行"""
    if not is_protected(db, action):
        return True, ""
    return verify_token(db, token, ip)


def is_configured(values: dict) -> bool:
    """选了提供方并把两把密钥都填了才算配过"""
    name = str(values.get("captcha_provider") or "none").lower()
    if name not in VERIFY_URLS:
        return False
    return bool(values.get("captcha_secret_key")) and bool(values.get("captcha_site_key"))


def is_enabled(values: dict) -> bool:
    """当前是否真在拦人"""
    return is_configured(values)


def test(db: Session, payload: dict) -> dict:
    """拿一个必然无效的 token 打一次 siteverify：

    能收到 ``invalid-input-response`` 说明**密钥有效、域名可达**（如果密钥错会返回
    ``invalid-input-secret``）。这是在不依赖前端挂件的前提下，能对密钥做的最直接验证。
    """
    name = provider(db)
    if name == "none":
        return {"ok": False, "message": "未选择提供方（先在「提供方」里选一家并填密钥）"}
    secret = secret_key(db)
    if not secret:
        return {"ok": False, "message": "未填私钥（Secret Key）"}
    import httpx

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(VERIFY_URLS[name], data={"secret": secret, "response": "codebuff-probe"})
        body = resp.json() if resp.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"{PROVIDER_LABELS.get(name, name)} 不可达：{type(exc).__name__}: {exc}"}
    codes = [str(c) for c in (body.get("error-codes") or [])]
    if "invalid-input-secret" in codes or "invalid-secret" in codes:
        return {"ok": False, "message": "私钥无效（invalid-input-secret），请核对 Secret Key",
                "detail": {"provider": name, "error_codes": codes}}
    if body.get("success"):
        return {"ok": True, "message": "密钥有效（这个 token 竟然通过了，请确认没有把 token 校验关掉）",
                "detail": {"provider": name}}
    return {"ok": True,
            "message": f"密钥有效：{PROVIDER_LABELS.get(name, name)} 已接受该私钥（对无效 token 返回 {', '.join(codes) or 'ok'}）",
            "detail": {"provider": name, "error_codes": codes}}
