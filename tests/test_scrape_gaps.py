"""刮削「没刮干净」的三个根因回归。

生产实测：series 3263 条里 464 条没 TMDB、另有数百条有 tmdb 但缺简介/评分，
且 `enrich_status` 全是 done —— 失败被标记成完成，再也不会重试。

三个独立根因：

1. **全角冒号没归一化**：`90 Day： The Last Resort` 用全角 `：`（U+FF1A），
   TMDB 用半角 `:`，直接搜必然零结果（实测半角能搜到 2 条）。
2. **年份不符直接否决**：`_hit_score` 里「文件名年份 ≠ TMDB 年份 → return None」，
   把本来能命中的条目全部毙掉。目录年份常是**季/版本年份**而非首播年
   （实测 Schlag den Star 目录写 2009、TMDB 首播 2009-03-13 恰好一致，
   但 `90 Day： The Last Resort (2023)` 这类跨年条目会被误杀）。
3. **`vote_average == 0.0` 被当成「没数据」**：`if rating:` 对真实的 0 分判假值，
   评分永远写不进库（实测 `21天重养自己` 的 vote_average 就是 0.0）。

另外 `apply_details` 只落 imdb/别名，**不落 overview 和评分**，
所以「有 tmdb_id 但缺简介」的一大批永远补不上。
"""
from types import SimpleNamespace

import os
import tempfile

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")
_fd, _tmp = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
from backend import database as _dbmod
from sqlalchemy import create_engine as _ce
from sqlalchemy.orm import sessionmaker as _sm
_dbmod.engine = _ce(os.environ["DATABASE_URL"])
# 必须走 configure_session_local：直接赋值会把 SessionLocal 代理顶掉，
# 导致同批次其他测试（如 test_sessionlocal_proxy）绑定到建库前的旧 factory。
_dbmod.configure_session_local(_sm(bind=_dbmod.engine))
from backend.database import init_db
init_db()

from backend.emby_server import tmdb


def test_fullwidth_colon_normalized_in_query():
    """全角冒号必须归一化为半角，否则 TMDB 搜不到"""
    got = tmdb._clean_query("90 Day： The Last Resort")
    assert "：" not in got, got
    assert ":" in got, got


def test_fullwidth_colon_also_in_raw_name():
    cands = tmdb._search_candidates("90 Day： The Last Resort (2023)")
    assert cands, cands
    assert all("：" not in q for q, _ in cands), cands


def test_norm_text_strips_fullwidth_colon():
    assert tmdb._norm_text("90 Day： The Last Resort") == tmdb._norm_text("90 Day: The Last Resort")


def test_vote_average_zero_is_written():
    """0.0 是合法评分，不能被 if rating: 判假值丢掉"""
    item = SimpleNamespace(tmdb_id=None, last_scraped_at=None, overview=None,
                           community_rating=None, primary_image_url=None,
                           poster_path=None, backdrop_path=None,
                           backdrop_image_url=None, aliases="", genres="",
                           name="x", original_title=None)
    hit = {"id": 324071, "overview": "", "vote_average": 0.0,
           "poster_path": None, "backdrop_path": None, "name": "21天重养自己"}
    tmdb.TmdbClient().apply(item, hit, "series")
    assert item.community_rating == 0.0, item.community_rating


def test_apply_details_fills_overview_and_rating():
    """详情接口必须补上简介与评分（原来只落 imdb/别名）"""
    item = SimpleNamespace(tmdb_id="324071", last_scraped_at=None,
                           overview=None, community_rating=None,
                           primary_image_url=None, poster_path=None,
                           backdrop_path=None, backdrop_image_url=None,
                           aliases="", genres="", name="x", original_title=None)
    data = {
        "id": 324071, "name": "21天重养自己", "overview": "简介内容",
        "vote_average": 0.0,
        "external_ids": {"imdb_id": "tt123"},
        "alternative_titles": {},
    }
    tmdb.TmdbClient().apply_details(item, data)
    assert item.overview == "简介内容", item.overview
    assert item.community_rating == 0.0, item.community_rating
    assert item.imdb_id == "tt123"


def test_year_is_stripped_into_its_own_candidate():
    """目录名带的 (YYYY) 必须被剥成独立候选，否则永远匹配不上 TMDB 标题"""
    cands = tmdb._search_candidates("Schlag den Star (2009)")
    assert "Schlag den Star" in [q for q, _ in cands], cands


def test_year_mismatch_does_not_hard_reject():
    """年份对不上不应直接否决：降级为不加分，而非 return None"""
    hit = {"name": "Schlag den Star", "first_air_date": "2006-01-01"}
    # 走剥掉年份后的候选（生产真实路径）
    sc = tmdb._hit_score("Schlag den Star (2009)", "Schlag den Star", hit)
    assert sc is not None, "年份不符不该直接否决"


def test_fullwidth_colon_year_case_matches_halfwidth_title():
    """全角冒号 + 年份的真实失败样本，必须能对上 TMDB 的半角标题"""
    hit = {"name": "90 Day: The Last Resort", "first_air_date": "2023-08-14"}
    sc = tmdb._hit_score("90 Day： The Last Resort (2023)",
                         "90 Day: The Last Resort", hit)
    assert sc is not None, sc


def test_incomplete_stays_pending_for_retry():
    """没刮到 TMDB 的条目必须退回 pending，不能被标记成 done 永久躺平

    旧实现无条件 enrich_status='done'，而 _claim_batch 只捞 pending，
    于是搜不到的条目再也不会重试（生产 464 条 series 永久缺 TMDB）。
    """
    from backend.emby_server import enrich_worker
    from backend.emby_server import models as em
    from backend.emby_server import models as emby_models
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        lib = em.Library(guid="L" * 32, name="库", collection_type="tvshows", paths="")
        db.add(lib)
        db.flush()
        it = emby_models.MediaItem(guid="s" * 32, library_id=lib.id, item_type="series",
                                   name="Schlag den Star (2009)", overview="", tmdb_id=None,
                                   enrich_status="enriching", enrich_attempts=0,
                                   enrich_next_retry_at=None)
        db.add(it)
        db.flush()
        enrich_worker._enrich_apply(db, it, {"tmdb_hit": None, "tmdb_details": None,
                                            "poster": None, "fanart": None,
                                            "external_subs": [], "nfo_data": None})
        db.commit()
        assert it.enrich_status == "pending", f"未刮到应退回 pending，实为 {it.enrich_status}"
    finally:
        db.query(emby_models.MediaItem).delete()
        db.query(em.Library).delete()
        db.commit()
        db.close()


# ==================== 处方 12・Tier 1.5（C-14）：短中文标题的包含式匹配 ====================


def test_cjk_contain_rank_hits_for_short_title():
    """≥3 字中文查询是标题子串 → Tier 1.5 命中，rank=超长度的负值"""
    variants = [tmdb._norm_text("虎子的冒险")]
    names = [tmdb._norm_text("虎子的冒险日记")]
    hit = {"original_language": "zh", "original_name": "虎子的冒险日记"}
    got = tmdb._cjk_contain_rank(variants, names, hit)
    assert got == -(len("虎子的冒险日记") - len("虎子的冒险")), got


def test_cjk_contain_rank_rejects_two_char_query():
    """两字名（如「虎子」）不得包含式命中——先挡掉「虎子→老虎和兔子」类错配"""
    variants = [tmdb._norm_text("虎子")]
    names = [tmdb._norm_text("老虎和兔子")]
    hit = {"original_language": "zh", "original_name": "老虎和兔子"}
    assert tmdb._cjk_contain_rank(variants, names, hit) is None


def test_cjk_contain_rank_language_gate_blocks_latin_world():
    """语种/地区闸门：拉丁世界的同名巧合不参与包含式匹配"""
    variants = [tmdb._norm_text("虎子的冒险")]
    names = [tmdb._norm_text("虎子的冒险日记")]
    hit = {"original_language": "en", "origin_country": [],
           "original_name": "Tiger Kid"}   # 无 CJK 原名、非中日韩产物
    assert tmdb._cjk_contain_rank(variants, names, hit) is None


def test_hit_score_tier_15_when_lcs_structurally_impossible():
    """端到端：4 字查询对 7 字标题，Tier 1（lcs≥6）结构性不达标，Tier 1.5 接住"""
    hit = {"name": "风犬少年的天空", "original_name": "风犬少年的天空",
           "original_language": "zh"}
    sc = tmdb._hit_score("风犬少年 (2020)", "风犬少年", hit)
    assert sc is not None, "短中文标题必须能命中"
    assert sc[0] == 1.5, sc


def test_hit_score_gate_rejects_mismatch_in_end_to_end_path():
    """端到端：非中日韩产物 + 非精确匹配 → 整体拒绝（不降级到包含式）"""
    hit = {"name": "虎子的冒险日记", "original_name": "Tiger Kid",
           "original_language": "en", "origin_country": ["US"]}
    assert tmdb._hit_score("虎子的冒险 (2024)", "虎子的冒险", hit) is None
