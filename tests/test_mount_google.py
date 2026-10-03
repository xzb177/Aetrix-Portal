"""Google Drive 原生挂载（mount_google）的单元测试。

全部用假 Drive 服务与假令牌：**不碰真实 Google API、不碰真实凭据**。
覆盖的关键点是「哪些行为必须钉死」：

- 注册表形状（后台下拉 / 表单 / 脱敏全靠它，错了界面就错）
- 分页追完 + 文件夹/原生文档的区分
- Drive 的 403 分三种（配额 / 权限 / 额度满），处置完全不同
- 播放目标里不能漏出凭据，且直链只在显式打开时才有
- 遍历并发被限到 Drive 配额的舒适区（这是根治的一部分，不是调优）
"""
import json
import os
import time
import types

# 必须**在任何业务模块之前**设好：mounts 连带 backend.database，而 database.py
# 在 import 期就按 DATABASE_TYPE 建好 engine（本机没有 PG 服务，PG 分支会
# Connection refused）。这与仓库其它需要库的测试是同一套约定。
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest

from backend.emby_server import direct_url, mount_google, mounts as mount_lib


# ---------------- 假 Drive 服务 ----------------

class _Resp:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content

    def json(self):
        return self._payload


FOLDER = "application/vnd.google-apps.folder"
DOCS = "application/vnd.google-apps.document"

# 文件夹树：根 → [电影/, 说明.txt]；电影 → [a.mkv, poster.jpg]
_TREE = {
    "root": [
        {"id": "d1", "name": "电影", "mimeType": FOLDER},
        {"id": "f0", "name": "说明.txt", "mimeType": "text/plain", "size": "12"},
        {"id": "g1", "name": "片单", "mimeType": DOCS},
    ],
    "d1": [
        {"id": "m1", "name": "A.电影 (2024).mkv", "mimeType": "video/x-matroska", "size": "1048576"},
        {"id": "p1", "name": "poster.jpg", "mimeType": "image/jpeg", "size": "999"},
    ],
}


class _FakeDrive:
    """记录每次请求，模拟 files.list 的分页与错误。

    ``_CloudMount._request`` 用的是 ``with self._client(...) as client``，
    所以这里必须实现上下文管理器协议——这正是 ``smoke_test_mounts.py`` 里的做法。
    """

    def __init__(self, tree=None, errors=None):
        self.tree = tree if tree is not None else _TREE
        self.errors = errors or {}
        self.calls = []
        self.token_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def _parent_of(self, q):
        return q.split("'")[1] if "'" in q else ""

    _PER_PAGE = 2

    def _page(self, items, page):
        """每页 ``_PER_PAGE`` 条；返回 (本页, 下一页 token，没有则空串)

        ``page`` 是 ``PAGE<n>`` 形式的 token，``None`` / 空串是第一页。
        故意把每页压到 2 条：默认树里根目录 3 条、``d1`` 2 条，
        根目录就会真的走两页，翻页漏读的问题立刻暴露在测试里。
        """
        index = 0
        if page:
            index = int(page.removeprefix("PAGE"))
        start = index * self._PER_PAGE
        chunk = items[start:start + self._PER_PAGE]
        nxt = f"PAGE{index + 1}" if len(items) > start + self._PER_PAGE else ""
        return chunk, nxt

    def request(self, method, url, *, headers=None, params=None, json=None, data=None,
                follow_redirects=True):
        # 参数名必须与 httpx.Client.request 一致（``json=`` 而不是 ``json_body=``）
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        for frag, resp in self.errors.items():
            if frag in url:
                return resp
        if "/files?" not in url and not url.endswith("/files"):
            return _Resp(200, {"id": "root", "name": "我的云端硬盘", "root": "root"})
        params = params or {}
        parent = self._parent_of(params.get("q", ""))
        items = self.tree.get(parent)
        if items is None:
            return _Resp(404, {"error": {"code": 404, "message": "File not found.",
                                        "errors": [{"message": "File not found."}]}})
        chunk, nxt = self._page(items, params.get("pageToken"))
        return _Resp(200, {"files": chunk, "nextPageToken": nxt})


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """目录缓存与熔断器都是**进程级**的，不复位会跨用例互相污染。

    尤其熔断器：前一个用例故意造的 403 失败会把下一个用例的正常列举
    直接判成「熔断中」——那是测试之间串扰，不是代码问题。
    """
    with mount_lib._BREAKER_LOCK:
        mount_lib._BREAKERS.clear()
    mount_lib.invalidate_list_cache()
    yield
    with mount_lib._BREAKER_LOCK:
        mount_lib._BREAKERS.clear()
    mount_lib.invalidate_list_cache()


@pytest.fixture
def drive(monkeypatch):
    """假 Drive + 固定令牌（取票本身由 ``real_token`` 夹具下的用例单独覆盖）

    令牌在这里桩掉，是为了不让**每个**用例都去换票；那些专门验证取票的用例
    用 ``real_token`` 复位它，跑真正的 ``_token`` 逻辑。
    """
    import httpx

    fake = _FakeDrive()
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    monkeypatch.setattr(mount_google.GoogleDriveMount, "_token", lambda self: "TOKEN_X")
    return fake


@pytest.fixture
def real_token(monkeypatch):
    """恢复真实的取票逻辑（让 ``_token`` 真去要令牌）

    没有这个夹具的话，取票用例会被 ``drive`` 的桩短路成永远返回 TOKEN_X，
    于是「轮换池有没有被调用」「缓存有没有生效」全都测不到真东西。
    """
    monkeypatch.undo()
    return True


def _mount(config=None):
    cfg = {"auth_mode": "sa"}
    cfg.update(config or {})
    return types.SimpleNamespace(
        id=99, name="gd", mount_type="gdrive", path="", config=json.dumps(cfg),
        is_enabled=True, realm_id=None, remark="",
    )


def _provider(config=None):
    return mount_lib.build_provider(_mount(config))


# ---------------- 注册表与元数据 ----------------

def test_type_registered():
    assert "gdrive" in mount_lib.MOUNT_TYPE_MAP
    assert "gdrive" in mount_lib._PROVIDERS


def test_metadata_shape():
    meta = mount_lib.type_meta("gdrive")
    assert meta["kind"] == "remote"      # 条目存 mount://，播放时代理
    assert meta["group"] == "cloud"      # 后台用云盘图标
    assert meta["browse"] is True
    assert mount_lib.root_key("gdrive") == "root_id"
    assert [f["key"] for f in mount_lib.required_fields("gdrive")] == ["auth_mode"]


def test_secrets_are_masked_but_sa_path_is_not():
    """sa_file 是**路径**不是密钥：标成 secret 会让列表页只显示「已配置」，没法核对。"""
    keys = mount_lib.secret_config_keys()
    assert {"client_secret", "refresh_token"} <= keys
    assert "sa_file" not in keys
    assert "api_base" not in keys


# ---------------- 列目录 ----------------

def test_list_dir_maps_entries(drive):
    entries = _provider().list_dir("/")
    names = [(e.name, e.is_dir) for e in entries]
    # 目录在前、文件在后；Google 原生文档被跳过
    assert names == [("电影", True), ("说明.txt", False)]
    # entry_id 落 Drive file id：解析播放目标靠它定位文件
    folder = next(e for e in entries if e.name == "电影")
    assert folder.entry_id == "d1"


def test_list_dir_paginates(drive):
    """翻页必须追完：漏页等于漏文件，扫描会误判「文件已删除」并清理掉。"""
    tree = {k: list(v) for k, v in _TREE.items()}
    tree["d1"] = tree["d1"] + [
        {"id": "m2", "name": "B.电影 (2023).mkv", "mimeType": "video/x-matroska", "size": "2048"},
        {"id": "m3", "name": "C.电影 (2022).mkv", "mimeType": "video/x-matroska", "size": "3072"},
    ]
    drive.tree = tree
    entries = _provider().list_dir("/电影")
    assert [e.name for e in entries] == [
        "A.电影 (2024).mkv", "B.电影 (2023).mkv", "C.电影 (2022).mkv", "poster.jpg",
    ]


def test_list_dir_sends_shared_drive_params(drive):
    """共享盘缺 supportsAllDrives / driveId 就是「能列目录但打不开文件」。"""
    p = _provider({"drive_id": "DRV1"})
    p.list_dir("/")
    params = [c["params"] for c in drive.calls if c["params"].get("q")]
    assert params
    for prm in params:
        assert prm["supportsAllDrives"] == "true"
        assert prm["includeItemsFromAllDrives"] == "true"
        assert prm["corpora"] == "drive"
        assert prm["driveId"] == "DRV1"


def test_subpath_walks_down_by_name(drive):
    """媒体库路径写成 mount://<id>/电影 时，必须能定位到子目录。"""
    entries = _provider().list_dir("/电影")
    assert [e.name for e in entries] == ["A.电影 (2024).mkv", "poster.jpg"]


def test_missing_subpath_is_readable_error(drive):
    with pytest.raises(mount_lib.MountError) as exc:
        _provider().list_dir("/不存在的目录")
    assert "找不到目录" in str(exc.value)


# ---------------- 播放目标 ----------------

def test_resolve_returns_proxy_target_without_leaking(drive):
    t = _provider().resolve("/电影/A.电影 (2024).mkv")
    assert t.kind == "url"
    assert "/files/m1" in t.value
    assert "alt=media" in t.value
    assert t.headers["Authorization"] == "Bearer TOKEN_X"
    assert "access_token" not in t.value, "凭据只能走 Authorization 头，不能进 URL"


def test_legacy_direct_link_config_is_ignored(drive):
    """老配置里的 direct_link 还在，但代码已不读它，也不报错。

    Google Drive 的 302 真直链不可行：重定向带不过 Authorization 头，
    token 放 URL 里会被限流（Alist / RClone / Cloudreve 也均为服务端代理）。
    """
    provider = _provider({"direct_link": "1"})
    assert not hasattr(provider, "direct_link"), "direct_link 配置已删除，不再读取"
    t = provider.resolve("/电影/A.电影 (2024).mkv")
    assert t.value.startswith("https://www.googleapis.com/drive/v3/files/")


def test_direct_link_form_field_is_gone(drive):
    """后台表单里也不再有这个字段（不给一个点了也没用的开关）"""
    fields = [f for e in mount_google.MOUNT_TYPE_ENTRIES
              if e["value"] == mount_google.MOUNT_GDRIVE for f in e["fields"]]
    assert "direct_link" not in {f["key"] for f in fields}


def test_resolve_missing_file(drive):
    with pytest.raises(mount_lib.MountError):
        _provider().resolve("/电影/没有这部.mkv")


# ---------------- 错误翻译 ----------------

@pytest.mark.parametrize("reason,exc_type", [
    ("rateLimitExceeded", mount_lib.MountError),
    ("insufficientPermissions", mount_lib.MountAuthError),
    ("storageQuotaExceeded", mount_lib.MountAuthError),
])
def test_403_variants(drive, reason, exc_type):
    """403 有三种，处置完全不同：配额等一会就好，权限/额度满改配置也没用。"""
    body = {"error": {"code": 403, "reason": reason,
                      "errors": [{"message": f"{reason} happened"}]}}
    drive.errors["/files"] = _Resp(403, body)
    mount_lib.invalidate_list_cache()
    with pytest.raises(exc_type) as exc:
        _provider().list_dir("/")
    if reason == "rateLimitExceeded":
        assert "配额" in str(exc.value)


def test_401_is_auth_error(drive):
    drive.errors["/files"] = _Resp(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
    mount_lib.invalidate_list_cache()
    with pytest.raises(mount_lib.MountAuthError):
        _provider().list_dir("/")


def test_404_is_plain_error(drive):
    drive.errors["/files"] = _Resp(404, {"error": {"code": 404, "message": "File not found."}})
    mount_lib.invalidate_list_cache()
    with pytest.raises(mount_lib.MountError) as exc:
        _provider().list_dir("/")
    assert not isinstance(exc.value, mount_lib.MountAuthError)


# ---------------- 遍历 ----------------

def test_walk_media_skips_docs_and_dedupes(drive):
    files = list(_provider().walk_media(root="/"))
    rels = [f.rel for f in files]
    assert rels == ["/电影/A.电影 (2024).mkv"]      # 说明.txt 不是媒体；片单是原生文档
    assert files[0].size == 1048576


def test_walk_workers_capped_for_drive_quota():
    """Drive 是 per-user 配额：并发必须低于全局的 16，否则整轮扫描撞限流。"""
    assert mount_google._GDRIVE_WALK_WORKERS <= 8
    assert _provider().walk_workers() == mount_google._GDRIVE_WALK_WORKERS


def test_walk_media_skips_disc_subtrees(drive):
    drive.tree["d1"] = _TREE["d1"] + [{"id": "bd", "name": "BDMV", "mimeType": FOLDER}]
    drive.tree["bd"] = [{"id": "seg", "name": "00000.m2ts", "mimeType": "video/mp2t", "size": "1"}]
    files = list(_provider().walk_media(root="/"))
    assert all("BDMV" not in f.rel for f in files)


# ---------------- 取票 ----------------

def test_sa_pool_used_when_no_explicit_file(monkeypatch, real_token):
    """没指定单个账号时走轮换池——多账号分摊配额，是根治「跑久了爆」的关键。"""
    called = []

    class _Pool:
        def get_token_sync(self):
            called.append(1)
            return ("SA_TOKEN", time.time() + 3600)

    monkeypatch.setattr(direct_url, "get_sa_pool", lambda: _Pool())
    p = _provider()
    assert p._token() == "SA_TOKEN"
    assert called == [1]
    # token 缓存：第二次不再问池子
    assert p._token() == "SA_TOKEN"
    assert called == [1]


def test_single_sa_file_used(monkeypatch, real_token, tmp_path):
    sa = tmp_path / "one.json"
    sa.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        direct_url, "_sa_access_token_sync",
        lambda path, label: (calls.append(path) or ("ONE_TOKEN", time.time() + 3600)),
    )
    p = _provider({"sa_file": str(sa)})
    assert p._token() == "ONE_TOKEN"
    assert calls == [str(sa)]
    # token 缓存：第二次不再换票
    assert p._token() == "ONE_TOKEN"
    assert calls == [str(sa)]


def test_oauth_missing_fields_is_auth_error(real_token):
    """OAuth 模式三项不全要立刻说清缺什么，而不是等到扫描时才 401。"""
    with pytest.raises(mount_lib.MountAuthError) as exc:
        _provider({"auth_mode": "oauth"})._token()
    assert "client_id" in str(exc.value)


def test_oauth_refresh_used(monkeypatch, real_token):
    calls = []
    monkeypatch.setattr(
        direct_url, "refresh_access_token_sync",
        lambda cid, cs, rt: (calls.append((cid, rt)) or ("OAUTH_TOKEN", time.time() + 3600)),
    )
    p = _provider({"auth_mode": "oauth", "client_id": "CID",
                   "client_secret": "SEC", "refresh_token": "RT"})
    assert p._token() == "OAUTH_TOKEN"
    assert calls == [("CID", "RT")]


# ---------------- 同步取票（不建事件循环） ----------------

def _sa_json(tmp_path, name="sa.json"):
    """生成一份**能真签名**的服务账号 JSON（本地生成 RSA 私钥）。

    必须是真私钥：``_sa_jwt_assertion`` 会用 jose 真做 RS256 签名，
    私钥是假字符串时签不出 assertion，用例会以「签名失败」告终——
    那是环境没配好，不是被测代码的毛病。
    """
    pytest.importorskip("jose")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    p = tmp_path / name
    p.write_text(json.dumps({
        "type": "service_account",
        "project_id": "test-project",
        "private_key": pem,
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }), encoding="utf-8")
    return str(p)


def test_sync_token_path_does_not_use_asyncio(monkeypatch, tmp_path):
    """工作线程里 asyncio.run 会为每次取票新建事件循环——必须真的用同步 httpx。"""
    import httpx

    sa = _sa_json(tmp_path)

    class _SyncClient:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, **kw):
            assert data["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
            return _Resp(200, {"access_token": "SYNC_TOKEN", "expires_in": 3600})

    monkeypatch.setattr(httpx, "Client", _SyncClient)
    got = direct_url._sa_access_token_sync(sa, "MP")
    assert got and got[0] == "SYNC_TOKEN"


def test_sync_pool_shares_rotation_and_cooldown(monkeypatch, tmp_path):
    """同步路与异步路必须共用轮换与冷却语义。"""
    from backend.emby_server.direct_url import SARateLimited, ServiceAccountPool

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(json.dumps({
            "type": "service_account", "private_key": "k",
            "client_email": f"{name}@x", "token_uri": "u",
        }), encoding="utf-8")

    def fetch(path, label):
        if path == str(a):
            raise SARateLimited("429")
        return ("TOKEN_B", time.time() + 3600)

    monkeypatch.setattr(direct_url, "_sa_access_token_sync", fetch)
    pool = ServiceAccountPool(sa_dir=str(tmp_path), prewarm=False, healthcheck_interval=0)
    assert pool.get_token_sync()[0] == "TOKEN_B"
    # 被限流的账号进入冷却，下一轮换另一个；与异步版语义一致
    assert str(a) in pool._cooldown_until


# ---------------- 连通性 ----------------

def test_test_message_mentions_auth_mode(drive):
    out = _provider().test()
    assert out["ok"] is True
    assert "服务账号轮换池" in out["message"]


# ---------------- 与追新的衔接 ----------------

def test_entries_carry_modified_time(drive):
    """追新靠条目的 mod_ts 做「新增」窗口过滤。

    不带 mod_ts 等于这类挂载永远检不出新文件——**静默漏检**，不报错，最难查。
    """
    drive.tree["d1"] = _TREE["d1"] + [
        {"id": "m9", "name": "新片.mkv", "mimeType": "video/x-matroska",
         "size": "10", "modifiedTime": "2026-10-01T12:00:00.123456789Z"},
    ]
    entries = _provider().list_dir("/电影")
    new = next(e for e in entries if e.name == "新片.mkv")
    # Drive 给的是 9 位纳秒（rclone 也有同样的精度问题），公共通道的
    # parse_mod_ts 负责归一；这里断言它落在正确的秒级且亚秒部分没丢
    assert new.mod_ts == pytest.approx(1790856000.123, abs=0.01)


def test_chase_new_accepts_gdrive(monkeypatch, drive):
    """追新的类型判定：能给出远端 modTime 的远程挂载都要能接上

    ``#283`` 把追新改成走公共通道（吃缓存/限流/熔断），判定条件是「条目带得上
    mod_ts」。若这里只认 rclone 的 ``mode == rc``，gdrive 会被**静默跳过**——
    线程在跑、last_check 在更新，却永远发现不了新资源（与追新早年的真故障同型）。
    """
    from backend.emby_server import change_watcher as cw

    got = cw._chase_provider(_mount(), None)
    assert got is not None
    assert got.mount_type == "gdrive"


def test_chase_new_still_rejects_local_and_disabled(monkeypatch):
    """本机目录（走 find -newermt 那条路）与停用挂载必须继续被排除。"""
    from backend.emby_server import change_watcher as cw

    local = types.SimpleNamespace(
        id=1, name="l", mount_type="local", path="/tmp", config="{}",
        is_enabled=True, realm_id=None, remark="",
    )
    assert cw._chase_provider(local, None) is None
    # 停用的 gdrive 同样不进追新
    assert cw._chase_provider(_mount(), None) is not None
    off = _mount()
    off.is_enabled = False
    assert cw._chase_provider(off, None) is None