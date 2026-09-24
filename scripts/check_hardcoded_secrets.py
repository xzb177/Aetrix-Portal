#!/usr/bin/env python3
"""硬编码密钥契约检查：仓库里不许出现「像真的」的密钥。

起因是**真实发生过的**一次事故：`scripts/check_emby_sync.sh` 在公开仓库里写死了一个
Emby API Key 与生产域名（`EMBY_API_KEY="af3f…"`、`https://emby.<生产域名>`），
而这个仓库是 public 的——密钥一旦进过 Git 历史，就等于已经泄露，只能作废重发。

脚本、测试、文档这类「顺手的边角文件」是硬编码凭据的高发地：它们不进主流程，
代码评审最容易跳过，而一旦提交就无法收回。类型检查、导入、其它护栏都看不见它们，
所以这里单独加一条契约检查。

它认两类东西：

1. **有厂商前缀的密钥**（结构上不可能是别的意思）：AWS `AKIA…`、OpenAI/Stripe
   `sk-…`、GitHub `ghp_…` / `github_pat_…`、Slack `xox…`、Google `AIza…`、
   Telegram 机器人 token（`<数字>:<base64>`）、`-----BEGIN … PRIVATE KEY-----`、
   字面量 JWT（`eyJ….….…`）、`X-Emby-Token:` 后面的 32 位十六进制。
2. **赋值形式的疑似密钥**：`API_KEY = "<16 位以上、看着随机>"` 这类。
   判定要求值里**同时有数字和字母**（纯单词不算，`emby-client-token-alice` 这种
   测试夹具不会被误报），且不是明显的占位串（example / your- / changeme / ***…）。

被判定为占位的地方，用行内注释显式放行：`secret-scan: allow`（附一句为什么）。
**放行要写成注释**，而不是把值改得更像一个真密钥——契约检查的价值就在于让
「这是假值」成为一个需要解释的决定。

用法：python3 scripts/check_hardcoded_secrets.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 这些目录不进判定：依赖、构建产物、缓存、历史
SKIP_DIRS = frozenset({
    ".git", "node_modules", "dist", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "build", ".venv", "venv", "htmlcov",
})

# 不按文本读的文件（体积大 / 二进制）
SKIP_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz", ".pdf", ".zip", ".gz",
    ".tar", ".tgz", ".7z", ".rar", ".mp4", ".mkv", ".mp3", ".woff", ".woff2", ".ttf",
    ".eot", ".so", ".dylib", ".dll", ".exe", ".pyc", ".db", ".sqlite", ".sqlite3",
    ".db-wal", ".db-shm", ".wal", ".shm", ".bin", ".class", ".jar",
})

# 单个文件超过这个大小就不读（产线数据库、日志残留等）
MAX_FILE_BYTES = 512 * 1024

# 行内放行标记（三种注释语法都认）
ALLOW_MARKER = "secret-scan: allow"

# 明显的占位值：出现这些片段就不算密钥
PLACEHOLDER_HINTS = (
    "example", "sample", "placeholder", "changeme", "change_me", "change-me",
    "your_", "your-", "yours", "redacted", "dummy", "fake", "dummy", "test",
    "xxxx", "****", "secret-scan", "os.getenv", "process.env", "env.", "<", ">",
    "${", "{{", "none", "null", "todo", "swordfish", "abcdef0123",
)

# 变量名里出现这些词 + 值看着随机 → 判定为硬编码密钥
SECRET_NAMES = (
    r"api[_-]?key", r"apikey", r"secret(?:[_-]?key)?", r"access[_-]?token",
    r"refresh[_-]?token", r"auth[_-]?token", r"bearer[_-]?token", r"partner[_-]?key",
    r"private[_-]?key", r"client[_-]?secret", r"app[_-]?secret", r"password",
    r"passwd", r"passphrase", r"sign[_-]?key", r"panel[_-]?key", r"node[_-]?key",
    r"license[_-]?key", r"webhook[_-]?secret", r"cookie",
)

ASSIGN_RE = re.compile(
    rf"(?i)(?:{ '|'.join(SECRET_NAMES) })\s*[:=]\s*[\"']([^\"'\s]{{16,}})[\"']"
)

# 厂商前缀 / 结构性特征：命中即报，不看变量名
VENDOR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS Access Key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("OpenAI / Stripe 密钥", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Stripe 正式密钥", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{16,}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Telegram 机器人 token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b")),
    ("私钥文件内容", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("字面量 JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("Emby API Key / X-Emby-Token", re.compile(r"(?i)\bx-emby-token\s*[\"']?\s*[:=]\s*[\"']?([0-9a-f]{32})\b")),
)

findings: list[str] = []


def _is_placeholder(value: str) -> bool:
    """值是否明显是占位 / 假值（纯单词、重复字符、含提示词）"""
    lowered = value.lower()
    if any(hint in lowered for hint in PLACEHOLDER_HINTS):
        return True
    # 少于 3 种字符（aaaaaaaa…、0000…）明显是填充
    if len(set(lowered)) < 3:
        return True
    # 纯字母单词（可以带 - / _ / . 分隔）：测试夹具常见，如 emby-client-token-alice
    if re.fullmatch(r"[A-Za-z]+(?:[-_.][A-Za-z]+)*", value):
        return True
    return False


def _looks_random(value: str) -> bool:
    """值是否「像密钥」：够长，且同时有字母与数字（随机串的基本特征）"""
    if len(value) < 16:
        return False
    has_digit = any(ch.isdigit() for ch in value)
    has_alpha = any(ch.isalpha() for ch in value)
    return has_digit and has_alpha


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts[:-1])
        if parts & SKIP_DIRS:
            continue
        name = path.name
        if name.endswith(tuple(SKIP_SUFFIXES)):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def scan_file(path: Path, root: Path) -> list[str]:
    """扫一个文件，返回该文件里的判定结果（给测试单独调用）"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    rel = path.relative_to(root).as_posix()
    out: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for label, pattern in VENDOR_PATTERNS:
            match = pattern.search(line)
            if match:
                hit = match.group(match.lastindex or 0)
                if not _is_placeholder(hit):
                    out.append(f"{rel}:{lineno}  [{label}] {hit[:12]}…")
        for value in ASSIGN_RE.findall(line):
            if _is_placeholder(value) or not _looks_random(value):
                continue
            out.append(f"{rel}:{lineno}  [疑似硬编码密钥] {value[:6]}…（{len(value)} 位）")
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
        print(f"❌ 发现 {len(found)} 处疑似硬编码密钥（公开仓库里等于已泄露）：")
        for item in found:
            print(f"   {item}")
        print("\n改法：从环境变量 / .env 读取；确认是假值就写行内注释 "
              f"`{ALLOW_MARKER}` 并说明原因。")
        return 1
    print("✅ 未发现硬编码密钥")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
