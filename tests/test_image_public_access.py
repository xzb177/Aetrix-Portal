"""条目图片端点：不带任何凭据也能取图（H2 之后 URL 里不再带 JWT / api_key）

用户端首页「本周入库」直接用 <img src="{EA}/emby/Items/{id}/Images/Primary?maxWidth=320">
跨域取图：浏览器不会给它加 Authorization 头，跨站 Cookie 也不保证带上。所以这个端点
必须**不依赖任何鉴权**——以后谁给它加上 token 校验，首页海报会整排变成占位卡，这里先拦住。

同时覆盖首页的取图口径：单集按「集 → 季 → 剧」回退到剧的海报；剧本体直接出图；带 maxWidth
时出缩略图。
"""
import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

import uuid

import pytest

PIL = pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.emby_server import models as em  # noqa: E402

init_db()


def _guid():
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def client():
    from emby_api.main import app

    # 不进 lifespan：只测路由本身（启动钩子要 SECRET_KEY / Redis 等运行期依赖）
    return TestClient(app)


@pytest.fixture()
def seed(tmp_path):
    from PIL import Image

    poster = tmp_path / f"poster_{_guid()}.jpg"
    Image.new("RGB", (800, 1200), (180, 40, 40)).save(poster, "JPEG")
    db = SessionLocal()
    try:
        lib = em.Library(guid=_guid(), name="图片测试库", collection_type="tvshows")
        db.add(lib)
        db.flush()
        series = em.MediaItem(guid=_guid(), library_id=lib.id, item_type="series",
                              name="沧元图", poster_path=str(poster))
        db.add(series)
        db.flush()
        season = em.MediaItem(guid=_guid(), library_id=lib.id, item_type="season",
                              name="第 1 季", series_id=series.id, parent_id=series.id,
                              season_number=1)
        db.add(season)
        db.flush()
        episode = em.MediaItem(guid=_guid(), library_id=lib.id, item_type="episode",
                               name="沧元图 S01E58", series_id=series.id,
                               parent_id=season.id, season_number=1, episode_number=58)
        db.add(episode)
        db.commit()
        return {"series": series.guid, "episode": episode.guid}
    finally:
        db.close()


@pytest.mark.parametrize("which", ["series", "episode"])
@pytest.mark.parametrize("query", ["", "?maxWidth=320"])
def test_primary_image_needs_no_credentials(client, seed, which, query):
    r = client.get(f"/emby/Items/{seed[which]}/Images/Primary{query}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/")
    assert r.content


def test_thumbnail_is_smaller_than_original(client, seed):
    full = client.get(f"/emby/Items/{seed['series']}/Images/Primary")
    small = client.get(f"/emby/Items/{seed['series']}/Images/Primary?maxWidth=320")
    assert full.status_code == small.status_code == 200
    assert len(small.content) < len(full.content)


def test_unknown_item_is_404_not_401(client):
    r = client.get(f"/emby/Items/{_guid()}/Images/Primary")
    assert r.status_code == 404
