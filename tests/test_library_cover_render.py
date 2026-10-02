"""媒体库封面三样式渲染冒烟：每种模板都能出 1920×1080 WebP，不抛异常。

用 PIL 现场生成假海报/假横图，不依赖网络和真实库。
"""
import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from backend.emby_server import library_cover_render as render_mod


def _make_image(path, size, color):
    Image.new("RGB", size, color).save(path, "JPEG")


@pytest.fixture()
def posters(tmp_path):
    paths = []
    for i, color in enumerate([(20, 120, 90), (150, 60, 40),
                               (40, 60, 150), (120, 120, 30)]):
        p = tmp_path / f"poster_{i}.jpg"
        _make_image(str(p), (500, 750), color)
        paths.append(str(p))
    return paths


@pytest.fixture()
def backdrop(tmp_path):
    p = tmp_path / "backdrop.jpg"
    _make_image(str(p), (1280, 720), (90, 30, 30))
    return str(p)


class _FakeItem:
    def __init__(self, poster=None, backdrop=None):
        self.library_id = 7
        self.last_scraped_at = datetime.now(timezone.utc)
        self.poster_path = poster
        self.primary_image_url = None
        self.backdrop_path = backdrop
        self.backdrop_image_url = None


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def limit(self, n):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, model):
        return _FakeQuery(self._rows)


class _FakeLibrary:
    id = 7
    name = "测试库"
    collection_type = "tvshows"


@pytest.mark.parametrize("template", ["poster", "visual", "filmstrip"])
def test_render_all_templates_produce_webp(template, posters, backdrop):
    items = [_FakeItem(posters[0], backdrop), _FakeItem(posters[1]),
             _FakeItem(posters[2]), _FakeItem(posters[3])]
    data = render_mod.render_cover_bytes(
        _FakeDB(items), _FakeLibrary(), template=template,
        title="{library}", subtitle="{type} · {year}",
    )
    assert data, f"{template} 返回为空"
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    img = Image.open(io.BytesIO(data))
    assert img.size == (1920, 1080)


def test_render_unknown_template_falls_back_to_default(posters):
    items = [_FakeItem(posters[0])]
    data = render_mod.render_cover_bytes(
        _FakeDB(items), _FakeLibrary(), template="nope",
        title="标题", subtitle="副标题",
    )
    assert data and data[:4] == b"RIFF"


def test_render_no_posters_returns_none():
    assert render_mod.render_cover_bytes(
        _FakeDB([]), _FakeLibrary(), template="visual") is None


def test_render_text_variables():
    assert render_mod.render_text(
        "{library}·{type}·{year}", "国产剧", "tvshows", 2026) == "国产剧·剧集·2026"
    assert render_mod.render_text("  ", "x", "y") == ""
    assert render_mod.human_media_type("movies") == "电影"
