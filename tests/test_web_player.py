"""轻量 Web 播放页（web_player/）的测试。

借鉴 go-emby 的"契约校验"思路：允许前端大改，但 CI 用 grep 钉住
与后端的 API 契约（登录/Views/Items/PlaybackInfo/图片/直链），
契约丢了测试就红。
"""
import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTML = REPO / "web_player" / "index.html"
EA_MAIN = REPO / "emby_api" / "main.py"

# 前端必须调用的后端契约（改后端接口名时同步改这里）
CONTRACT_MARKERS = [
    "/emby/Users/AuthenticateByName",  # 登录
    "/emby/Users/me/Views",            # 媒体库列表
    "/emby/Users/me/Items",            # 海报墙/搜索
    "/emby/Shows/",                    # 季/集
    "PlaybackInfo",                    # 播放信息
    "DirectStreamUrl",                 # 302 直链字段
    "/Images/Primary",                 # 海报
    "X-Emby-Token",                    # 鉴权头
]


def _html() -> str:
    assert HTML.is_file(), "web_player/index.html 不存在"
    return HTML.read_text(encoding="utf-8")


def test_html_exists_and_not_empty():
    h = _html()
    assert len(h) > 5000, "index.html 太小，可能没写完"
    assert h.lstrip().startswith("<!DOCTYPE html>")


def test_api_contract_markers():
    """契约：HTML 里必须出现这些后端接口标记，丢一个就红。"""
    h = _html()
    missing = [m for m in CONTRACT_MARKERS if m not in h]
    assert not missing, f"前端丢了后端契约: {missing}"


def test_lazy_loading_images():
    """海报墙图片必须懒加载（go-emby 式图片策略）。"""
    h = _html()
    assert 'loading="lazy"' in h
    assert 'decoding="async"' in h


def test_thumbnail_size_params():
    """按场景请求精确尺寸：墙用小图、backdrop 用大图。"""
    h = _html()
    assert "maxWidth=" in h


def test_no_hardcoded_libraries():
    """功能只提供能力：库名必须从 Views API 取，不能写死具体库名。"""
    h = _html()
    code = re.sub(r"<!--.*?-->", "", h, flags=re.S)
    for bad in ["动漫", "国产剧", "欧美剧", "演唱会"]:
        assert bad not in code, f"HTML 里写死了库名: {bad}"


def test_xss_escaping():
    """媒体名插值必须经过 esc() 转义。"""
    h = _html()
    assert "const esc" in h or "function esc" in h
    assert "esc(it.Name)" in h


def test_watch_route_registered():
    """EA 必须挂载 /watch 路由（静态 AST 检查）。"""
    src = EA_MAIN.read_text(encoding="utf-8")
    tree = ast.parse(src)
    paths = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "get":
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        paths.append(dec.args[0].value)
    assert "/watch" in paths, f"/watch 路由未注册"
    assert "/watch/" in paths


def test_watch_route_serves_web_player_dir():
    src = EA_MAIN.read_text(encoding="utf-8")
    assert "_WEB_PLAYER_DIR" in src
    assert "web_player" in src
