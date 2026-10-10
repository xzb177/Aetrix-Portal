"""Aetrix-Portal 后端：.strm 文件 Drive 直链的签名与校验工具。

定位
----
.strm 是纯文本小文件，服务端 scanner/relay 读取其内容拿到 Drive 直链再代理播放。
为防盗链，.strm 文件内容改为带签名的 URL，签名默认 1 小时过期；janitor 定时刷新
签名，节奏随 TTL 推导（见 refresh_threshold_seconds，本模块提供刷新判定）。

格式
----
签名后内容形如 ``{drive_url}&aexp={exp}&asig={sig}``：

- ``exp``：过期时间（unix 秒 = 当前时间 + TTL）；
- ``sig``：``HMAC-SHA256(SECRET_KEY, "{canonical_drive_url}:{exp}")`` 的 hex 前 32 位；
- ``canonical_drive_url``：去掉 ``aexp``/``asig`` 参数后的原始 URL（防止二次签名叠加）。

三种校验结果（verify_strm_url 的 status）
----------------------------------------
- ``ok``：签名参数齐全、exp 未过期且 HMAC 比对通过，返回 canonical URL，可直接使用；
- ``legacy``：旧格式（无 aexp/asig 参数），平滑迁移期放行，由刷新任务补签名；
- ``bad``：无 URL、参数残缺、exp 非数字/已过期或签名不匹配，返回空串，禁止使用。

密钥来源
--------
复用 ``backend.security.SECRET_KEY``（环境变量 ``SECRET_KEY``，EA 与 API 容器间已同步），
本模块不生成、不管理另一套密钥。

TTL 配置
--------
SystemConfig 键 ``strm_sig_ttl_seconds``（默认 ``"3600"``），热读实现收敛到
``play_sign.strm_sig_ttl_seconds``（横切能力只许一套）；合法范围 300–86400 秒，
非数字或越界均回落默认值；db 为 None 时直接用默认值。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

SIG_PARAM_EXP = "aexp"
SIG_PARAM_SIG = "asig"
REFRESH_THRESHOLD_SECONDS = 600


def strm_sig_ttl_seconds(db: Session | None = None) -> int:
    """热读 SystemConfig 中的 .strm 签名 TTL（秒）。

    唯一实现在 ``play_sign.strm_sig_ttl_seconds``（横切能力只许一套），
    本函数只是薄委托，方便 .strm 相关调用方就近引用。
    """
    from backend.emby_server import play_sign

    return play_sign.strm_sig_ttl_seconds(db)


def _signing_key() -> bytes:
    """签名密钥：与 play_sign 同源，复用面板 SECRET_KEY（函数内导入，测试可 reload）。"""
    from backend.security import SECRET_KEY

    return SECRET_KEY.encode("utf-8")


def strip_sig_params(url: str) -> str:
    """去掉 URL 中的 aexp/asig 参数（代理向 Drive 发请求前也用本函数清理）。"""
    if not url:
        return url
    parts = urlsplit(url)
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in (SIG_PARAM_EXP, SIG_PARAM_SIG)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def _hmac_sig(canonical: str, exp: int) -> str:
    """按约定格式计算签名：HMAC-SHA256(SECRET_KEY, "{canonical}:{exp}") 的 hex 前 32 位。"""
    return hmac.new(_signing_key(), f"{canonical}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def sign_strm_url(drive_url: str, ttl_seconds: int | None = None, db: Session | None = None) -> str:
    """给 Drive 直链追加 aexp/asig 签名；先 canonical 化，空 URL 原样返回，永不抛异常。"""
    if not drive_url:
        return drive_url
    canonical = strip_sig_params(drive_url)
    if not canonical:
        return drive_url
    ttl = ttl_seconds if ttl_seconds is not None else strm_sig_ttl_seconds(db)
    exp = int(time.time()) + int(ttl)
    sig = _hmac_sig(canonical, exp)
    sep = "&" if "?" in canonical else "?"
    return f"{canonical}{sep}{SIG_PARAM_EXP}={exp}&{SIG_PARAM_SIG}={sig}"


def verify_strm_url(content: str) -> tuple[str, str]:
    """校验 .strm 内容，返回 (clean_url, status)；status ∈ {"ok", "legacy", "bad"}。

    只认第一行有效 URL（语义复用 mounts.strm_url：BOM/空行/#注释容忍）；任何异常
    一律返回 ("", "bad")，本函数永不抛异常。
    """
    try:
        # 延迟导入：mounts 在顶层 import 本模块，此处必须避免循环导入。
        from backend.emby_server.mounts import strm_url

        url = strm_url(content)
        if not url:
            return "", "bad"
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
        exp_raw = query.get(SIG_PARAM_EXP, [None])[0]
        sig_raw = query.get(SIG_PARAM_SIG, [None])[0]
        if exp_raw is None and sig_raw is None:
            return url, "legacy"
        if exp_raw is None or sig_raw is None:
            return "", "bad"
        exp = int(exp_raw)
        if exp <= int(time.time()):
            return "", "bad"
        canonical = strip_sig_params(url)
        if not hmac.compare_digest(_hmac_sig(canonical, exp), sig_raw):
            return "", "bad"
        return canonical, "ok"
    except Exception:
        return "", "bad"


def refresh_threshold_seconds(ttl_seconds: int, tick_seconds: int) -> int:
    """重签阈值随 TTL 走：剩余有效期 < max(TTL/3, 2×tick) 就重签。

    2×tick 保证"这一拍没赶上、下一拍还来得及"；TTL/3 让长 TTL 不必临期才刷。
    阈值 ≥ TTL（TTL 配得过短）时等于每拍都重签——宁可多写也不让链接过期。
    """
    ttl = max(1, int(ttl_seconds))
    tick = max(1, int(tick_seconds))
    return max(ttl // 3, 2 * tick, REFRESH_THRESHOLD_SECONDS)


def needs_refresh(content: str, db: Session | None = None,
                  threshold_seconds: int | None = None) -> bool:
    """判断 .strm 内容是否需要刷新签名。

    legacy → True（补签名）；bad → False（坏的不碰，等人工处理）；
    ok 且剩余有效期 < threshold_seconds（缺省 600 秒；刷新任务传
    refresh_threshold_seconds(TTL, tick)）→ True，否则 False。
    db 参数仅为与 sign_strm_url 保持同构签名而保留，校验逻辑本身不需要数据库。
    """
    _, status = verify_strm_url(content)
    if status == "legacy":
        return True
    if status != "ok":
        # 签名本身有效、只是过期了 → 必须重签。以前 bad 一律不碰：刷新任务
        # 只要错过一次窗口（停机/重启超过剩余有效期、janitor 节拍抖动、或 TTL
        # 配得比 50 分钟刷新间隔还短），所有 .strm 就永久变成 bad，全库拒播且
        # 永远不会自愈。被篡改（HMAC 不符）的仍然不碰。
        return _expired_but_authentic(content)
    try:
        from backend.emby_server.mounts import strm_url

        url = strm_url(content)
        exp = int(parse_qs(urlsplit(url).query, keep_blank_values=True)[SIG_PARAM_EXP][0])
    except Exception:
        return False
    threshold = REFRESH_THRESHOLD_SECONDS if threshold_seconds is None else int(threshold_seconds)
    return (exp - time.time()) < threshold


def _expired_but_authentic(content: str) -> bool:
    """签名参数齐全、HMAC 比对通过、但 exp 已过期（= 我们自己签过的旧链接）。"""
    try:
        from backend.emby_server.mounts import strm_url

        url = strm_url(content)
        if not url:
            return False
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
        exp_raw = query.get(SIG_PARAM_EXP, [None])[0]
        sig_raw = query.get(SIG_PARAM_SIG, [None])[0]
        if exp_raw is None or sig_raw is None:
            return False
        exp = int(exp_raw)
        if exp > int(time.time()):
            return False
        return hmac.compare_digest(_hmac_sig(strip_sig_params(url), exp), sig_raw)
    except Exception:
        return False
