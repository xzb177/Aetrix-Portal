"""
.strm 直链目录的通用可配置能力。

.strm 是纯文本小文件，内容为视频直链 URL；生产环境用 docker-compose
把宿主机 /opt/strm 挂到容器的 /strm（只读）。

本模块把 .strm 相关配置做成 SystemConfig 可配置项（运行时一律热读），共三项：

- strm_enabled：.strm 功能总开关，默认 "true"（启用）；
- strm_host_dir：宿主机 .strm 目录，默认 "/opt/strm"；
- strm_container_path：容器内挂载点。**全项目唯一事实源**是 container_path(db)：
  后台配置 > 环境变量 STRM_CONTAINER_PATH（docker-compose 挂载的容器侧路径，
  同一个变量）> "/strm"。扫描、判定、签名刷新一律走它，别处不许再读环境变量或写死 /strm。

docker-compose 的环境变量只管容器启动时的挂载本身（挂载仍需在
docker-compose 里声明），运行时"目录在哪"以后端这里的配置为准。
默认启用 = 与现状一致（/opt/strm → /strm）。
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from backend.integrations import store
from backend.models import SystemConfig

CONFIG_STRM_ENABLED = "strm_enabled"
CONFIG_STRM_HOST_DIR = "strm_host_dir"
CONFIG_STRM_CONTAINER_PATH = "strm_container_path"

DEFAULT_STRM_ENABLED = True
DEFAULT_STRM_HOST_DIR = "/opt/strm"
DEFAULT_STRM_CONTAINER_PATH = "/strm"

DESCRIPTIONS: dict[str, str] = {
    CONFIG_STRM_ENABLED: ".strm 功能总开关（true 启用 / false 关闭），默认启用",
    CONFIG_STRM_HOST_DIR: "宿主机 .strm 目录（docker-compose 挂载的源目录），默认 /opt/strm",
    CONFIG_STRM_CONTAINER_PATH: "容器内挂载点（.strm 文件在容器内的根路径），默认 /strm",
}

_MAX_DIR_PATH_LENGTH = 1024


def _raw(db: Session, key: str, default: str = "") -> str:
    """统一热读（只许这一套）：短 TTL 缓存，保存时失效"""
    return store.get_value(db, key, default)


def enabled(db: Session) -> bool:
    """热读 strm_enabled：缺省 true；非法值按默认值 True 处理（升级前 .strm 一直启用）"""
    value = _raw(db, CONFIG_STRM_ENABLED, "true").strip().lower()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off", ""):
        return False
    return DEFAULT_STRM_ENABLED


def normalize_dir_path(raw: object, default: str) -> str:
    """读路径用的宽松归一化：永不抛异常，非法输入回落 default"""
    if not isinstance(raw, str):
        return default
    value = raw.strip()
    if not value:
        return default
    value = value.replace("\\", "/")
    while "//" in value:
        value = value.replace("//", "/")
    if len(value) > 1 and value.endswith("/"):
        value = value.rstrip("/")
    if not value.startswith("/"):
        return default
    for segment in value.split("/"):
        if segment == "..":
            return default
    if len(value) > _MAX_DIR_PATH_LENGTH:
        return default
    if value == "/" and default != "/":
        # 挂载点是根目录没有意义（任何绝对路径都会命中），回落默认值
        return default
    return value


def host_dir(db: Session) -> str:
    """热读 strm_host_dir，归一化后回落默认值"""
    return normalize_dir_path(
        _raw(db, CONFIG_STRM_HOST_DIR, DEFAULT_STRM_HOST_DIR),
        DEFAULT_STRM_HOST_DIR,
    )


ENV_STRM_CONTAINER_PATH = "STRM_CONTAINER_PATH"


def env_container_path() -> str:
    """部署侧容器内挂载点：环境变量 STRM_CONTAINER_PATH（与 docker-compose 挂载同一个变量），
    非法/未设回落 /strm。只给 container_path() 当兜底用。"""
    return normalize_dir_path(os.getenv(ENV_STRM_CONTAINER_PATH, ""), DEFAULT_STRM_CONTAINER_PATH)


def container_path(db: Session) -> str:
    """容器内 .strm 挂载点的唯一事实源：后台配置 > 环境变量 STRM_CONTAINER_PATH > /strm"""
    fallback = env_container_path()
    raw = _raw(db, CONFIG_STRM_CONTAINER_PATH, "") if db is not None else ""
    return normalize_dir_path(raw, fallback)


def is_strm_path(db: Session, path: str) -> bool:
    """判断 path 是否在容器内 .strm 挂载点下（含挂载点本身）"""
    container = container_path(db)
    if not isinstance(path, str) or not path:
        return False
    normalized = normalize_dir_path(path, "")
    if not normalized:
        return False
    return normalized == container or normalized.startswith(container + "/")


def config_payload(db: Session) -> dict:
    """管理后台回显：当前值 + 默认值"""
    return {
        "enabled": enabled(db),
        "host_dir": host_dir(db),
        "container_path": container_path(db),
        "defaults": {
            "enabled": DEFAULT_STRM_ENABLED,
            "host_dir": DEFAULT_STRM_HOST_DIR,
            "container_path": DEFAULT_STRM_CONTAINER_PATH,
        },
    }


def _normalize_dir_path_strict(raw: str, *, field_label: str) -> str:
    """写路径用的严格归一化：非法输入抛 ValueError（中文提示）"""
    if not isinstance(raw, str):
        raise ValueError(f"{field_label}必须是字符串")
    value = raw.strip()
    if not value:
        raise ValueError(f"{field_label}不能为空")
    value = value.replace("\\", "/")
    while "//" in value:
        value = value.replace("//", "/")
    if len(value) > 1 and value.endswith("/"):
        value = value.rstrip("/")
    if not value.startswith("/"):
        raise ValueError(f"{field_label}必须是绝对路径（以 / 开头），不能包含 ..")
    for segment in value.split("/"):
        if segment == "..":
            raise ValueError(f"{field_label}必须是绝对路径（以 / 开头），不能包含 ..")
    if len(value) > _MAX_DIR_PATH_LENGTH:
        raise ValueError(f"{field_label}长度不能超过 {_MAX_DIR_PATH_LENGTH} 个字符")
    if value == "/":
        raise ValueError(f"{field_label}不能是根路径 /")
    return value


def _upsert(db: Session, key: str, value: str, description: str) -> None:
    """逐键 upsert SystemConfig 行（含 description）"""
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        db.add(SystemConfig(key=key, value=value, description=description))
    else:
        row.value = value
        row.description = description


def write_config(db: Session, *, enabled: bool, host_dir: str, container_path: str) -> dict:
    """校验并写入三项配置：归一化后逐键 upsert，commit 并清热缓存"""
    normalized_host_dir = _normalize_dir_path_strict(host_dir, field_label="宿主机目录")
    normalized_container_path = _normalize_dir_path_strict(container_path, field_label="容器内挂载点")

    _upsert(db, CONFIG_STRM_ENABLED, "true" if enabled else "false", DESCRIPTIONS[CONFIG_STRM_ENABLED])
    _upsert(db, CONFIG_STRM_HOST_DIR, normalized_host_dir, DESCRIPTIONS[CONFIG_STRM_HOST_DIR])
    _upsert(db, CONFIG_STRM_CONTAINER_PATH, normalized_container_path, DESCRIPTIONS[CONFIG_STRM_CONTAINER_PATH])

    db.commit()
    store.invalidate(CONFIG_STRM_ENABLED, CONFIG_STRM_HOST_DIR, CONFIG_STRM_CONTAINER_PATH)
    return config_payload(db)