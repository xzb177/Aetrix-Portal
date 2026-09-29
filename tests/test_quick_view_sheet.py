"""QuickViewSheet 契约测试：媒体库轻量快线接线不断（借鉴 go-emby 的 grep 契约思路）。"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHEET = REPO / "user_frontend/src/components/media/QuickViewSheet.vue"
CARD = REPO / "user_frontend/src/components/media/MediaCard.vue"
LIB = REPO / "user_frontend/src/views/media/LibraryView.vue"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_sheet_exists():
    assert SHEET.exists(), "QuickViewSheet.vue 缺失"


def test_sheet_contract():
    s = read(SHEET)
    # 数据口径：与 ItemDetailView 一致
    for marker in ["embyApi.getItem", "embyApi.getSeasons", "embyApi.getEpisodes",
                   "posterUrl", "backdropUrl", "/watch/"]:
        assert marker in s, f"sheet 缺少契约标记: {marker}"
    # 功能点：版本选择 + 选集 + 播放 + 详情入口
    for marker in ["hasVersions", "qv-ep-grid", "playMovie", "goDetail", "role=\"dialog\""]:
        assert marker in s, f"sheet 缺少功能标记: {marker}"


def test_mediacard_quickview_prop():
    s = read(CARD)
    assert "quickView" in s, "MediaCard 缺少 quickView prop"
    assert "'quick-view'" in s or '"quick-view"' in s, "MediaCard 缺少 quick-view emit"


def test_library_wires_sheet():
    s = read(LIB)
    assert "QuickViewSheet" in s, "LibraryView 未引入 QuickViewSheet"
    assert "sheetItemId" in s, "LibraryView 未接 sheetItemId"
    assert "@quick-view" in s, "LibraryView 未监听 quick-view 事件"
    # 老功能保留：详情整页路由仍在
    assert "/media/${" in s or "/media/" in s, "详情页路由入口丢失"
