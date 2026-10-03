"""转码 / HLS 路径（video_hls）的线路处理回归测试

## 起因
``video_hls``（转码那条路，客户端拿 ``master.m3u8`` 走 HLS 时用的就是它）
**从头到尾没有看过 ``get_play_line``** —— 除了本地缓存线路那条特判。

于是两个后果：

1. **统计说谎**：用户明明选了中转线路，转码请求却被记成默认线路。面板上
   「代理中转」永远是 0，运维会以为没人用中转 —— 从面板看就像「切换没生效」。
2. **CDN 未启用时的退化没有记录**：选了 cdn 但管理员没开 CDN，
   播放路径会记一条「降级 + 原因」，转码路径不记。

（注：这里的“默认线路”在 302 直连下线后是 relay；用例里仍用 monkeypatch 直接
指定线路值，验证的是「记的是用户选的那条」这个口径本身。）

（本文件最初还怀疑「转码把源站凭据丢了」，实测 ``start_transcode`` 确实带着
``input_headers`` 走到 ffmpeg 的 ``-headers``，那个猜测是错的；
对应的用例保留下来当回归护栏。）

全部用 monkeypatch 桩，不碰网络、不碰生产库。
"""
import asyncio
from types import SimpleNamespace

import pytest

from backend.emby_server.play_line import LINE_CACHE, LINE_CDN, LINE_RELAY


class _StopAtTranscode(Exception):
    """在 start_transcode 处停下：再往下就是拼播放列表，与线路判定无关"""


def _request(query: str = ""):
    from starlette.requests import Request

    scope = {
        "type": "http", "method": "GET", "path": "/videos/item/master.m3u8",
        "raw_path": b"/videos/item/master.m3u8", "query_string": query.encode(),
        "headers": [], "scheme": "http", "server": ("testserver", 80),
        "client": ("testclient", 50000), "root_path": "",
    }
    return Request(scope)


@pytest.fixture()
def harness(monkeypatch):
    """把 video_hls 起转码之前的所有外部依赖都桩掉，并收集线路判定结果"""
    from backend.emby_server import api
    from backend.emby_server.mounts import PlayTarget

    state = SimpleNamespace(
        recorded=[], transcode_args=None, enqueued=[],
        target=PlayTarget("url", "https://origin.example/movie.mkv",
                          {"Authorization": "Basic c2VjcmV0"}),
    )

    monkeypatch.setattr(api, "_require_item",
                        lambda db, item_id: SimpleNamespace(container="mp4", guid="g1"))
    monkeypatch.setattr(api, "ensure_playback_allowed", lambda db, user: None)
    monkeypatch.setattr(api.playback_policy, "ensure_client_allowed",
                        lambda db, user, ua: None)
    monkeypatch.setattr(api.playback_policy, "ensure_transcode_allowed",
                        lambda db, user, **kw: None)
    monkeypatch.setattr(api.playback_policy, "clamp_bitrate_kbps",
                        lambda db, v: v or 0)
    monkeypatch.setattr(api.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(api, "_api_key_for", lambda db, request: "k")
    monkeypatch.setattr(api, "_play_target", lambda db, item: state.target)
    monkeypatch.setattr(api.cdn, "enabled", lambda db: False)
    monkeypatch.setattr(api.cdn, "rewrite_url", lambda db, url, base: url)
    monkeypatch.setattr(api.local_cache, "lookup", lambda db, item: None)
    monkeypatch.setattr(api.local_cache, "enqueue",
                        lambda db, item, prio: state.enqueued.append(item))
    monkeypatch.setattr(
        api.line_stats, "record_request",
        lambda line, **kw: state.recorded.append((line, kw)),
    )

    def fake_start_transcode(url, start, bitrate, height, **kw):
        state.transcode_args = dict(source=url, start=start, bitrate=bitrate,
                                    height=height, **kw)
        raise _StopAtTranscode()

    monkeypatch.setattr(api, "start_transcode", fake_start_transcode)
    return api, state


def _run(api, user=SimpleNamespace(id=7)):
    with pytest.raises(_StopAtTranscode):
        asyncio.run(api.video_hls("item", "master.m3u8", _request(), user, object()))


# ==================== 1. 选中的线路必须被记录 ====================


def test_relay_line_is_recorded_on_transcode(harness, monkeypatch):
    """选了中转线路：这条转码请求必须记在 relay 头上，而不是记成直连"""
    api, state = harness
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_RELAY)

    _run(api)

    assert [line for line, _ in state.recorded] == [LINE_RELAY], (
        f"转码路径忽略了线路选择，实际记成 {[l for l, _ in state.recorded]}")


def test_relay_line_is_recorded_on_transcode(harness, monkeypatch):
    """中转线路（当前默认）在转码路径上要记成 relay，而不是别的线。"""
    api, state = harness
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_RELAY)

    _run(api)

    assert [line for line, _ in state.recorded] == [LINE_RELAY]


def test_cache_miss_still_records_cache_as_degraded(harness, monkeypatch):
    """本地缓存没命中：记「缓存降级」，实际承载的是回源（口径不能被本次修复带偏）"""
    api, state = harness
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_CACHE)

    _run(api)

    lines = [line for line, _ in state.recorded]
    assert LINE_CACHE in lines
    assert state.enqueued, "缓存未命中时仍要排进缓存队列"


# ==================== 2. 转码拉流必须带凭据 ====================


def test_transcode_input_carries_source_credentials(harness, monkeypatch):
    """回归护栏：ffmpeg 是**外部进程**，没有本服务的会话，
    源站凭据只能靠 ``input_headers`` → ffmpeg ``-headers`` 这一处透传。

    写这个用例时怀疑过这里丢过凭据（那样中转线路在转码路径上就完全拉不到
    流）。实测当前实现是带上的，所以它现在是护栏而不是修复。
    """
    api, state = harness
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_RELAY)

    _run(api)

    assert state.transcode_args is not None
    assert state.transcode_args["input_headers"] == state.target.headers, (
        "转码拉流的凭据头丢了，ffmpeg 会裸奔去源站要流")


def test_transcode_input_headers_empty_when_source_has_none(harness, monkeypatch):
    """源站本来就没有凭据时，不要凭空塞一个空字典以外的噪声（保持既有形状）"""
    from backend.emby_server.mounts import PlayTarget

    api, state = harness
    state.target = PlayTarget("url", "https://origin.example/public.mkv", {})
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_RELAY)

    _run(api)

    assert state.transcode_args["input_headers"] in ({}, None)


# ==================== 3. CDN 未启用时的退化 ====================


def test_cdn_line_without_cdn_enabled_is_recorded_as_degraded(harness, monkeypatch):
    """选了 CDN 但管理员没开：记「CDN 降级 + 原因」，实际承载的是回源。
    与 video_stream 里 cache 未命中的处理口径一致。"""
    api, state = harness
    monkeypatch.setattr(api.play_line, "get_play_line", lambda db, uid: LINE_CDN)
    monkeypatch.setattr(api.cdn, "enabled", lambda db: False)

    _run(api)

    recorded = dict(state.recorded)
    assert LINE_CDN in recorded, "选中的线路本身必须留下记录"
    assert recorded[LINE_CDN].get("degraded"), "未启用的降级必须带上原因"
    assert LINE_RELAY in recorded, "实际承载回源的那条线也要记一笔"