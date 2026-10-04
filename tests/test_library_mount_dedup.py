"""媒体库设置页挂载去重（v2.46.0）：界面只留「按类型添加路径」一个入口

改动前的界面上有三处重叠的挂载设置：媒体路径每条能选后端 / 库里能单选一批「存储挂载」/
高级折叠里能直接写 ``rclone:`` 前缀。去重后只剩第一条（弹窗里选类型 + 挂载）。

这里钉住的是**去重不能弄丢数据**这件事：

1. 前端不再下发 ``mount_ids`` 之后，后端必须**原样保留**老库上的挂载
   （``LibraryUpdate.mount_ids`` 省略 = 不修改，不是「清空」）；
2. 老库只剩 ``mount_ids``、一条路径都没有时，改个名字也得能存下去
   （v2.46.0 前 ``path_entries=[]`` 会被拼成空串并判成「目录不存在」）；
3. 但 ``mount_ids`` 这个字段本身仍然能写 —— 老前端与外部调用方还在用它，
   显式传列表照旧生效（删的只是界面，不是接口）。

不碰网络、不碰生产库；挂载用 local 类型当远程来源的替身。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import models
from backend.emby_server import models as em
from backend.emby_server import mounts as mnt
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


def _mount(db, mount_type: str = "local", name: str = "本机媒体盘", path: str = "") -> em.StorageMount:
    row = em.StorageMount(name=name, mount_type=mount_type, path=path,
                          config="{}", is_enabled=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _library(db, paths: str = "", mount_ids: str = "", name: str = "电影库") -> em.Library:
    lib = em.Library(guid="g1", name=name, collection_type="movies",
                     paths=paths, storage_backends="", mount_ids=mount_ids)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


# ==================== 1. 前端不再下发 mount_ids ≠ 清空 ====================

def test_omitted_mount_ids_is_left_untouched(client):
    """新界面的保存报文里没有 mount_ids —— 老库挂着的挂载必须原样留着

    ``LibraryUpdate.mount_ids`` 默认 None，路由里靠 ``is not None`` 判「有没有传」：
    省略 = 不修改。写成「省略 = 清空」的话，去重这个界面改动就会静默抹掉存量数据。
    """
    c, db, tmp_path = client
    mount = _mount(db)
    lib = _library(db, "", str(mount.id))

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={"name": "电影库改名"})

    assert res.status_code == 200, res.text
    db.expire_all()
    db.refresh(lib)
    assert lib.mount_ids == str(mount.id)
    assert lib.name == "电影库改名"
    # 扫描 / 追新 / 挂载健康都按 mount_ids 取来源，它还在，行为就不变
    assert mnt.parse_mount_ids(lib) == [mount.id]


def test_explicit_mount_ids_still_writes_for_legacy_callers(client):
    """字段没被删：老前端与外部调用方显式传列表，照旧写入"""
    c, db, _ = client
    old_mount = _mount(db, name="旧挂载")
    new_mount = _mount(db, name="新挂载")
    lib = _library(db, "", str(old_mount.id))

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={"mount_ids": [new_mount.id]})

    assert res.status_code == 200, res.text
    db.expire_all()
    db.refresh(lib)
    assert lib.mount_ids == str(new_mount.id)


def test_explicit_empty_mount_ids_still_clears(client):
    """显式传空列表仍然是「解绑」：接口语义没被悄悄改成「只能加不能减」"""
    c, db, _ = client
    mount = _mount(db)
    lib = _library(db, "", str(mount.id))

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={"mount_ids": []})

    assert res.status_code == 200, res.text
    db.expire_all()
    db.refresh(lib)
    assert lib.mount_ids == ""
    assert mnt.parse_mount_ids(lib) == []


def test_omitted_field_is_not_in_model_fields_set():
    """钉住「省略」在 pydantic 这层的形状：路由判据就是它

    没有这一条，将来有人把默认值改成 ``[]``，上面三条会一起失效而测试还绿着。
    """
    assert "mount_ids" not in portal.LibraryUpdate().model_fields_set
    assert "mount_ids" in portal.LibraryUpdate(mount_ids=[]).model_fields_set


# ==================== 2. 「只有挂载、一条路径都没有」的老库也存得下去 ====================

def test_legacy_mount_only_library_can_be_saved(client):
    """老库只剩 mount_ids 时改名字：以前会被空路径挡成 400

    ``path_entries=[]`` 拼出空串再 ``split(",")`` 成 ``[""]``，不跳过空条目的话
    会被判成「目录不存在」——界面上明明看不出哪里错了。
    """
    c, db, _ = client
    mount = _mount(db)
    lib = _library(db, "", str(mount.id))

    res = c.put(f"/api/admin/emby/libraries/{lib.id}",
                json={"name": "老库改名", "path_entries": []})

    assert res.status_code == 200, res.text
    db.expire_all()
    db.refresh(lib)
    assert lib.name == "老库改名"
    assert lib.paths == ""
    assert lib.mount_ids == str(mount.id)


def test_validate_library_sources_skips_blank_entries(client):
    """空串 / 纯空白不算一条路径（不是「目录不存在」）"""
    _, db, _ = client

    portal._validate_library_sources(db, ["", "   "], [])   # 不抛即为通过


def test_validate_library_sources_still_rejects_missing_dir(client):
    """跳过空条目不等于放宽校验：真写错的目录照样得拦"""
    _, db, _ = client

    with pytest.raises(Exception) as err:
        portal._validate_library_sources(db, ["/nope/真不存在"], [])
    assert "不存在" in str(getattr(err.value, "detail", err.value))


def test_update_rejects_missing_local_directory(client):
    """端到端那条：界面加了个不存在的目录，保存要被拒（不能被上面的空条目放行）"""
    c, db, _ = client
    lib = _library(db, "")

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={
        "path_entries": [{"path": "/nope/不存在", "backend": "local", "mount_id": None}],
    })

    assert res.status_code == 400
    assert "不存在" in res.json()["detail"]


# ==================== 3. 挂载已经写在那一条路径上，就够了 ====================

def test_mount_source_rides_on_the_path_entry_alone(client):
    """弹窗选好「类型 + 挂载」后，库里只有 paths 一处来源：不再有第二个 mount_ids

    扫描侧按 ``paths`` 里的 ``mount://<id>/<子目录>`` 取到内容，所以前端不下发
    ``mount_ids`` 也不会让这个库扫不到东西。
    """
    c, db, tmp_path = client
    root = tmp_path / "挂载根"
    (root / "Movies").mkdir(parents=True)
    mount = _mount(db, path=str(root))
    lib = _library(db, "")

    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={
        "path_entries": [{"path": "/Movies", "backend": "local", "mount_id": mount.id}],
    })

    assert res.status_code == 200, res.text
    db.expire_all()
    db.refresh(lib)
    assert lib.paths == f"mount://{mount.id}/Movies"
    assert lib.mount_ids == ""

    sources, failed = mnt.library_sources(lib, db)
    assert failed == []
    assert [(s.kind, s.label) for s in sources] == [("mount", f"mount://{mount.id}/Movies")]


def test_new_library_defaults_to_local_backend(client):
    """新界面不加后端列时，默认就是本地文件（不用每次都选一次）"""
    c, db, tmp_path = client
    media = tmp_path / "电影"
    media.mkdir()

    res = c.post("/api/admin/emby/libraries", json={
        "name": "本地库",
        "path_entries": [{"path": str(media)}],
    })

    assert res.status_code == 200, res.text
    body = c.get("/api/admin/emby/libraries").json()
    lib = next(x for x in body["libraries"] if x["name"] == "本地库")
    assert lib["path_entries"][0]["backend"] == "local"
    assert lib["path_entries"][0]["backend_label"] == "本地文件"
    assert lib["mount_ids"] == []


def test_legacy_prefix_entry_still_round_trips(client):
    """老库里 ``rclone:gdrive/Movies`` 这种前缀路径：去重后仍能原样读写

    界面不再提供新建前缀路径的入口，但**存量**条目不能因此被改坏、消失，
    也不能把整个表单卡死（以前校验拿 ``os.path.isdir`` 去判它，必然报「不存在」）。
    """
    c, db, tmp_path = client
    media = tmp_path / "电影"
    media.mkdir()
    lib = _library(db, f"rclone:gdrive/Movies,{media}")

    entry = c.get("/api/admin/emby/libraries").json()["libraries"][0]["path_entries"][0]
    assert (entry["path"], entry["backend"], entry["source"]) == (
        "rclone:gdrive/Movies", "rclone", "prefix")

    # 原样回存（界面不改这一条，只是顺手存了别的字段）
    res = c.put(f"/api/admin/emby/libraries/{lib.id}", json={
        "path_entries": [
            {"path": "rclone:gdrive/Movies", "backend": "rclone", "mount_id": None},
            {"path": str(media), "backend": "local", "mount_id": None},
        ],
    })

    assert res.status_code == 200, res.text
    db.expire_all()
    db.refresh(lib)
    assert lib.paths == f"rclone:gdrive/Movies,{media}"


def test_prefix_path_is_left_for_the_scanner_to_judge(client):
    """前缀路径存得进去，但「远端通不通」交给扫描期判定（它会记成不可用来源）

    保存时硬判会让存量库改个名字都存不下去；扫描期反而知道得更准（带重试与凭据）。
    """
    c, db, _ = client
    lib = _library(db, "rclone:gdrive/Movies")

    sources, failed = mnt.library_sources(lib, db)

    assert sources == []
    assert len(failed) == 1
    assert failed[0]["label"] == "rclone:gdrive/Movies"