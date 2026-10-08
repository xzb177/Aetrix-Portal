"""分集标题美化（StrmAssistant 对标）——轻量通用能力。

纯展示层处理：API 返回分集标题时，对占位/垃圾标题做友好化。
- 不写库、不调外部 API、无后台任务、无 per-user 开关，默认生效
- 纯字符串操作，单集约微秒级，可安全用在列表接口

规则（按优先级）：
1. 名字是垃圾值（季信息串入，如 "Season 01 S01"）→ 用集号重建 "第N集"
2. 名字为空或占位符（第N集 / Episode N / S01E05）→ 尝试从文件名提取描述性标题，
   有则返回 "第N集 · 描述"，无则规范化为 "第N集"
3. 其他（已有真实标题）→ 原样返回
"""
from __future__ import annotations

import os
import re

# --- 占位符：本身不携带真实标题信息 ---
_PLACEHOLDER_RES = [
    re.compile(r"^第\s*\d+\s*集$"),                       # 第13集
    re.compile(r"^Episode\s*\d+$", re.IGNORECASE),        # Episode 13
    re.compile(r"^EP?\s*\d+$", re.IGNORECASE),            # E13 / P13
    re.compile(r"^S\d{1,2}E\d{1,3}$", re.IGNORECASE),     # S04E13
    re.compile(r"^\d+$"),                                 # 纯数字 13
]

# --- 垃圾值：扫描时季信息串入了集名 ---
_GARBAGE_RES = [
    re.compile(r"^Season\s*\d+\s*S\d+\s*$", re.IGNORECASE),  # Season 01 S01
    re.compile(r"^\d+\s*S\d+\s*$"),                          # 60 S19
]

# 文件名标签清洗（描述性标题提取用）
_TAG_RES = [
    re.compile(r"[Ss]\d{1,2}[Ee]\d{1,3}"),                       # S04E13
    re.compile(r"\b\d{1,2}x\d{1,3}\b"),                          # 4x13
    re.compile(r"\b(480|720|1080|2160)p\b", re.IGNORECASE),      # 1080p
    re.compile(r"\b(4K|UHD)\b", re.IGNORECASE),
    re.compile(r"\b(WEB-DL|WEBRip|BluRay|Blu-ray|HDTV|DVDRip|BDRip|HDRip)\b", re.IGNORECASE),
    re.compile(r"\b(x264|x265|[hH]\.?264|[hH]\.?265|HEVC|AVC|Xvid)\b"),
    re.compile(r"\b(AAC|AC3|DTS(?:-HD)?|FLAC|MP3|Opus|2Audio|DDP?\d?)\b", re.IGNORECASE),
    re.compile(r"\b(10bit|8bit|HDR\d*|DoVi|DV)\b", re.IGNORECASE),
    re.compile(r"\b(CMCTV|CMCT|FRDS|PTH|TTG|CHD|HDChina|OurTV|ZMCTV)\b", re.IGNORECASE),  # 压制组
    re.compile(r"\b\d{3,4}[Kk]\b"),                              # 2Audio 之外的码率标记
]


def _is_placeholder(name: str) -> bool:
    return any(p.match(name) for p in _PLACEHOLDER_RES)


def _is_garbage(name: str) -> bool:
    return any(p.match(name) for p in _GARBAGE_RES)


def _canonical_episode_label(episode_number) -> str | None:
    """规范化的集标签：'第N集'。集号无效时返回 None。"""
    try:
        n = int(episode_number)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return f"第{n}集"


def _extract_desc_title(file_path: str | None, series_name: str | None = None) -> str:
    """从文件名提取描述性标题（去掉剧名/SxxExx/标签后剩余的部分）。

    如 Running.Man.S04E13.1080p.mkv → ""（无描述性标题）
    如 Show.S01E05.The.Secret.Mission.1080p.mkv（series=Show）→ "The Secret Mission"
    """
    if not file_path:
        return ""
    base = os.path.basename(file_path)
    # 去扩展名
    base = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", base)
    text = base
    for pat in _TAG_RES:
        text = pat.sub(" ", text)
    # 分隔符统一为空格后分词
    tokens = [t for t in re.split(r"[\s.\-_]+", text) if t]
    if not tokens:
        return ""
    # 去掉剧名 token（忽略大小写、忽略其中的分隔符差异）
    if series_name:
        norm_series = re.sub(r"[\s.\-_]+", "", series_name).lower()
        tokens = [t for t in tokens
                  if re.sub(r"[\s.\-_]+", "", t).lower() not in (norm_series,)
                  and norm_series not in re.sub(r"[\s.\-_]+", "", t).lower()]
        # 剧名可能是多个 token（如 "Running Man"）：整体再过滤一次
        joined = " ".join(tokens)
        for sep in (" ", ".", "-", "_"):
            joined = joined.replace(sep, " ")
        # 简单处理：去掉与剧名单词重合的连续词
        series_words = {w.lower() for w in re.split(r"[\s.\-_]+", series_name) if w}
        tokens = [t for t in tokens if t.lower() not in series_words]
    # 去掉仍像占位符的 token（第N集 / 纯数字）
    tokens = [t for t in tokens
              if not re.fullmatch(r"第?\s*\d+\s*集?", t)
              and not t.isdigit()]
    return " ".join(tokens).strip()


def beautify_episode_title(name: str | None,
                           file_path: str | None = None,
                           season_number=None,
                           episode_number=None,
                           series_name: str | None = None) -> str:
    """返回展示用分集标题。输入为 DB 原始值，不修改 DB。"""
    raw = (name or "").strip()

    # 1. 垃圾值 → 用集号重建
    if raw and _is_garbage(raw):
        label = _canonical_episode_label(episode_number)
        return label or raw

    # 2. 空或占位符 → 尝试文件名提取
    if not raw or _is_placeholder(raw):
        label = _canonical_episode_label(episode_number) or raw or ""
        desc = _extract_desc_title(file_path, series_name)
        if desc:
            return f"{label} · {desc}" if label else desc
        return label

    # 3. 已有真实标题 → 原样
    return raw
