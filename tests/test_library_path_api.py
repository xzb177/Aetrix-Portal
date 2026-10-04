"""媒体库路径 API 端到端（走真实 HTTP 接口，隔离的内存 SQLite）

单元测试（``test_library_path_entries.py``）验的是纯函数；这里验的是**管理员实际会碰到
的那条链路**——打开设置页看到什么、保存后库里存了什么：

1. ``GET  /libraries``       —— 老库里的 ``mount://1/paul_emby/video/剧集/国产剧``
   回显成 ``{path: /video/剧集/国产剧, backend: 115}``，并下发后端下拉项
2. ``PUT  /libraries/{id}``  —— 界面传 ``path_entries``（裸路径 + 后端 + 挂载 id），
   库里存回 ``mount://`` 前缀，且 ``storage_backends`` 与 ``paths`` 逐条对应
3. ``GET  /mounts/local-dirs`` —— 本机目录浏览与挂载浏览同一套结构（前端只写一套列表 UI）

不碰网络、不碰生产库；路由用假挂载与临时目录。
"""
import os
from pathlib import Path

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.emby_server import models as em
from backend.emby_server import portal, portal_mount_routes
from backend.integrations import store


@pytest.fixture()
def db():
    # TestClient 在线程池里跑路由，而线程里的 SQLite 连接不能跨线程用，
    # 所以要 check_same_thread=False + StaticPool（内存库只此一个连接）
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    em.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    store.invalidate()
    yield session
    store.invalidate()
    session.close()


@pytest.fixture()
def client(db, tmp_path, monkeypatch):
    """真路由 + 假鉴权（require_staff 直接给一个管理员），只有 DB 与目录是临时的"""
    staff = models.WebUser(username="boss", password_hash="x", is_staff=True)
    db.add(staff)
    db.commit()

    app = FastAPI()
    app.include_router(portal.admin_emby_router)
    app.include_router(portal_mount_routes.mount_picker_router)
    app.dependency_overrides[portal.require_staff] = lambda: staff

    def _get_db():
        yield db

    app.dependency_overrides[portal.get_db] = _get_db
    app.dependency_overrides[portal_mount_routes.get_db] = _get_db
    with TestClient(app) as c:
        yield c, db, tmp_path


def _mount(db, mount_type: str, name: str, path: str = "") -> em.StorageMount:
    row = em.StorageMount(name=name, mount_type=mount_type, path=path,
                          config="{}", is_enabled=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _library(db, paths: str, backends: str = "") -> em.Library:
    lib = em.Library(guid="g1", name="电影库", collection_type="movies",
                     paths=paths, storage_backends=backends)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


# ==================== 列表回显 ====================

def test_list_hides_mount_prefix_and_sends_backend_options(client):
    c, db, _ = client
    _mount(db, "115", "115 影库")
    _library(db, "mount://1/video/剧集/国产剧,/media/电影", "115,local")

    body = c.get("/api/admin/emby/libraries").json()

    entry = body["libraries"][0]["path_entries"][0]
    assert entry["path"] == "/video/剧集/国产剧"
    assert entry["backend"] == "115"
    assert entry["backend_label"] == "115 网盘"
    assert entry["mount_name"] == "115 影库"
    # 入库形态仍在（兼容老客户端与排障），但界面不用它显示
    assert body["libraries"][0]["paths"] == ["mount://1/video/剧集/国产剧", "/media/电影"]
    assert [(b["value"], b["label"]) for b in body["storage_backends"]] == [
        ("local", "本地文件"), ("rclone", "Rclone"), ("115", "115 网盘"),
    ]


def test_list_of_legacy_library_without_backends_column(client):
    """老库没有后端信息也要能打开设置页（不能因为一个新列就 500）"""
    c, db, _ = client
    _mount(db, "rclone", "谷歌云盘")
    lib = _library(db, "mount://1/Movies")
    db.execute(text("UPDATE emby_libraries SET storage_backends = ''"))
    db.commit()

    entry = c.get("/api/admin/emby/libraries").json()["libraries"][0]["path_entries"][0]

    assert (entry["path"], entry["backend"]) == ("/Movies", "rclone")
    assert lib.id


# ==================== 保存：界面写什么，库里存什么 ====================

def test_update_assembles_mount_prefix_and_keeps_backends_aligned(client):
    """界面传「裸路径 + 后端 + 挂载」→ 库里存成 mount:// 前缀 → 回显时又拆开

    用 **local 挂载**做远程来源的替身：它和 115/rclone 走的是同一条校验
    （check_mount_subpath 真的去列目录），但不需要网络，测试才跑得动。
    """
    c, db, tmp_path = client
    root = tmp_path / "挂载根"
    (root / "video" / "剧集" / "国产剧").mkdir(parents=True)
    mount = _mount(db, "local", "本机媒体盘", path=str(root))
    media = tmp_path / "电影"
    media.mkdir()
    lib = _library(db, "")

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={
        "path_entries": [
            {"path": "/video/剧集/国产剧", "backend": "local", "mount_id": mount.id},
            {"path": str(media), "backend": "local", "mount_id": None},
        ],
    })

    assert res.status_code == 200, res.text
    db.expire_all()
    db.refresh(lib)
    assert lib.paths == f"mount://{mount.id}/video/剧集/国产剧,{media}"
    assert lib.storage_backends == "local,local"

    # 回显回到界面：前缀再次被隐藏
    entry = c.get("/api/admin/emby/libraries").json()["libraries"][0]["path_entries"][0]
    assert entry["path"] == "/video/剧集/国产剧"
    assert entry["mount_name"] == "本机媒体盘"
    assert entry["source"] == "mount"


def test_update_rejects_missing_local_directory(client):
    c, db, _ = client
    lib = _library(db, "")

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={
        "path_entries": [{"path": "/nope/不存在", "backend": "local", "mount_id": None}],
    })

    assert res.status_code == 400
    assert "不存在" in res.json()["detail"]


def test_update_rejects_backend_mount_mismatch(client):
    c, db, _ = client
    mount = _mount(db, "rclone", "谷歌云盘")
    lib = _library(db, "")

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={
        "path_entries": [{"path": "/电影", "backend": "115", "mount_id": mount.id}],
    })

    assert res.status_code == 400
    assert "115 网盘" in res.json()["detail"]


def test_create_with_path_entries(client):
    c, db, tmp_path = client
    root = tmp_path / "挂载根"
    (root / "TV").mkdir(parents=True)
    mount = _mount(db, "local", "本机媒体盘", path=str(root))
    media = tmp_path / "剧集"
    media.mkdir()

    res = c.post("/api/admin/emby/libraries", json={
        "name": "剧集库",
        "collection_type": "tvshows",
        "path_entries": [
            {"path": "/TV", "backend": "local", "mount_id": mount.id},
            {"path": str(media), "backend": "local", "mount_id": None},
        ],
    })

    assert res.status_code == 200, res.text
    lib = db.query(em.Library).filter(em.Library.id == res.json()["id"]).one()
    assert lib.paths == f"mount://{mount.id}/TV,{media}"
    assert lib.storage_backends == "local,local"


def test_legacy_paths_payload_still_works(client):
    """老前端只发 paths：照样存得进去，且后端列被清空、回显时现推（不写死猜出来的值）"""
    c, db, tmp_path = client
    media = tmp_path / "电影"
    media.mkdir()
    lib = _library(db, "/media/旧", "local")

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={"paths": [str(media)]})

    assert res.status_code == 200, res.text
    db.expire_all()
    db.refresh(lib)
    assert lib.paths == str(media)
    assert lib.storage_backends == ""


# ==================== 本机目录浏览 ====================

def test_local_dirs_returns_same_shape_as_mount_browse(client):
    c, _, tmp_path = client
    (tmp_path / "电影").mkdir()
    (tmp_path / "剧集").mkdir()
    (tmp_path / "readme.txt").write_text("x")

    body = c.get("/api/admin/mounts/local-dirs", params={"path": str(tmp_path)}).json()

    assert body["path"] == str(tmp_path)
    assert [d["name"] for d in body["dirs"]] == ["剧集", "电影"]   # 只有目录，按名字排序
    assert body["dirs"][0]["path"] == f"{tmp_path}/剧集"
    # 面包屑逐级展开（与挂载浏览同口径），末段就是当前目录
    assert body["crumbs"][-1]["path"] == str(tmp_path)
    assert body["crumbs"][-1]["name"] == Path(tmp_path).name
    assert body["parent"] == str(tmp_path.parent)
    assert body["truncated"] is False


def test_local_dirs_root_and_parent(client):
    c, _, _ = client

    root = c.get("/api/admin/mounts/local-dirs", params={"path": "/"}).json()
    assert root["path"] == "/"
    assert root["parent"] is None
    assert any(d["name"] == "tmp" for d in root["dirs"])


def test_local_dirs_rejects_relative_path(client):
    c, _, _ = client

    res = c.get("/api/admin/mounts/local-dirs", params={"path": "relative/dir"})

    assert res.status_code == 400


def test_local_dirs_404_for_missing_directory(client):
    c, _, tmp_path = client

    res = c.get("/api/admin/mounts/local-dirs", params={"path": str(tmp_path / "nope")})

    assert res.status_code == 404


def test_local_dirs_400_for_file(client):
    c, _, tmp_path = client
    target = tmp_path / "a.mkv"
    target.write_bytes(b"x")

    res = c.get("/api/admin/mounts/local-dirs", params={"path": str(target)})

    assert res.status_code == 400