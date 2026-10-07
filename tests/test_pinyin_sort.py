# -*- coding: utf-8 -*-
"""拼音首字母排序测试（对标 StrmAssistant #12）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.emby_server.pinyin_sort import make_sort_name, pinyin_initials


def test_chinese_pinyin_initials():
    # 长津湖 → zjh
    assert pinyin_initials("长津湖") == "zjh"
    # 肖申克的救赎 → xskdjs（赎=shu→s）
    assert pinyin_initials("肖申克的救赎") == "xskdjs"


def test_english_unchanged():
    assert pinyin_initials("The Shawshank Redemption") == "the shawshank redemption"


def test_mixed():
    # 混合：中文取首字母，非中文保留
    result = pinyin_initials("复仇者联盟4")
    assert result.startswith("fczlm")


def test_empty():
    assert pinyin_initials("") == ""
    assert pinyin_initials(None) == ""
    assert make_sort_name("") == ""


def test_make_sort_name_chinese():
    assert make_sort_name("长津湖") == "zjh"


def test_make_sort_name_english():
    assert make_sort_name("Inception") == "inception"
