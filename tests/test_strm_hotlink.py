"""防盗链（.strm 签名 + Drive SA 凭据中转 + 播放签名可配置）单元测试。

覆盖：
- backend/emby_server/strm_sign.py：签名/验签/三态/刷新判定/参数剥离
- backend/emby_server/drive_auth.py：Drive 域名判定/凭据头构造/失败降级
- backend/emby_server/play_sign.py：防盗链开关 + TTL 热读/钳制/write_config 校验
- backend/emby_server/mounts.py：local_play_target 的 .strm 分支（三态）
- backend/emby_server/streaming.py：_redirect_headers 的 Drive 例外

用隔离的内存 SQLite，不碰生产库；不碰真实网络。
"""
from __future__ import annotations

import time
from unittest import mock

import pytest

DRIVE_URL = "https://drive.google.com/uc?export=download&id=ABC123&confirm=t"


@pytest.fixture(autouse=True)
def fixed_secret(monkeypatch):
    """测试用固定签名密钥，避免依赖环境变量。"""
    import backend.security as sec

    monkeypatch.setattr(sec, "SECRET_KEY", "test-secret-key-for-strm-hotlink-00")


@pytest.fixture()
def db():
    """隔离的内存 SQLite（照抄 tests/test_cdn.py 的模式）。"""
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
    from backend import models
    from backend.integrations import store

    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if row is None:
        db.add(models.SystemConfig(key=key, value=value))
    else:
        row.value = value
    db.commit()
    store.invalidate(key)


# ==================== strm_sign ====================

class TestStrmSign:
    def test_sign_verify_roundtrip_ok(self):
        from backend.emby_server import strm_sign

        signed = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600)
        assert "aexp=" in signed and "asig=" in signed
        clean, status = strm_sign.verify_strm_url(signed)
        assert status == "ok"
        assert clean == DRIVE_URL

    def test_sign_is_idempotent_no_stacking(self):
        """二次签名不叠加参数（canonical 化）。"""
        from backend.emby_server import strm_sign

        once = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600)
        twice = strm_sign.sign_strm_url(once, ttl_seconds=3600)
        assert twice.count("aexp=") == 1 and twice.count("asig=") == 1
        clean, status = strm_sign.verify_strm_url(twice)
        assert status == "ok" and clean == DRIVE_URL

    def test_tampered_sig_is_bad(self):
        from backend.emby_server import strm_sign

        signed = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600)
        tampered = signed[:-1] + ("0" if signed[-1] != "0" else "1")
        _, status = strm_sign.verify_strm_url(tampered)
        assert status == "bad"

    def test_tampered_url_is_bad(self):
        from backend.emby_server import strm_sign

        signed = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600).replace("id=ABC123", "id=EVIL")
        _, status = strm_sign.verify_strm_url(signed)
        assert status == "bad"

    def test_expired_is_bad(self):
        from backend.emby_server import strm_sign

        signed = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600)
        # 把 exp 改成过去（保持签名有效位数的错位不重要：先判过期）
        import re

        expired = re.sub(r"aexp=\d+", f"aexp={int(time.time()) - 10}", signed)
        _, status = strm_sign.verify_strm_url(expired)
        assert status == "bad"

    def test_missing_one_param_is_bad(self):
        from backend.emby_server import strm_sign

        signed = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600)
        no_sig = strm_sign.strip_sig_params(signed) + "&aexp=9999999999"
        _, status = strm_sign.verify_strm_url(no_sig)
        assert status == "bad"

    def test_legacy_no_signature(self):
        from backend.emby_server import strm_sign

        clean, status = strm_sign.verify_strm_url(DRIVE_URL)
        assert status == "legacy"
        assert clean == DRIVE_URL

    def test_legacy_tolerates_bom_comments_blank_lines(self):
        from backend.emby_server import strm_sign

        content = "\ufeff\n# 这是注释\n\n" + DRIVE_URL + "\n"
        clean, status = strm_sign.verify_strm_url(content)
        assert status == "legacy"
        assert clean == DRIVE_URL

    def test_empty_content_is_bad(self):
        from backend.emby_server import strm_sign

        for content in ("", "   \n  ", "# 只有注释\n"):
            _, status = strm_sign.verify_strm_url(content)
            assert status == "bad"

    def test_needs_refresh(self):
        from backend.emby_server import strm_sign

        assert strm_sign.needs_refresh(DRIVE_URL) is True  # legacy → 补签名
        fresh = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600)
        assert strm_sign.needs_refresh(fresh) is False  # 充足 → 不刷新
        soon = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=300)
        assert strm_sign.needs_refresh(soon) is True  # 剩余 <600s → 刷新
        assert strm_sign.needs_refresh("not a url at all") is False  # bad → 不碰

    def test_strip_sig_params(self):
        from backend.emby_server import strm_sign

        signed = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600)
        assert strm_sign.strip_sig_params(signed) == DRIVE_URL
        # 非签名 URL 原样返回
        assert strm_sign.strip_sig_params(DRIVE_URL) == DRIVE_URL
        assert strm_sign.strip_sig_params("") == ""

    def test_sign_empty_url_returns_as_is(self):
        from backend.emby_server import strm_sign

        assert strm_sign.sign_strm_url("") == ""

    def test_verify_never_raises(self):
        from backend.emby_server import strm_sign

        for content in (None, 123, "https://[invalid", "aexp=1&asig=2"):
            _, status = strm_sign.verify_strm_url(content)
            assert status in ("ok", "legacy", "bad")


# ==================== drive_auth ====================

class TestDriveAuth:
    def test_is_drive_url(self):
        from backend.emby_server import drive_auth

        assert drive_auth.is_drive_url("https://drive.google.com/uc?id=1")
        assert drive_auth.is_drive_url("https://drive.usercontent.google.com/download?id=1")
        assert drive_auth.is_drive_url("https://docs.google.com/document/d/1")
        assert drive_auth.is_drive_url("https://www.googleapis.com/drive/v3/files/1")
        assert drive_auth.is_drive_url("HTTPS://DRIVE.GOOGLE.COM/uc?id=1")  # 大小写
        assert not drive_auth.is_drive_url("https://example.com/x")
        assert not drive_auth.is_drive_url("https://evildrive.google.com.evil.com/x")
        assert not drive_auth.is_drive_url("")

    def test_headers_non_drive_is_empty(self):
        from backend.emby_server import drive_auth

        assert drive_auth.drive_auth_headers("https://example.com/video.mp4") == {}

    def test_headers_no_token_is_empty(self):
        """拿不到 SA token 时降级为空 dict（不阻断播放）。"""
        from backend.emby_server import drive_auth

        drive_auth._cached_token = None
        drive_auth._cached_expire_at = 0.0
        with mock.patch.object(drive_auth, "_pick_sa", return_value=None):
            assert drive_auth.drive_auth_headers(DRIVE_URL) == {}

    def test_headers_with_token(self):
        from backend.emby_server import drive_auth

        with mock.patch.object(drive_auth, "get_drive_bearer_token", return_value="TOK123"):
            headers = drive_auth.drive_auth_headers(DRIVE_URL)
        assert headers == {"Authorization": "Bearer TOK123"}

    def test_get_token_never_raises(self):
        from backend.emby_server import drive_auth

        drive_auth._cached_token = None
        drive_auth._cached_expire_at = 0.0
        with mock.patch.object(drive_auth, "_pick_sa", side_effect=RuntimeError("boom")):
            assert drive_auth.get_drive_bearer_token() is None

    def test_token_cache_hit(self):
        """进程内缓存：剩余有效期 >120s 直接返回，不再调 _pick_sa。"""
        from backend.emby_server import drive_auth

        drive_auth._cached_token = "CACHED"
        drive_auth._cached_expire_at = time.monotonic() + 3000
        try:
            with mock.patch.object(
                drive_auth, "_pick_sa", side_effect=AssertionError("should not be called")
            ):
                assert drive_auth.get_drive_bearer_token() == "CACHED"
        finally:
            drive_auth._cached_token = None
            drive_auth._cached_expire_at = 0.0


# ==================== play_sign 配置 ====================

class TestPlaySignConfig:
    def test_hotlink_enabled_default_true(self):
        from backend.emby_server import play_sign

        assert play_sign.hotlink_enabled() is True

    def test_hotlink_enabled_values(self, db):
        from backend.emby_server import play_sign

        _set_config(db, play_sign.CONFIG_HOTLINK_ENABLED, "false")
        assert play_sign.hotlink_enabled(db) is False
        _set_config(db, play_sign.CONFIG_HOTLINK_ENABLED, "0")
        assert play_sign.hotlink_enabled(db) is False
        _set_config(db, play_sign.CONFIG_HOTLINK_ENABLED, "true")
        assert play_sign.hotlink_enabled(db) is True
        _set_config(db, play_sign.CONFIG_HOTLINK_ENABLED, "YES")
        assert play_sign.hotlink_enabled(db) is True

    def test_hotlink_enabled_illegal_falls_back_true(self, db):
        """非法值回落默认启用：不弱化验签语义。"""
        from backend.emby_server import play_sign

        _set_config(db, play_sign.CONFIG_HOTLINK_ENABLED, "maybe")
        assert play_sign.hotlink_enabled(db) is True
        _set_config(db, play_sign.CONFIG_HOTLINK_ENABLED, "")
        assert play_sign.hotlink_enabled(db) is True

    def test_play_sign_ttl_clamp(self, db):
        from backend.emby_server import play_sign

        assert play_sign.play_sign_ttl_seconds() == 900  # db=None 默认
        _set_config(db, play_sign.CONFIG_PLAY_SIGN_TTL, "1800")
        assert play_sign.play_sign_ttl_seconds(db) == 1800
        _set_config(db, play_sign.CONFIG_PLAY_SIGN_TTL, "10")  # <60 钳制
        assert play_sign.play_sign_ttl_seconds(db) == 60
        _set_config(db, play_sign.CONFIG_PLAY_SIGN_TTL, "999999")  # >86400 钳制
        assert play_sign.play_sign_ttl_seconds(db) == 86400
        _set_config(db, play_sign.CONFIG_PLAY_SIGN_TTL, "not-a-number")
        assert play_sign.play_sign_ttl_seconds(db) == 900  # 非法回落默认

    def test_strm_sig_ttl_clamp(self, db):
        from backend.emby_server import play_sign

        assert play_sign.strm_sig_ttl_seconds() == 3600  # db=None 默认
        _set_config(db, play_sign.CONFIG_STRM_SIG_TTL, "7200")
        assert play_sign.strm_sig_ttl_seconds(db) == 7200
        _set_config(db, play_sign.CONFIG_STRM_SIG_TTL, "10")  # <300 钳制
        assert play_sign.strm_sig_ttl_seconds(db) == 300
        _set_config(db, play_sign.CONFIG_STRM_SIG_TTL, "999999")
        assert play_sign.strm_sig_ttl_seconds(db) == 86400

    def test_strm_sign_delegates_to_play_sign(self, db):
        """strm_sign 的 TTL 读取必须委托给 play_sign（不许两套）。"""
        from backend.emby_server import play_sign, strm_sign

        _set_config(db, play_sign.CONFIG_STRM_SIG_TTL, "7200")
        assert strm_sign.strm_sig_ttl_seconds(db) == 7200 == play_sign.strm_sig_ttl_seconds(db)

    def test_write_config_roundtrip(self, db):
        from backend import models
        from backend.emby_server import play_sign

        payload = play_sign.write_config(db, enabled=False, play_sign_ttl=1800, strm_sig_ttl=7200)
        assert payload["enabled"] is False
        assert payload["play_sign_ttl"] == 1800
        assert payload["strm_sig_ttl"] == 7200
        assert payload["defaults"] == {"enabled": True, "play_sign_ttl": 900, "strm_sig_ttl": 3600}
        # 落库 + description
        row = db.query(models.SystemConfig).filter(
            models.SystemConfig.key == play_sign.CONFIG_HOTLINK_ENABLED).first()
        assert row.value == "false"
        assert row.description
        # 热读即时生效（write_config 内已 invalidate）
        assert play_sign.hotlink_enabled(db) is False

    def test_write_config_rejects_out_of_range(self, db):
        from backend.emby_server import play_sign

        with pytest.raises(ValueError):
            play_sign.write_config(db, enabled=True, play_sign_ttl=30, strm_sig_ttl=3600)
        with pytest.raises(ValueError):
            play_sign.write_config(db, enabled=True, play_sign_ttl=900, strm_sig_ttl=100)
        with pytest.raises(ValueError):
            play_sign.write_config(db, enabled=True, play_sign_ttl="abc", strm_sig_ttl=3600)

    def test_sign_ttl_seconds_constant_kept(self):
        """SIGN_TTL_SECONDS 常量保留（兼容旧引用）。"""
        from backend.emby_server import play_sign

        assert play_sign.SIGN_TTL_SECONDS == 900


# ==================== mounts.local_play_target ====================

class TestMountsStrmBranch:
    def _write(self, tmp_path, name, content):
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_ok_signed_strm(self, tmp_path):
        from backend.emby_server import mounts, strm_sign

        signed = strm_sign.sign_strm_url(DRIVE_URL, ttl_seconds=3600)
        path = self._write(tmp_path, "ok.strm", signed + "\n# 注释保留\n")
        with mock.patch(
            "backend.emby_server.drive_auth.drive_auth_headers",
            return_value={"Authorization": "Bearer T"},
        ):
            target = mounts.local_play_target(path)
        assert target.kind == "url"
        assert target.value == DRIVE_URL  # 返回 canonical（去签名参数）
        assert target.headers["Authorization"] == "Bearer T"
        assert "User-Agent" in target.headers

    def test_legacy_strm_passes_with_warning(self, tmp_path, caplog):
        from backend.emby_server import mounts

        path = self._write(tmp_path, "legacy.strm", DRIVE_URL + "\n")
        with mock.patch(
            "backend.emby_server.drive_auth.drive_auth_headers", return_value={}
        ):
            target = mounts.local_play_target(path)
        assert target.kind == "url"
        assert target.value == DRIVE_URL
        assert "legacy" in caplog.text

    def test_bad_signed_strm_raises(self, tmp_path):
        from backend.emby_server import mounts

        path = self._write(tmp_path, "bad.strm", DRIVE_URL + "&aexp=1&asig=deadbeef\n")
        with pytest.raises(mounts.MountError, match="签名无效或已过期"):
            mounts.local_play_target(path)

    def test_empty_strm_still_raises_missing_link(self, tmp_path):
        from backend.emby_server import mounts

        path = self._write(tmp_path, "empty.strm", "\n# 空文件\n")
        with pytest.raises(mounts.MountError, match="没有可用的直链"):
            mounts.local_play_target(path)


# ==================== streaming._redirect_headers ====================

class TestRedirectHeaders:
    def test_same_host_untouched(self):
        from backend.emby_server.streaming import _redirect_headers

        fwd = {"Authorization": "Bearer X", "Cookie": "c=1", "User-Agent": "ua"}
        assert _redirect_headers(fwd, "https://a.com/1", "https://a.com/2") == fwd

    def test_drive_to_drive_keeps_authorization_only(self):
        from backend.emby_server.streaming import _redirect_headers

        fwd = {
            "Authorization": "Bearer X",
            "Cookie": "c=1",
            "Proxy-Authorization": "p",
            "User-Agent": "ua",
        }
        out = _redirect_headers(
            fwd,
            "https://drive.google.com/uc?id=1",
            "https://drive.usercontent.google.com/download?id=1",
        )
        assert out == {"Authorization": "Bearer X", "User-Agent": "ua"}

    def test_drive_to_evil_strips_all(self):
        from backend.emby_server.streaming import _redirect_headers

        fwd = {"Authorization": "Bearer X", "Cookie": "c=1", "User-Agent": "ua"}
        out = _redirect_headers(fwd, "https://drive.google.com/uc?id=1", "https://evil.com/x")
        assert out == {"User-Agent": "ua"}

    def test_non_drive_cross_host_strips_all(self):
        """非 Drive 目标保持原逻辑：全剥（回归）。"""
        from backend.emby_server.streaming import _redirect_headers

        fwd = {"Authorization": "Basic X", "Cookie": "c=1", "User-Agent": "ua"}
        out = _redirect_headers(fwd, "https://webdav.example.com/a", "https://other.example.com/b")
        assert out == {"User-Agent": "ua"}

    def test_header_name_case_insensitive(self):
        from backend.emby_server.streaming import _redirect_headers

        fwd = {"AUTHORIZATION": "Bearer Y", "cookie": "c=1"}
        out = _redirect_headers(
            fwd, "https://drive.google.com/a", "https://docs.google.com/b"
        )
        assert out == {"AUTHORIZATION": "Bearer Y"}
