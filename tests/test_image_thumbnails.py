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
    src = _make_jpeg(os.path.join(imgdir, "big.jpg"), w=6000, h=4000)
    thumb = image_store.resized_variant(src, max_width=99999)
    assert thumb and "_w640" in thumb  # 钳制后吸附到最大配置档（防无界变体）


def test_thumb_widths_env(imgdir, monkeypatch):
    assert image_store.thumb_widths() == [320, 640]
    monkeypatch.setenv("EMBY_THUMB_WIDTHS", "100,abc,0,5000,100")
    assert image_store.thumb_widths() == [100]  # 非法/越界/重复被过滤


def test_thumb_digest():
    digest = "a" * 40  # 真实是 40 位 sha1（localize 落盘名）
    assert image_store._thumb_digest(f"{digest}_w320.jpg") == digest
    assert image_store._thumb_digest(f"{digest}_w320_h640.jpg") == digest
    assert image_store._thumb_digest(f"{digest}_h640.jpg") == digest
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
    assert image_store._clamp_dim("99999") == image_store._THUMB_MAX_DIM  # 上限钳制


def test_pick_dim_priority():
    # 标准 Emby 参数优先于 w/h 别名；非法值跳过取下一个
    assert image_store.pick_dim("320", "160") == 320
    assert image_store.pick_dim(None, "300") == 300
    assert image_store.pick_dim("abc", "300") == 300
    assert image_store.pick_dim(None, None) is None
    assert image_store.pick_dim("0", "300") == 300


def test_thumb_mem_cache_lru():
    cache = image_store._ThumbMemCache()
    cache.put("a", b"x" * 100)
    cache.put("b", b"y" * 100)
    assert cache.get("a") == b"x" * 100
    assert cache.get("missing") is None
    # 单条目超限不进缓存
    cache.put("big", b"z" * (image_store._THUMB_MEM_ENTRY_MAX + 1))
    assert cache.get("big") is None
    # drop 清掉
    cache.drop("a")
    assert cache.get("a") is None


def test_thumb_mem_cache_evicts_oldest():
    import backend.emby_server.image_store as m
    old_cap = m._THUMB_MEM_CAP
    m._THUMB_MEM_CAP = 250  # 临时调小，验证淘汰
    try:
        c = m._ThumbMemCache()
        c.put("k1", b"1" * 100)
        c.put("k2", b"2" * 100)
        c.put("k3", b"3" * 100)  # 300 > 250，最老的 k1 被淘汰
        assert c.get("k1") is None
        assert c.get("k2") == b"2" * 100
        assert c.get("k3") == b"3" * 100
        snap = c.snapshot()
        assert snap["bytes"] <= 250 and snap["entries"] == 2
    finally:
        m._THUMB_MEM_CAP = old_cap


def test_huge_image_rejected(imgdir, monkeypatch):
    import backend.emby_server.image_store as m
    monkeypatch.setattr(m, "_THUMB_MAX_PIXELS", 10_000)  # 临时调小门限
    p = _make_jpeg(os.path.join(str(imgdir), "huge.jpg"), w=500, h=500)  # 250000 > 10000
    assert m.resized_variant(p, max_width=320) == ""


def test_gen_semaphore_bounded():
    import threading
    sem = image_store._GEN_SEMAPHORE
    assert isinstance(sem, type(threading.Semaphore()))
    assert sem._value == image_store._THUMB_CONCURRENCY


def test_is_thumb_variant():
    # 真实命名：40 位 sha1 + _w320（之前 _thumb_digest 按 24 位写，真实缩略图识别不出来）
    assert image_store.is_thumb_variant("/x/" + "a" * 40 + "_w320.jpg")
    assert image_store.is_thumb_variant("/x/" + "b" * 40 + "_w320_h640.jpg")
    assert image_store.is_thumb_variant("/x/" + "c" * 40 + "_h640.jpg")
    assert not image_store.is_thumb_variant("/x/" + "b" * 40 + ".jpg")
    assert not image_store.is_thumb_variant("")
    assert image_store._thumb_digest("d" * 40 + "_w320.jpg") == "d" * 40
    assert image_store._thumb_digest("e" * 40 + ".jpg") is None


def test_concurrent_burst_no_deadlock(imgdir):
    """海报墙突发：20 线程同时要 5 张不同缩略图，信号量限流但不死锁"""
    import threading
    srcs = [_make_jpeg(os.path.join(imgdir, f"c{i}.jpg"), w=1200, h=800)
            for i in range(5)]
    results, errors = [], []

    def worker(s):
        try:
            results.append(image_store.resized_variant(s, max_width=320))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,))
               for s in srcs for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
        assert not t.is_alive(), "转码线程卡死（疑似死锁）"
    assert not errors
    assert len(results) == 20
    # 非阻塞信号量：抢不到名额的返回空字符串（调用方回退原图），这是刻意设计防线程池饿死
    # 断言：无死锁、无异常；非空结果是 5 张图的去重缩略图（单飞依然有效）
    non_empty = [r for r in results if r]
    assert len(set(non_empty)) <= 5  # 单飞：同一源只生成一次
    assert all(r.endswith("_w320.jpg") for r in non_empty)
