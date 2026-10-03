"""``parse_mod_ts``：远端修改时间的解析口径

追新靠 ModTime 判断「新增」，所以解析器错一个字符的后果不是报错，而是**静默漏检**。
rclone 的 ``ModTime`` 是纳秒（``...000000123Z``），Python 3.10 的 ``fromisoformat``
只收 3 或 6 位小数——直接扔过去会返回 0.0，追新就永远看不到新文件。
"""
import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend.emby_server.mounts import parse_mod_ts

_TS = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()


def test_rclone_nanosecond_precision():
    """rclone 的真实格式：纳秒。解析不了就等于追新全废。"""
    assert parse_mod_ts("2026-10-01T12:00:00.000000123Z") == _TS
    assert parse_mod_ts("2026-10-01T12:00:00.123456789Z") == _TS + 0.123456


def test_common_iso_variants():
    assert parse_mod_ts("2026-10-01T12:00:00Z") == _TS
    assert parse_mod_ts("2026-10-01T12:00:00.123Z") == _TS + 0.123
    # 1 位小数要能补齐，不能直接丢精度后报失败
    assert parse_mod_ts("2026-10-01T12:00:00.1Z") == _TS + 0.1


def test_offset_timezone_is_respected():
    assert parse_mod_ts("2026-10-01T20:00:00.123+08:00") == _TS + 0.123


def test_unparsable_degrades_to_zero():
    for bad in (None, "", "   ", "garbage", True):
        assert parse_mod_ts(bad) == 0.0


def test_numeric_passthrough():
    assert parse_mod_ts(1700000000) == 1700000000.0
    assert parse_mod_ts(1700000000.5) == 1700000000.5
