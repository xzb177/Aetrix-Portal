"""strm 配置（backend/emby_server/strm_config.py）回归测试。

回归口径：
- 默认启用与升级前一致：空库时 enabled=True / host_dir="/opt/strm" / container_path="/strm"；
- 非法值回落默认：enabled 非法值按 True 处理，路径非法（相对、超长、含 ".."、根路径、非字符串）回落默认目录；
- 写失败不落半个配置：write_config 校验失败抛 ValueError，DB 不产生任何 strm_* 行；
- 热读语义：write_config 保存即生效（缓存失效），直改 DB 行在 TTL 内仍读旧值、store.invalidate() 后读新值（跨进程 TTL 兜底）。
"""

import pytest


@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import models
    from backend.integrations import store
    store.invalidate()
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        store.invalidate()


def _set_config(db, key, value):
    """直接预置/覆盖一行 SystemConfig，并失效热读缓存。"""
    from backend import models
    from backend.integrations import store
    db.query(models.SystemConfig).filter_by(key=key).delete()
    db.add(models.SystemConfig(key=key, value=value))
    db.commit()
    store.invalidate()


def test_defaults_on_empty_db(db):
    from backend.emby_server import strm_config
    assert strm_config.enabled(db) is True
    assert strm_config.host_dir(db) == "/opt/strm"
    assert strm_config.container_path(db) == "/strm"


def test_enabled_parsing(db):
    from backend.emby_server import strm_config
    key = strm_config.CONFIG_STRM_ENABLED
    for value in ("true", "TRUE", "1", "yes", "ON"):
        _set_config(db, key, value)
        assert strm_config.enabled(db) is True, value
    for value in ("false", "FALSE", "0", "no", "off", ""):
        _set_config(db, key, value)
        assert strm_config.enabled(db) is False, value
    for value in ("maybe", "2"):
        _set_config(db, key, value)
        assert strm_config.enabled(db) is True, value


def test_normalize_dir_path_boundaries():
    from backend.emby_server import strm_config
    default = "/opt/strm"
    normalize = strm_config.normalize_dir_path
    assert normalize(None, default) == default
    assert normalize(123, default) == default
    assert normalize("", default) == default
    assert normalize("  /a//b/ ", default) == "/a/b"
    assert normalize("C:\\x", default) == default
    assert normalize("/a\\b", default) == "/a/b"
    assert normalize("/a/../b", default) == default
    assert normalize("/a/./b", default) == "/a/./b"
    assert normalize("/", default) == default
    assert normalize("a" * 2000, default) == default
    assert normalize("opt/strm", default) == default


def test_is_strm_path_default_container(db):
    from backend.emby_server import strm_config
    assert strm_config.is_strm_path(db, "/strm") is True
    assert strm_config.is_strm_path(db, "/strm/a.strm") is True
    assert strm_config.is_strm_path(db, "/strm2/x") is False
    assert strm_config.is_strm_path(db, "/media/x") is False
    assert strm_config.is_strm_path(db, "") is False
    assert strm_config.is_strm_path(db, None) is False


def test_is_strm_path_custom_container(db):
    from backend.emby_server import strm_config
    strm_config.write_config(db, enabled=True, host_dir="/opt/strm", container_path="/s")
    assert strm_config.is_strm_path(db, "/s") is True
    assert strm_config.is_strm_path(db, "/s/a") is True
    assert strm_config.is_strm_path(db, "/strm/a") is False


def test_write_config_success(db):
    from backend.emby_server import strm_config
    from backend import models
    payload = strm_config.write_config(db, enabled=False, host_dir="/data/strm/", container_path="/s")
    assert payload["enabled"] is False
    assert payload["host_dir"] == "/data/strm"
    assert payload["container_path"] == "/s"
    assert "defaults" in payload
    for key in (
        strm_config.CONFIG_STRM_ENABLED,
        strm_config.CONFIG_STRM_HOST_DIR,
        strm_config.CONFIG_STRM_CONTAINER_PATH,
    ):
        row = db.query(models.SystemConfig).filter_by(key=key).first()
        assert row is not None, key
        assert row.description, key
    assert strm_config.enabled(db) is False
    assert strm_config.host_dir(db) == "/data/strm"
    assert strm_config.container_path(db) == "/s"


def test_write_config_validation_failures(db):
    from backend.emby_server import strm_config
    from backend import models
    strm_keys = (
        strm_config.CONFIG_STRM_ENABLED,
        strm_config.CONFIG_STRM_HOST_DIR,
        strm_config.CONFIG_STRM_CONTAINER_PATH,
    )
    for bad_host_dir in ("rel", "/a/../b", "", "a" * 2000):
        with pytest.raises(ValueError):
            strm_config.write_config(db, enabled=True, host_dir=bad_host_dir, container_path="/s")
        for key in strm_keys:
            assert db.query(models.SystemConfig).filter_by(key=key).first() is None, key
    with pytest.raises(ValueError):
        strm_config.write_config(db, enabled=True, host_dir="/opt/strm", container_path="/")
    with pytest.raises(ValueError):
        strm_config.write_config(db, enabled=True, host_dir="/opt/strm", container_path="a" * 2000)
    for key in strm_keys:
        assert db.query(models.SystemConfig).filter_by(key=key).first() is None, key


def test_config_payload_shape(db):
    from backend.emby_server import strm_config
    payload = strm_config.config_payload(db)
    assert set(payload.keys()) == {"enabled", "host_dir", "container_path", "defaults"}
    assert payload["enabled"] is True
    assert payload["host_dir"] == "/opt/strm"
    assert payload["container_path"] == "/strm"
    assert payload["defaults"] == {"enabled": True, "host_dir": "/opt/strm", "container_path": "/strm"}


def test_hot_read_semantics(db):
    from backend.emby_server import strm_config
    from backend import models
    from backend.integrations import store
    strm_config.write_config(db, enabled=False, host_dir="/opt/strm", container_path="/strm")
    assert strm_config.enabled(db) is False
    # 直改 DB 行且不清缓存：TTL 内仍读旧值
    db.query(models.SystemConfig).filter_by(key=strm_config.CONFIG_STRM_ENABLED).update({"value": "true"})
    db.commit()
    assert strm_config.enabled(db) is False
    # 缓存失效后读到新值：跨进程 TTL 兜底
    store.invalidate()
    assert strm_config.enabled(db) is True


def test_enabled_gates_scanner_strm_filter(db):
    """开关与扫描器的接线契约：iter_scan_sources 每轮读 strm_config.enabled(db)，
    把结果喂给 scanner._strm_filter；关闭时 .strm 文件不产出。"""
    from types import SimpleNamespace
    from backend.emby_server import strm_config
    from backend.emby_server.scanner import _strm_filter
    files = [SimpleNamespace(name="a.strm"), SimpleNamespace(name="b.mkv")]
    # 默认启用：.strm 照常产出
    assert [f.name for f in _strm_filter(files, strm_config.enabled(db))] == ["a.strm", "b.mkv"]
    # 关闭：.strm 被跳过
    strm_config.write_config(db, enabled=False, host_dir="/opt/strm", container_path="/strm")
    assert [f.name for f in _strm_filter(files, strm_config.enabled(db))] == ["b.mkv"]
