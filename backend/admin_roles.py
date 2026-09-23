"""管理员角色与权限（v2.26.0）

此前后台只有一种身份：``is_staff``。要给运营 / 客服 / 审计的人开一个号，就得把
「改系统设置、改上游 Key、管管理员」一起交出去——实际使用里没人愿意这样。

这里在原身份之上加一层**角色**（存 ``web_users.admin_role``）：

- ``super``：全部（**升级前的老管理员都是它**：``admin_role`` 为空按 super 处理，
  既不会因为升级把现有管理员降权，也不会出现「没人进得去后台」）；
- ``operator``：日常运营全都能做（用户、订阅、经济流水、卡码、优惠券、订单、求片、工单、
  公告、设备、媒体库、存储来源、服务器与线路、扫描与修复、切当前服），
  但改不了**系统设置 / 经济设置、能力中心（上游 Key）、播放与客户端策略、管理员与权限**；
- ``viewer``：只读（GET / HEAD / OPTIONS），给审计与排查看。

判定的位置只有一个：``get_current_admin``（``/api/admin/*``）与 ``require_staff``
（``/api/admin/emby/*``）。**不做端点级散落判断**——散落的判断迟早会有漏网的写接口，
一处漏网就等于角色无效。
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request

ROLE_SUPER = "super"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"

ROLES = (ROLE_SUPER, ROLE_OPERATOR, ROLE_VIEWER)

ROLE_LABELS = {
    ROLE_SUPER: "超级管理员",
    ROLE_OPERATOR: "运营",
    ROLE_VIEWER: "只读审计",
}

ROLE_HINTS = {
    ROLE_SUPER: "全部权限：含系统设置、上游 Key（能力中心）、播放与客户端策略、管理员与权限",
    ROLE_OPERATOR: "日常运营：用户 / 订阅 / 订单 / 卡码 / 求片 / 工单 / 媒体库 / 存储来源 / 服务器；不能改系统设置与权限",
    ROLE_VIEWER: "只读：能看所有页面与数据，任何修改都会被拒绝（适合审计与排查）",
}

# 只读判定：这三个方法不算修改
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# 仅超级管理员可写的前缀：系统与结构，不是日常运营（读仍然人人可看）
SUPER_ONLY_PREFIXES = (
    "/api/admin/admins",           # 管理员与权限本身
    "/api/admin/economy/settings",  # 系统 / 经济设置
    "/api/admin/playback/policy",   # 播放与客户端策略（影响所有人能不能看）
    "/api/admin/capabilities",      # 能力中心：上游 Key
)


def normalize_role(raw: Optional[str]) -> str:
    """把库里的值收敛到枚举内

    空值 / 未知值都当 super：升级上来的老管理员没写过这个字段，
    误判成 viewer 会让人以为「系统坏了」，而 super 与升级前行为完全一致。
    """
    value = (raw or "").strip().lower()
    return value if value in ROLES else ROLE_SUPER


def role_of(user) -> str:
    """某个管理员当前的角色（非管理员调用者本身已被鉴权拦下）"""
    return normalize_role(getattr(user, "admin_role", None))


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def can_write(user) -> bool:
    """这个角色能不能做写操作（前端据此把按钮置灰，服务端仍然自己判定一次）"""
    return role_of(user) != ROLE_VIEWER


def is_super(user) -> bool:
    return role_of(user) == ROLE_SUPER


def blocked_reason(request: Request, user) -> Optional[str]:
    """这次请求为什么被拦（None = 放行）

    只读角色的**所有**写操作都拦；运营角色只拦 ``SUPER_ONLY_PREFIXES`` 下的写操作。
    """
    path = getattr(getattr(request, "url", None), "path", "") or ""
    method = (getattr(request, "method", "") or "").upper()
    role = role_of(user)
    if role == ROLE_VIEWER and method not in SAFE_METHODS:
        return "当前账号是「只读审计」角色：可以查看，不能修改；需要写权限请让超级管理员调整角色"
    if role != ROLE_SUPER and method not in SAFE_METHODS:
        for prefix in SUPER_ONLY_PREFIXES:
            if path.startswith(prefix):
                return "这一项需要「超级管理员」角色（当前：{}）".format(role_label(role))
    return None


def ensure_admin_allowed(request: Request, user) -> None:
    """鉴权依赖里统一调用：不满足就 403，并说清缺什么"""
    reason = blocked_reason(request, user)
    if reason:
        raise HTTPException(status_code=403, detail=reason)


def roles_payload() -> list:
    """角色元数据（前端不自己维护一份，改后端一处即可）"""
    return [
        {"value": role, "label": ROLE_LABELS[role], "hint": ROLE_HINTS[role]}
        for role in ROLES
    ]


def permission_payload(user) -> dict:
    """当前账号能做什么（``GET /api/admin/auth/me`` 带回，前端据此置灰入口）"""
    role = role_of(user)
    return {
        "role": role,
        "role_label": role_label(role),
        "can_write": role != ROLE_VIEWER,
        "is_super": role == ROLE_SUPER,
    }
