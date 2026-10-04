"""Rex deep link 生成规则（追新日历点击跳转）

为什么值得测：这几行看着像 `||`，但**剧集条目是最容易悄悄坏掉的一类**——
TMDB 里剧集 id 与单集 id 是两套编号，`rex://tmdb?type=tv` 只认剧集的 id。
填错了不会报错，只会「点了没反应」，属于用户不会报障的那类坑。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest

# 这份规则活在 TS 里，但跑在只装了 Python 的 CI job 里。用 node 现算它，而不是
# 另写一份 Python 翻译——两份实现必然漂移，漂移了就等于没测。
# 没有 node 就整体跳过，而不是让后端 job 因为一个可选工具红掉。
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="需要 node 才能执行 TS 源"
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "user_frontend/src/utils/rexDeepLink.ts"


def _call(item: dict) -> str:
    """跑一次 TS 源：用 node 剥掉类型标注后求值（不引入构建工具依赖）"""
    body = SRC.read_text(encoding="utf-8")
    # 去掉类型标注与 import/export，保留可执行的 JS 语义
    body = re.sub(r"^import .*$", "", body, flags=re.M)
    body = body.replace("export function", "function")
    body = re.sub(r"^type ItemLike = \{.*?^\}$", "", body, flags=re.M | re.S)
    body = re.sub(r"\): string \{", ") {", body)
    body = re.sub(r"\(item: ItemLike\)", "(item)", body)
    body = re.sub(r"^/\*\*.*?^\*/$", "", body, flags=re.M | re.S)
    payload = json.dumps(item)
    script = f"{body}\nconsole.log(rexDeepLink({payload}));"
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr[:400]
    return out.stdout.strip()


import json  # noqa: E402


def test_movie_with_tmdb_id_uses_tmdb_link():
    got = _call({"Name": "流浪地球", "Type": "Movie",
                 "ProviderIds": {"Tmdb": "335984"}})
    assert got == "rex://tmdb?id=335984&type=movie", got


def test_series_with_tmdb_id_uses_tv_link():
    got = _call({"Name": "最后生还者", "Type": "Series",
                 "ProviderIds": {"Tmdb": "100088"}})
    assert got == "rex://tmdb?id=100088&type=tv", got


def test_missing_tmdb_falls_back_to_search():
    got = _call({"Name": "无编号电影", "Type": "Movie", "ProviderIds": {}})
    assert got.startswith("rex://search?q="), got
    assert "%E6%97%A0%E7%BC%96%E5%8F%B7" in got, got


def test_provider_ids_absent_entirely():
    got = _call({"Name": "完全没刮削", "Type": "Movie"})
    # 预期值用 quote 算，不手写百分号编码（手写过一次，写错了才发现）
    assert got == "rex://search?q=" + quote("完全没刮削"), got


def test_episode_never_uses_its_own_tmdb_id():
    """剧集条目不能拿单集的 TMDB id 去 type=tv：两套编号，填了必然打不开"""
    got = _call({"Name": "第一季第一集", "Type": "Episode",
                 "SeriesName": "最后生还者",
                 "ProviderIds": {"Tmdb": "63056"}})
    assert got.startswith("rex://search?q="), got
    assert "63056" not in got, got
    assert "%E6%9C%80%E5%90%8E%E7%94%9F%E8%BF%98%E8%80%85" in got, got


def test_episode_without_series_name_falls_back_to_its_own_title():
    got = _call({"Name": "孤儿单集", "Type": "Episode"})
    assert got.startswith("rex://search?q="), got


def test_season_is_treated_like_unknown():
    """季不是日历支持的类型，真出现了也不能硬塞 type=tv"""
    got = _call({"Name": "第一季", "Type": "Season",
                 "ProviderIds": {"Tmdb": "100088"}})
    assert got.startswith("rex://search?q="), got


def test_non_numeric_tmdb_id_is_ignored():
    """脏数据里的 'N/A' 不能拼进 rex://tmdb?id=——那会让 Rex 打不开"""
    got = _call({"Name": "脏数据", "Type": "Movie", "ProviderIds": {"Tmdb": "N/A"}})
    assert got.startswith("rex://search?q="), got


def test_empty_name_still_produces_valid_link():
    got = _call({"Name": "", "Type": "Movie"})
    assert got == "rex://search?q=", got
