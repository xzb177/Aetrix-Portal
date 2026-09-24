"""SQLite 默认库文件名与「老库不被改名」的兼容（v2.30.0 品牌统一）

改品牌最容易被忽略的一处是**默认库文件名**（旧品牌名 → `aetrix_unified.db`）。
如果只是把默认值改掉，一个正常升级上来的部署下次启动就会去建一个空库——
用户看到的是「升级了一下，整站数据没了」。所以这里的口径是：

- 新名不存在、老名还在 → **继续用老名**（升级上来的人什么都不用做）；
- 新名已经存在 → 用新名（新部署 / 已经迁过的人）；
- 两者都不在 → 用新名（全新部署建新库）。

只测这个函数：``backend.database`` 在导入时就把 ``DATABASE_URL`` 定死了，
所以把目录当参数传进来，才能在不改环境变量的前提下验证四种组合。
"""
from pathlib import Path

from backend.database import (
    LEGACY_SQLITE_DB_FILENAME,
    SQLITE_DB_FILENAME,
    default_sqlite_url,
)


def test_fresh_install_uses_the_new_filename(tmp_path):
    assert default_sqlite_url(str(tmp_path)) == f"sqlite:///./{SQLITE_DB_FILENAME}"


def test_upgraded_install_keeps_the_legacy_file(tmp_path):
    """只有老库在 → 沿用老库（这条是「升级不丢数据」的全部保证）"""
    (tmp_path / LEGACY_SQLITE_DB_FILENAME).write_bytes(b"")
    assert default_sqlite_url(str(tmp_path)).endswith(LEGACY_SQLITE_DB_FILENAME)


def test_new_file_wins_once_it_exists(tmp_path):
    """两个文件都在 → 新名优先（已经迁过的人不会被老文件拽回去）"""
    (tmp_path / LEGACY_SQLITE_DB_FILENAME).write_bytes(b"")
    (tmp_path / SQLITE_DB_FILENAME).write_bytes(b"")
    assert default_sqlite_url(str(tmp_path)).endswith(SQLITE_DB_FILENAME)


def test_path_in_url_is_relative_to_the_process_cwd(tmp_path):
    """连接串保持相对路径：库文件跟着工作目录，和升级前一致"""
    assert default_sqlite_url(str(tmp_path)).startswith("sqlite:///./")
    assert Path(LEGACY_SQLITE_DB_FILENAME).name == LEGACY_SQLITE_DB_FILENAME
