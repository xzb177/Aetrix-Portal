"""rclone RC 的 404 有两种完全不同的含义，不能一律当成「方法不存在」。

真实起因：媒体库路径配错（目录不存在）时，面板报的是

    rclone RC 没有这个接口: /operations/listfile（该 rclone 版本不提供）

把用户指去了完全错误的方向——去查 rclone 版本。根因有两层：

1. rclone 对「方法不存在」和「目录不存在」**都返 HTTP 404**，只有响应体的
   ``error`` 字段能区分：``couldn't find method "x"`` vs ``directory not found``；
2. 原来的 ``_rc_list_items`` 见到 404 就回退到 ``/operations/listfile``，
   而那个方法在 rclone 里**根本不存在**（master 的 fs/operations/rc.go
   注册的 11 个方法里没有它），于是真实原因被二次 404 彻底吞掉。

这里钉住四件事：两种 404 分得开、真实原因原样透出、回退分支不再存在、
异常继承关系不破坏调用方。

不碰网络：HTTP 层用最小 resp 替身。
"""

import pytest

from backend.emby_server import mount_rclone
from backend.emby_server.mount_rclone import MountError, _classify_404
from backend.emby_server.mounts import MountAuthError, MountMethodMissing


class _Resp:
    """最小 resp 替身：只提供 rc_call 用到的 status_code 与 json()"""

    def __init__(self, status, payload=None, raw=b""):
        self.status_code = status
        self._payload = payload
        self._raw = raw

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


# ==================== 404 分类 ====================

def test_404_method_missing_is_classified_as_method_missing():
    """rclone 说「找不到这个方法」→ 方法缺失（这才允许调用方换接口）"""
    resp = _Resp(404, {"error": 'couldn\'t find method "operations/listfile"'})
    err = _classify_404("/operations/listfile", resp)
    assert isinstance(err, MountMethodMissing)
    assert "没有这个接口" in str(err)


def test_404_directory_not_found_keeps_real_reason():
    """目录不存在 → 必须把 'directory not found' 原样透出，不能说成版本问题"""
    resp = _Resp(404, {"error": "error in ListJSON: directory not found"})
    err = _classify_404("/operations/list", resp)
    assert isinstance(err, MountError)
    assert not isinstance(err, MountMethodMissing), "目录不存在被误判成方法缺失"
    assert "directory not found" in str(err)
    assert "版本" not in str(err)


def test_404_unparsable_body_falls_back_to_method_missing():
    """响应体读不出来时按方法缺失处理：宁可多试一次，也不吞真实原因"""
    err = _classify_404("/operations/list", _Resp(404, raw=b""))
    assert isinstance(err, MountMethodMissing)


def test_404_without_reason_is_not_misreported_as_version():
    """404 但 body 里没有 error 字段时，也不能说成「该版本不提供」"""
    err = _classify_404("/operations/list", _Resp(404, {}))
    assert not isinstance(err, MountMethodMissing)
    assert "404" in str(err)


# ==================== _rc_list_items 不再有回退 ====================

def test_rc_list_items_no_longer_falls_back_to_listfile(monkeypatch):
    """列目录只调 /operations/list"""
    calls = []

    def _fake_call(rc_url, path, payload=None, **kw):
        calls.append(path)
        return {"list": [{"Path": "a.mkv", "Name": "a.mkv", "Size": 1, "IsDir": False}]}

    monkeypatch.setattr(mount_rclone, "rc_call", _fake_call)
    items = mount_rclone._rc_list_items("http://r:5572", "MP:", "dir")
    assert calls == ["/operations/list"]
    assert items and items[0]["Name"] == "a.mkv"


def test_rc_list_items_propagates_directory_not_found(monkeypatch):
    """目录不存在时原样抛出，错误信息里不再出现「版本」字样"""
    calls = []

    def _fake_call(rc_url, path, payload=None, **kw):
        calls.append(path)
        raise MountError("rclone: error in ListJSON: directory not found")

    monkeypatch.setattr(mount_rclone, "rc_call", _fake_call)
    with pytest.raises(MountError) as exc:
        mount_rclone._rc_list_items("http://r:5572", "MP:", "不存在的目录")
    assert calls == ["/operations/list"], "不应再尝试 listfile"
    assert "directory not found" in str(exc.value)
    assert "版本" not in str(exc.value)


def test_method_missing_still_usable_by_caller():
    """MountMethodMissing 是 MountError 子类，既有 except MountError 不受影响"""
    assert issubclass(MountMethodMissing, MountError)
    assert not issubclass(MountMethodMissing, MountAuthError)
