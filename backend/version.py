"""应用版本：单一版本源。

以前版本号散在 ``backend/main.py``、``emby_api/main.py`` 和两个 ``package.json`` 里，
四处各写各的，改了一处就漂移——``/api/health`` 报 2.33、CHANGELOG 已经 2.34，
管理员对着两个数字猜哪个是真的。

现在以仓库根目录的 ``VERSION`` 文件为准：

- 后端（EM / EA）启动时读它，``/api/health`` 永远反映真实版本；
- 前端两个 ``package.json`` 由 ``scripts/check_version.py`` 在 CI 里核对，
  漂了就让构建失败，而不是等到线上才发现。

镜像里 ``VERSION`` 随源码一起 ``COPY``，所以容器内外读到的是同一份。
"""
from __future__ import annotations

from pathlib import Path

#: 找不到 VERSION 时的兜底（源码被裁剪 / 只装了 backend 包时）。
FALLBACK_VERSION = "0.0.0"

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


def app_version() -> str:
    """读取根目录 VERSION，返回形如 ``2.34.0`` 的版本号。"""
    try:
        value = _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return FALLBACK_VERSION
    # 只要第一行；容忍尾随空行与注释
    for line in value.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            return line
    return FALLBACK_VERSION


__all__ = ["app_version", "FALLBACK_VERSION"]
