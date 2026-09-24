#!/usr/bin/env python3
"""品牌契约检查：仓库里不许再出现旧品牌名（v2.30.0）

**问题**：项目改名（RoyalBot → Aetrix）这类事，一半代码叫新名、一半叫旧名时最难用——
改个站名要在两种叫法之间猜，客户端列表里出现两台同名服务器，只有一处漏改的
`EMBY_SERVER_NAME` 默认值会真的改变行为（每个客户端都要重登一次）。

这类残留**任何检查都看不见**：类型检查、导入、冒烟测试全绿，因为它只是一段字符串。
所以单独一条契约检查：仓库里（代码 / 配置 / 文档 / 脚本 / 监控）不许再出现旧品牌名。

它认三种写法：``RoyalBot``、``royalbot``（大小写不敏感）、``Royal Bot``。

**允许旧名的地方用行内注释显式放行**：``brand-scan: allow``（附一句为什么）。
放行要写成注释，而不是把名字改得更像新名——契约检查的价值就在于让
「这里为什么还留着旧名」成为一个需要解释的决定。目前只有一处真的需要：
老部署的 SQLite 库文件名（改品牌不该让人丢数据，见 ``backend/database.py``）。

**整文件豁免**：发布说明与历史（``README.md``、``CHANGELOG.md``）本来就该写着
「以前叫什么」，它们是记录而不是残留；本脚本自身也豁免（它包含这个旧名）。

豁免按「整文件」给是**有代价的**：被豁免的文件里任何一处旧名都不会再被看见，
所以名单要尽量短——曾经豁免过一份 ``README-old.md``（被 README 瘦身时留下的历史快照），
但它与 ``CHANGELOG.md`` 重复、又没人引用，删除后少一个需要解释的例外。

用法：python3 scripts/check_branding.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 依赖、构建产物、缓存、历史快照不进判定
SKIP_DIRS = frozenset({
    ".git", "node_modules", "dist", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "build", ".venv", "venv", "htmlcov",
})

# 不按文本读的文件
SKIP_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz", ".pdf", ".zip", ".gz",
    ".tar", ".tgz", ".7z", ".rar", ".mp4", ".mkv", ".mp3", ".woff", ".woff2", ".ttf",
    ".eot", ".so", ".dylib", ".dll", ".exe", ".pyc", ".db", ".sqlite", ".sqlite3",
    ".db-wal", ".db-shm", ".wal", ".shm", ".bin", ".class", ".jar",
})

# 发布说明与历史：这里出现旧名是记录，不是残留
SKIP_FILES = frozenset({
    "README.md", "CHANGELOG.md",
    "scripts/check_branding.py",  # 本脚本（旧名是它的判定条件）
})

MAX_FILE_BYTES = 512 * 1024

ALLOW_MARKER = "brand-scan: allow"

OLD_NAMES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("RoyalBot", re.compile(r"royal[\s_-]*bot", re.IGNORECASE)),
)


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in SKIP_FILES:
            continue
        if set(path.relative_to(root).parts[:-1]) & SKIP_DIRS:
            continue
        if path.name in SKIP_SUFFIXES or path.name.endswith(tuple(SKIP_SUFFIXES)):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def scan_file(path: Path, root: Path) -> list[str]:
    """扫一个文件，返回判定结果（给测试单独调用）"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    rel = path.relative_to(root).as_posix()
    out: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for label, pattern in OLD_NAMES:
            if pattern.search(line):
                out.append(f"{rel}:{lineno}  [{label}] {line.strip()[:80]}")
                break
    return out


def scan(root: Path | None = None) -> list[str]:
    target = root or ROOT
    found: list[str] = []
    for path in _iter_files(target):
        found.extend(scan_file(path, target))
    return found


def main() -> int:
    found = scan(ROOT)
    if found:
        print(f"❌ 发现 {len(found)} 处旧品牌名残留（统一到 Aetrix）：")
        for item in found:
            print(f"   {item}")
        print("\n改法：改成新名；确实要保留旧名（例如老部署的库文件名 / 迁移兼容）"
              f"就在同一行写 `{ALLOW_MARKER}` 并说明原因。")
        return 1
    print("✅ 未发现旧品牌名残留")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
