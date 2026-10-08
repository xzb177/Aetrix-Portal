"""集/季图片回退链不能逐条发 SQL（性能审查 P1）

旧实现 ``_image_chain`` 用 ``db.query(MediaItem).filter(id == parent_id).first()`` 取季，
Query 不走 identity map，每条集都发一次 SELECT；``_item_dto`` 的 Primary / Backdrop
各调一次 → 每条集 2 次 SQL。``Items?IncludeItemTypes=Episode&Limit=1000`` 实测 2015 条 SQL。
现在改成 ``db.get``：父条目已在会话里（列表接口预取过）就零 SQL，
不随集数增长。
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.emby_server import api  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server import soft_delete  # noqa: E402

N_EPISODES = 40


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://")
    em.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    lib = em.Library(guid="lib", name="剧集", collection_type="tvshows", paths="/media/tv")
    s.add(lib)
    s.flush()
    series = em.MediaItem(guid="ser", library_id=lib.id, name="剧", item_type="series", date_added=datetime.now(),
                          primary_image_url="http://img/series.jpg",
                          backdrop_image_url="http://img/series-bd.jpg")
    s.add(series)
    s.flush()
    season = em.MediaItem(guid="sea", name="第 1 季", item_type="season", library_id=lib.id, date_added=datetime.now(),
                          series_id=series.id, parent_id=series.id, season_number=1,
                          primary_image_url="http://img/season.jpg")
    s.add(season)
    s.flush()
    for i in range(N_EPISODES):
        s.add(em.MediaItem(guid=f"ep{i}", name=f"第 {i + 1} 集", item_type="episode",
                           library_id=lib.id, date_added=datetime.now(), series_id=series.id,
                           parent_id=season.id, season_number=1, episode_number=i + 1))
    s.commit()
    s.close()
    try:
        yield engine, Session
    finally:
        engine.dispose()


class _SqlCounter:
    def __init__(self, engine):
        self.engine = engine
        self.statements: list[str] = []

    def _on(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._on)


def _episodes(db):
    return db.query(em.MediaItem).filter(em.MediaItem.item_type == "episode").all()


def _chains(eps, db):
    return [api._image_chain(ep, kind, db) for ep in eps for kind in ("Primary", "Backdrop")]


def test_list_prefetch_then_image_chain_costs_zero_sql(factory):
    """列表接口的真实路径：_prefetch_list_data 之后，整页集的回退链 0 条 SQL（旧实现 2×N）"""
    engine, Session = factory
    db = Session()
    try:
        eps = _episodes(db)
        assert len(eps) == N_EPISODES
        api._prefetch_list_data(db, 1, eps)
        with _SqlCounter(engine) as c:
            chains = _chains(eps, db)
        assert c.statements == [], f"预取后仍逐条发 SQL：{len(c.statements)} 条"
        # 回退链内容不变：集自身无图 → 季 → 剧
        assert chains[0] == ["http://img/season.jpg", "http://img/series.jpg"]
        assert chains[1] == ["http://img/series-bd.jpg"]
    finally:
        db.close()


def test_parents_already_in_session_cost_zero_sql(factory):
    """父条目以任何方式已在会话里（详情页先取过剧/季等）：同样 0 条 SQL"""
    engine, Session = factory
    db = Session()
    try:
        eps = _episodes(db)
        parents = db.query(em.MediaItem).filter(
            em.MediaItem.item_type.in_(("season", "series"))).all()
        assert len(parents) == 2
        with _SqlCounter(engine) as c:
            _chains(eps, db)
        assert len(c.statements) == 0, f"{len(c.statements)} 条 SQL"
    finally:
        db.close()


def test_soft_deleted_parent_in_identity_map_is_skipped(factory, monkeypatch):
    """父条目已软删但还在会话里：与原 query() 口径一致，不进回退链"""
    monkeypatch.setenv("MEDIA_SOFT_DELETE", "1")
    engine, Session = factory
    db = Session()
    try:
        with soft_delete.include_deleted():
            season = db.query(em.MediaItem).filter(em.MediaItem.item_type == "season").one()
        season.deleted_at = datetime.now()
        db.flush()
        ep = _episodes(db)[0]
        assert api._image_chain(ep, "Primary", db) == ["http://img/series.jpg"]
        with soft_delete.include_deleted():
            assert api._image_chain(ep, "Primary", db) == [
                "http://img/season.jpg", "http://img/series.jpg"]
    finally:
        db.rollback()
        db.close()
