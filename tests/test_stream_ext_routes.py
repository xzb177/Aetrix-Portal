"""EA 带扩展名的直接流路由（/stream.mkv /stream.mp4）版本化测试。

背景：iOS 客户端（Lenna/SenPlayer）请求播放时 URL 带扩展名，
如 /emby/videos/{id}/stream.mkv。若无此路由，请求会被
/{transcode_path:path}（HLS catch-all）误接收，导致 ffmpeg 误启动。
"""
import asyncio
import inspect

import pytest

from backend.emby_server import api


EXPECTED_ROUTES = [
    "/emby/videos/{item_id}/stream.mkv",
    "/emby/videos/{item_id}/stream.mp4",
    "/emby/Videos/{item_id}/stream.mkv",
    "/emby/Videos/{item_id}/stream.mp4",
]

CATCH_ALL_ROUTES = [
    "/emby/videos/{item_id}/{transcode_path:path}",
    "/videos/{item_id}/{transcode_path:path}",
]


def _route_paths():
    return [getattr(r, "path", "") for r in api.emby_router.routes]


def test_all_four_extension_routes_registered():
    paths = _route_paths()
    for expected in EXPECTED_ROUTES:
        assert expected in paths, f"路由缺失: {expected}"


def test_extension_routes_defined_before_catch_all():
    """FastAPI 按定义顺序匹配：扩展名路由必须在 /{transcode_path:path} 之前。"""
    paths = _route_paths()
    for ext in EXPECTED_ROUTES:
        ext_idx = paths.index(ext)
        for catch in CATCH_ALL_ROUTES:
            if catch in paths:
                assert ext_idx < paths.index(catch), (
                    f"{ext} 必须在 {catch} 之前定义，否则会被 HLS catch-all 抢走"
                )


def test_video_stream_ext_signature_matches_video_stream():
    """video_stream_ext 参数签名必须与 video_stream 一致（透传不丢参）。"""
    ext_params = list(inspect.signature(api.video_stream_ext).parameters)
    stream_params = list(inspect.signature(api.video_stream).parameters)
    assert ext_params == stream_params, (
        f"签名不一致: video_stream_ext={ext_params}, video_stream={stream_params}"
    )


def test_video_stream_ext_delegates_to_video_stream(monkeypatch):
    """video_stream_ext 必须把全部参数原样透传给 video_stream。"""
    calls = []

    async def fake_video_stream(item_id, request, user, db):
        calls.append((item_id, request, user, db))
        return "STREAM_RESULT"

    monkeypatch.setattr(api, "video_stream", fake_video_stream)

    sentinel_request, sentinel_user, sentinel_db = object(), object(), object()
    result = asyncio.run(
        api.video_stream_ext("item123", sentinel_request, sentinel_user, sentinel_db)
    )

    assert result == "STREAM_RESULT"
    assert calls == [("item123", sentinel_request, sentinel_user, sentinel_db)]
