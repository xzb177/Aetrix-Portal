"""EA gzip 排除回归测试：JSON 不应在 Python 层压缩（防事件循环阻塞）。"""
import re


def test_json_excluded_from_gzip():
    """application/json 必须在 _GZIP_EXCLUDES 里。

    2026-10-07 压力测试：50 并发 Items（~500KB JSON）在事件循环里同步压缩，
    导致 loop lag 3.3s、EA 无响应。JSON 交给 nginx 压缩。
    """
    with open("emby_api/main.py", encoding="utf-8") as f:
        src = f.read()
    # 找到 _GZIP_EXCLUDES 定义
    m = re.search(r"_GZIP_EXCLUDES\s*=\s*\((.*?)\)", src, re.S)
    assert m, "未找到 _GZIP_EXCLUDES 定义"
    excludes = m.group(1)
    assert "application/json" in excludes, (
        "application/json 必须在 gzip 排除列表里，否则大 JSON 会在事件循环里同步压缩"
    )


def test_tracemalloc_endpoints_gated():
    """tracemalloc 调试端点必须受 TRACEMALLOC 环境变量控制，默认关闭。"""
    with open("emby_api/main.py", encoding="utf-8") as f:
        src = f.read()
    assert 'os.getenv("TRACEMALLOC", "0") == "1"' in src, "tracemalloc 必须默认关闭"
    assert "/debug/tracemalloc/top" in src, "应保留调试端点供未来排查"
