#!/usr/bin/env python3
"""版本号一致性门禁：根目录 VERSION 是唯一事实来源

以前版本号散在 ``backend/main.py``、``emby_api/main.py`` 和两个前端 ``package.json``
四处，改一处就漂一处——``/api/health`` 报 2.33、CHANGELOG 已经 2.34，谁也不知道
线上跑的是哪个。现在以 ``VERSION`` 为准，本脚本保证其余地方不会偷偷分叉。

检查项：

1. ``VERSION`` 存在且是形如 ``2.34.0`` 的版本号；
2. 两个前端的 ``package.json`` 与 ``package-lock.json`` 都和它一致；
3. 后端不残留硬编码版本号（应当改为从 ``backend.version`` 读取）。

退出码 0 = 一致；1 = 有漂移。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# 这些文件里不该再出现写死的 "x.y.z" 版本号
BACKEND_FILES = ("backend/main.py", "emby_api/main.py")
# 允许出现的注释（历史说明 / 变更记录），不是运行版本
COMMENT_VERSION = re.compile(r"#.*\d+\.\d+\.\d+|v\d+\.\d+\.\d+")


def read_version() -> str:
    if not VERSION_FILE.is_file():
        return ""
    for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            return line
    return ""


def main() -> int:
    problems: list[str] = []
    version = read_version()
    if not version:
        problems.append("根目录 VERSION 不存在或为空")
    elif not SEMVER.match(version):
        problems.append(f"VERSION 内容 {version!r} 不是形如 2.34.0 的版本号")

    if version:
        for rel in ("user_frontend/package.json", "admin_frontend/package.json",
                    "user_frontend/package-lock.json", "admin_frontend/package-lock.json"):
            path = ROOT / rel
            if not path.is_file():
                problems.append(f"{rel} 不存在")
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"{rel} 不是合法 JSON：{exc}")
                continue
            got = data.get("version")
            root_pkg = (data.get("packages") or {}).get("", {}).get("version")
            if got != version:
                problems.append(f"{rel} version={got!r}，应为 {version!r}")
            if root_pkg is not None and root_pkg != version:
                problems.append(f"{rel} packages[\"\"].version={root_pkg!r}，应为 {version!r}")

    # 后端不允许再写死版本号：应当用 app_version()
    for rel in BACKEND_FILES:
        path = ROOT / rel
        if not path.is_file():
            problems.append(f"{rel} 不存在")
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or COMMENT_VERSION.search(stripped):
                continue
            # 形如 version="2.34.0" / EA_VERSION = "2.34.0" 这类硬编码
            if re.search(r'(version|EA_VERSION)\s*[:=]\s*["\']\d+\.\d+\.\d+["\']', stripped):
                problems.append(
                    f"{rel}:{lineno} 写死了版本号，请改用 backend.version.app_version()：{stripped[:80]}"
                )

    if problems:
        print("❌ 版本号不一致：")
        for item in problems:
            print("   -", item)
        print()
        print(f"修法：把根目录 VERSION 设为目标版本，并让各处都读它（当前 {version or '缺失'}）。")
        return 1

    print(f"✅ 版本号一致：{version}（VERSION / 两个前端 package.json + lock / 后端均已对齐）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
