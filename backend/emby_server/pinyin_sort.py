# -*- coding: utf-8 -*-
"""拼音首字母排序（对标 StrmAssistant "Pinyin Initials Sort Title"）。

StrmAssistant 的描述："Auto generate pinyin initials as sort title"。
实现：中文标题自动生成拼音首字母作为 sort_name，用于排序，不改变显示。

例如：
- "长津湖" → "zjh"（或 "长津湖" 的首字母）
- "肖申克的救赎" → "xskdjsh"
- "The Shawshank Redemption" → "the shawshank redemption"（非中文原样小写）

与现有 sort_name 的关系：
- 扫描器原来把 sort_name 设为 name.lower()，中文标题按 Unicode 排序，
  中文全挤在一起，体验差。
- 本模块生成拼音首字母，中文标题可以按 A-Z 排序。
- 开关：PINYIN_SORT_ENABLED（默认开）。关闭则回退到 name.lower()。
"""

import logging
import os
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

PINYIN_SORT_ENABLED = (
    os.getenv("PINYIN_SORT_ENABLED", "1") or "1"
).strip().lower() not in ("0", "false", "no")

# 中文字符范围：CJK 统一表意文字
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


@lru_cache(maxsize=65536)
def pinyin_initials(name: str) -> str:
    """生成拼音首字母排序键。

    - 含中文：每个中文字符取拼音首字母，非中文字符保留原样（小写）。
    - 纯非中文：直接小写返回。
    - 空：返回空字符串。

    lru_cache：同一系列名在剧/季/集行里重复计算，去重后扫描更快。
    """
    if not name:
        return ""
    name = name.strip()
    if not name:
        return ""
    if not _has_cjk(name):
        return name.lower()
    try:
        from pypinyin import pinyin, Style
    except ImportError:
        logger.warning("pypinyin 未安装，拼音排序回退到小写")
        return name.lower()
    try:
        # 每个字符取首字母，非中文字符 pypinyin 会原样返回
        result = pinyin(name, style=Style.FIRST_LETTER)
        initials = "".join(item[0] for item in result if item and item[0])
        # 去掉非字母数字（标点/空格），保留紧凑的排序键
        initials = re.sub(r"[^a-z0-9]", "", initials.lower())
        return initials or name.lower()
    except Exception as e:
        logger.warning("拼音转换失败 %r: %s，回退到小写", name, e)
        return name.lower()


def make_sort_name(name: str) -> str:
    """生成 sort_name：拼音排序开时用拼音首字母，关时用小写。

    这是扫描器统一入口，替代原来的 `name.lower()`。
    """
    if not name:
        return ""
    if PINYIN_SORT_ENABLED and _has_cjk(name):
        return pinyin_initials(name)
    return name.lower()
