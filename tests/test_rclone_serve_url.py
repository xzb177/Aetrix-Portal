"""rclone 数据面走 serve http（VFS 缓存）时的取流 URL 构造。

背景：`rcd --rc-serve` 取流**不经过 VFS 层**（rclone 1.71.1 的 rcd 连
`--vfs-cache-mode` 这个 flag 都没有），所以经 rcd 取的每个 Range 请求都是冷读，
而 Drive 每次 Range 读有约 1.2 秒固定往返。改用 `rclone serve http`（带 VFS
缓存）后，读过的区间落本地，重复读从 1.2s 降到毫秒级。

这里钉住三件容易错的事：

1. **两种端点的 URL 形态不一样**，混用就是 404 且极难定位：
     rc-serve ： ``http://rclone:5572/[MP:]/MoviePilot/x.mkv``（remote 套方括号）
     serve http： ``http://rclone:8080/MoviePilot/x.mkv``    （remote 直接挂根）
2. **控制面仍然走 rc_url**（列目录 /operations/list 等），只有媒体字节走 serve_url。
3. **向后兼容**：不填 serve_url 时行为与改动前逐字一致。
"""
import types

import pytest

from backend.emby_server import mount_rclone
from backend.emby_server.mount_rclone import RcloneMount


def _mount(**cfg):
    """构造一个最小可用的 RcloneMount（跳过真实校验）"""
    base = {
        "mode": "rc",
        "rc_url": "http://rclone:5572",
        "fs": "MP:",
        "rc_user": "u",
        "rc_pass": "p",
    }
    base.update(cfg)
    m = RcloneMount.__new__(RcloneMount)
    m.rc_url = (cfg.get("rc_url") or "http://rclone:5572").strip().rstrip("/")
    m.serve_url = (cfg.get("serve_url") or "").strip().rstrip("/")
    m.fs = base["fs"]
    m.rc_user = "u"
    m.rc_pass = "p"
    m._require_fs = lambda: base["fs"]
    return m


class TestRcServeUrlUnchanged:
    """不填 serve_url：必须与旧行为完全一致"""

    def test_default_keeps_bracket_form(self):
        m = _mount()
        assert m._rc_play_url("MoviePilot/音乐片/a.mkv") == \
            "http://rclone:5572/[MP:]/MoviePilot/%E9%9F%B3%E4%B9%90%E7%89%87/a.mkv"

    def test_serve_url_empty_is_treated_as_unset(self):
        """空串 / 只有空白 都等于没配，不能拼出 `http://rclone:8080//...`"""
        for blank in ("", "   ", None):
            m = _mount(serve_url=blank)
            assert "[MP:]" in m._rc_play_url("a.mkv"), f"serve_url={blank!r} 不该改变行为"

    def test_root_path(self):
        m = _mount()
        assert m._rc_play_url("") == "http://rclone:5572/[MP:]/"


class TestServeHttpUrl:
    """填了 serve_url：走 serve http，**不带**方括号"""

    def test_no_bracket_in_serve_url(self):
        m = _mount(serve_url="http://rclone:8080")
        url = m._rc_play_url("MoviePilot/音乐片/a.mkv")
        assert url == "http://rclone:8080/MoviePilot/%E9%9F%B3%E4%B9%90%E7%89%87/a.mkv"
        assert "[MP:]" not in url, "serve http 的 URL 不能带方括号，否则 404"

    def test_trailing_slash_normalised(self):
        m = _mount(serve_url="http://rclone:8080/")
        assert m._rc_play_url("a.mkv") == "http://rclone:8080/a.mkv"
        assert "//" not in m._rc_play_url("a.mkv").replace("://", "")

    def test_remote_root(self):
        m = _mount(serve_url="http://rclone:8080")
        assert m._rc_play_url("") == "http://rclone:8080/"

    def test_no_remote_name_in_path(self):
        """`serve http MP:` 把 remote 挂在**站点根**，路径里不能再出现 remote 名。

        带 /MP/ 前缀会 404（线上实测），不带才是 206。这条钉住最容易写错的点。
        """
        m = _mount(serve_url="http://rclone-serve:8080")
        url = m._rc_play_url("MoviePilot/音乐片/a.mkv")
        assert url == "http://rclone-serve:8080/MoviePilot/%E9%9F%B3%E4%B9%90%E7%89%87/a.mkv"
        assert "/MP/" not in url, "serve http 已经把 remote 挂在根上，再加 /MP/ 就 404"
        assert "MP:" not in url, "路径里不能带 remote 的尾冒号"

    def test_unicode_path_is_percent_encoded(self):
        m = _mount(serve_url="http://rclone:8080")
        url = m._rc_play_url("音乐片/梅艳芳 (2021).mkv")
        assert " " not in url, "空格必须编码，否则 serve http 会 404"
        assert "%20" in url and "%E6%A2%85" in url


class TestControlPlaneUnaffected:
    """控制面（列目录/查状态）不受影响，仍走 rc_url"""

    def test_list_still_uses_rc_url(self, monkeypatch):
        seen = {}

        def fake_call(rc_url, path, payload=None, **kw):
            seen["rc_url"] = rc_url
            seen["path"] = path
            return {"list": [{"Name": "a.mkv", "Path": "a.mkv", "Size": 1, "IsDir": False}]}

        monkeypatch.setattr(mount_rclone, "rc_call", fake_call)
        # _rc_list_items 是模块级函数，rc_url 由调用方传入
        items = mount_rclone._rc_list_items("http://rclone:5572", "MP:", "MoviePilot/音乐片")
        assert items and items[0]["Name"] == "a.mkv"
        assert seen["rc_url"] == "http://rclone:5572", "控制面不能被 serve_url 带偏"
        assert seen["path"] == "/operations/list"


class TestAuthHeaders:
    """取流仍带 Basic 认证（serve http 配了 --user/--pass，没带会 401）"""

    def test_headers_contain_basic_auth(self):
        m = _mount(serve_url="http://rclone:8080")
        h = m._rc_headers()
        assert h["Authorization"].startswith("Basic ")

    def test_no_auth_header_without_credentials(self):
        m = _mount(serve_url="http://rclone:8080")
        m.rc_user = ""
        m.rc_pass = ""
        assert "Authorization" not in m._rc_headers()
