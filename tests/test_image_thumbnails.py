"""图片缩略图：生成 / 按需尺寸 / 补生成水位 / 清理"""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.emby_server import image_store
from backend.emby_server import models as em
from backend import models as base_models  # noqa: F401 — 注册 web_users 等被 FK 引用的表

pytestmark = pytest.mark.skipif(
    not image_store.pil_available(), reason="Pillow 未安装"
)


@pytest.fixture()
def imgdir(tmp_path, monkeypatch):
    d = tmp_path / "images"
    d.mkdir()
    monkeypatch.setattr(image_store, "image_dir", lambda: str(d))
    monkeypatch.setenv("EMBY_THUMB_WIDTHS", "320,640")
    return str(d)


def _make_jpeg(path, w=800, h=1200, color=(200, 30, 30)):
    from PIL import Image

    img = Image.new("RGB", (w, h), color)
    img.save(path, "JPEG", quality=90)
    return path


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    em.Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_resized_variant_basic(imgdir):
    src = _make_jpeg(os.path.join(imgdir, "abc123.jpg"))
    thumb = image_store.resized_variant(src, max_width=320)
    assert thumb and os.path.isfile(thumb)
    assert thumb != src
    from PIL import Image

    with Image.open(thumb) as im:
        assert im.size[0] == 320
        assert im.size[1] == 480  # 等比
    assert os.path.getsize(thumb) < os.path.getsize(src)


def test_resized_variant_no_upscale(imgdir):
    src = _make_jpeg(os.path.join(imgdir, "small.jpg"), w=200, h=300)
    assert image_store.resized_variant(src, max_width=320) == ""


def test_resized_variant_missing_file(imgdir):
    assert image_store.resized_variant(os.path.join(imgdir, "nope.jpg"),
                                       max_width=320) == ""


def test_resized_variant_idempotent(imgdir):
    src = _make_jpeg(os.path.join(imgdir, "once.jpg"))
    first = image_store.resized_variant(src, max_width=320)
    mtime = os.path.getmtime(first)
    second = image_store.resized_variant(src, max_width=320)
    assert first == second
    assert os.path.getmtime(first) == mtime  # 第二次没重写


def test_resized_variant_height_only(imgdir):
    src = _make_jpeg(os.path.join(imgdir, "h.jpg"))
    thumb = image_store.resized_variant(src, max_height=600)
    assert thumb and os.path.isfile(thumb)
    from PIL import Image

    with Image.open(thumb) as im:
        assert im.size[1] == 600


def test_max_width_capped(imgdir):
    src = _make_jpeg(os.path.join(imgdir, "big.jpg"), w=3000, h=2000)
    thumb = image_store.resized_variant(src, max_width=99999)
    assert thumb and "_w1920" in thumb  # 钳制到上限，不会按 99999 生成


def test_thumb_widths_env(imgdir, monkeypatch):
    assert image_store.thumb_widths() == [320, 640]
    monkeypatch.setenv("EMBY_THUMB_WIDTHS", "100,abc,0,5000,100")
    assert image_store.thumb_widths() == [100]  # 非法/越界/重复被过滤


def test_thumb_digest():
    digest = "a" * 24
    assert image_store._thumb_digest(f"{digest}_w320.jpg") == digest
    assert image_store._thumb_digest(f"{digest}_w320h640.jpg") == digest
    assert image_store._thumb_digest(f"{digest}.jpg") is None
    assert image_store._thumb_digest("random.jpg") is None


def _add_item(db, imgdir, idx, name):
    src = _make_jpeg(os.path.join(imgdir, f"p{idx}.jpg"))
    item = em.MediaItem(guid=f"g{idx:08d}", library_id=1, item_type="movie",
                        name=name, poster_path=src)
    db.add(item)
    db.commit()
    return item


def test_backfill_processes_and_resumes(db, imgdir, monkeypatch):
    for i in range(3):
        _add_item(db, imgdir, i, f"m{i}")
    r1 = image_store.backfill_thumbnails(db, batch_size=2, max_seconds=60)
    assert r1["processed"] == 2
    assert r1["generated"] == 2
    assert not r1["done"]
    # 水位已提交：新 session 读到的是第 2 条
    assert image_store.backfill_status(db)["last_id"] == 2
    r2 = image_store.backfill_thumbnails(db, batch_size=10, max_seconds=60)
    assert r2["processed"] == 1
    assert r2["done"]
    # 缩略图确实落盘了
    thumbs = [f for f in os.listdir(imgdir) if "_w320" in f]
    assert len(thumbs) == 3


def test_backfill_skips_nonlocal(db, imgdir):
    item = em.MediaItem(guid="g00000099", library_id=1, item_type="movie",
                        name="remote", poster_path="https://example.com/a.jpg")
    db.add(item)
    db.commit()
    r = image_store.backfill_thumbnails(db, batch_size=10, max_seconds=60)
    assert r["generated"] == 0
    assert r["done"]


def test_prune_removes_orphan_thumbs_but_keeps_referenced(db, imgdir):
    item = _add_item(db, imgdir, 0, "keep")
    src = item.poster_path
    thumb = image_store.resized_variant(src, max_width=320)
    assert os.path.isfile(thumb)
    # 孤儿缩略图（原图 digest 不在库里）
    orphan = image_store.thumb_variant_path(
        os.path.join(imgdir, "b" * 24 + ".jpg"), 320)
    open(orphan, "wb").write(b"x")
    result = image_store.prune(db)
    assert os.path.isfile(src) and os.path.isfile(thumb)  # 被引用的不动
    assert not os.path.isfile(orphan)  # 孤儿缩略图被清
    assert result["removed"] >= 1


def test_clamp_dim_defensive():
    assert image_store._clamp_dim("320") == 320
    assert image_store._clamp_dim("abc") is None
    assert image_store._clamp_dim("") is None
    assert image_store._clamp_dim(None) is None
    assert image_store._clamp_dim("0") is None
    assert image_store._clamp_dim("-5") is None
    assert image_store._clamp_dim("99999") == 1920  # 上限钳制
