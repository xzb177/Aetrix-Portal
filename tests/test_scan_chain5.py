import os
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest

# 被测函数 Phase 2 才实现：import 失败时整个模块 skip，不要 collect 报错
scanner = pytest.importorskip("backend.emby_server.scanner")
try:
    _need_refresh = scanner._ext_subtitles_need_refresh
except AttributeError:
    pytest.skip("scanner._ext_subtitles_need_refresh 尚未实现（Phase 2）",
                allow_module_level=True)


def test_both_empty_returns_false():
    result = _need_refresh([], set())
    assert result is False


def test_new_subtitles_returns_true():
    result = _need_refresh([("chi", "/a.srt")], set())
    assert result is True


def test_stale_db_rows_returns_true():
    result = _need_refresh([], {"/old.srt"})
    assert result is True


def test_unchanged_still_returns_true():
    result = _need_refresh([("chi", "/a.srt")], {"/a.srt"})
    assert result is True


def test_none_external_ok():
    try:
        result = _need_refresh(None, set())
    except Exception as exc:  # pragma: no cover - 防御性断言
        pytest.fail(f"_need_refresh(None, set()) 抛出异常: {exc!r}")
    assert result is False


def test_none_db_paths_ok():
    try:
        result = _need_refresh([], None)
    except Exception as exc:  # pragma: no cover - 防御性断言
        pytest.fail(f"_need_refresh([], None) 抛出异常: {exc!r}")
    assert result is False

