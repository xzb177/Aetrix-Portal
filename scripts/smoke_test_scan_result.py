#!/usr/bin/env python3
"""最近一次扫描结果可查询（v2.22.0）冒烟测试

扫描统计以前只在**返回值**与日志里：管理端刷新一下就没了，「上一轮到底扫到什么」只能去
服务器日志翻。现在一轮扫描结束会把结果写回媒体库（`scan_status` / `scan_stats` / `scan_error`），
并由 `GET /api/admin/emby/libraries` 一并带回（`last_scan`）。

这条测试钉的是**可查且诚实**：

1. 从没扫过 → `last_scan` 为 `None`（「没扫过」和「扫了但都是 0」不是一回事）；
2. 成功一轮 → 新增/更新/删除/耗时落库，换个 Session 还能读到（是落库不是内存）；
3. 重扫 → 覆盖上一轮（不是累加），删除的文件计入 removed；
4. 来源读不到 → partial，点名读不到的来源，并说明「已跳过清理」；
5. 来源恢复 → 回到 success、补上那一轮被跳过的清理、error 清空；
6. 扫描抛异常 → failed + 原因落库，互斥与 is_scanning 都要复位（否则这个库再也扫不动）；
7. 扫描中 → running（`is_scanning` 为真），收尾后复位；
8. 虚拟库（没有自己的目录）算成功；**完全没配来源**算 partial（不是「一切正常」）。

用法：python scripts/smoke_test_scan_result.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_TYPE"] = "sqlite"
os.environ["REDIS_ENABLED"] = "false"
DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.database import engine, init_db  # noqa: E402
from backend.emby_server import models as em  # noqa: E402
from backend.emby_server import portal as emby_portal  # noqa: E402
from backend.emby_server import scanner as sc  # noqa: E402

init_db()
Session = sessionmaker(bind=engine)

FAILED = []
TOTAL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(label)


def fake_probe(path, headers=None, size=0):  # noqa: ANN001, ARG001
    return {
        "duration_ticks": 600_000_000, "bitrate": 1_000_000, "width": 1920, "height": 1080,
        "video_codec": "H264", "audio_codec": "AAC", "audio_languages": "chi",
        "subtitle_languages": "", "size": size or 2048,
        "streams": [
            {"stream_index": 0, "stream_type": "Video", "codec": "h264", "language": "",
             "display_title": None, "title": None, "channels": None, "bit_rate": 1_000_000},
        ],
    }


class FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class FakeTmdbSession:
    def get(self, url, params=None):  # noqa: ANN001, ARG002
        if "/search/" in url:
            query = (params or {}).get("query") or ""
            return FakeResp({"results": [{"id": abs(hash(query)) % 900000 + 1,
                                          "title": query, "name": query, "vote_average": 7.0}]})
        return FakeResp({"poster_path": "/poster.jpg", "backdrop_path": "/backdrop.jpg",
                         "external_ids": {"imdb_id": "tt1"}, "alternative_titles": {"titles": []}})


MOVIES = 4

lib_dir = tempfile.mkdtemp(prefix="scanresult_")
movie_dir = os.path.join(lib_dir, "Movies")
os.makedirs(movie_dir, exist_ok=True)


def movie_path(i: int) -> str:
    return os.path.join(movie_dir, f"Result Movie {i:02d} (2021).mkv")


for i in range(MOVIES):
    with open(movie_path(i), "wb") as f:
        f.write(b"\x00" * 2048)

sc.probe_metadata = fake_probe
sc.tmdb_client.session = FakeTmdbSession()
sc.tmdb_client.api_keys = ["fake-key"]
sc.tmdb_client.api_key = "fake-key"

with Session() as db:
    lib = em.Library(guid="r" * 32, name="扫描结果测试库", collection_type="movies", paths=lib_dir)
    db.add(lib)
    db.commit()
    lib_id = lib.id


def scan() -> dict:
    with Session() as db:
        lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
        return sc.scan_library_sync(db, lib)


def snapshot() -> dict:
    """换个 Session 读库：读到什么就是真落库了什么（内存里的对象不算数）"""
    with Session() as db:
        lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
        return {
            "status": lib.scan_status,
            "stats": sc.decode_scan_stats(lib.scan_stats),
            "error": lib.scan_error,
            "last_scan_at": lib.last_scan_at,
            "is_scanning": lib.is_scanning,
            "payload": sc.scan_result_payload(lib),
        }


def item_count() -> int:
    with Session() as db:
        return int(db.query(em.MediaItem).filter(em.MediaItem.library_id == lib_id).count())


# ==================== 1. 从没扫过 ====================
print("=== 1. 从没扫过 ===")
before = snapshot()
check("从未扫描：状态与时间都是空", before["status"] is None and before["last_scan_at"] is None,
      f"status={before['status']} last_scan_at={before['last_scan_at']}")
check("从未扫描：last_scan 是 None（不是「全 0 的结果」）", before["payload"] is None,
      str(before["payload"]))

with Session() as db:
    listed = emby_portal.list_libraries(staff=None, db=db, realm_id=0)["libraries"]
row = next((x for x in listed if x["id"] == lib_id), None)
check("管理端列表带 last_scan 字段（未扫描时为 None）",
      row is not None and "last_scan" in row and row["last_scan"] is None,
      str(row.get("last_scan") if row else row))

# ==================== 2. 成功一轮：结果落库 ====================
print("\n=== 2. 成功一轮：结果落库 ===")
first = scan()
snap1 = snapshot()
check("首次扫描：状态 success", snap1["status"] == "success", str(snap1["status"]))
check("首次扫描：统计落库与返回值一致",
      snap1["stats"].get("added") == MOVIES and first["added"] == MOVIES,
      f"落库 added={snap1['stats'].get('added')} 返回 added={first['added']}")
check("统计落库：duration_ms 在（不被白名单丢掉）",
      isinstance(snap1["stats"].get("duration_ms"), int) and snap1["stats"]["duration_ms"] >= 0,
      f"duration_ms={snap1['stats'].get('duration_ms')!r}")
check("统计落库：没有失败来源、没有跳过清理",
      snap1["stats"].get("failed_roots") == [] and snap1["stats"].get("removal_skipped") is False,
      f"{snap1['stats'].get('failed_roots')} / {snap1['stats'].get('removal_skipped')}")
check("扫描结束 is_scanning 复位", snap1["is_scanning"] is False)

payload = snap1["payload"]
check("last_scan：状态 / 完成时间 / 新增数齐全",
      bool(payload) and payload["status"] == "success" and payload["finished_at"]
      and payload["added"] == MOVIES, str(payload))
check("last_scan：耗时为整数毫秒",
      isinstance(payload["duration_ms"], int) and payload["duration_ms"] >= 0,
      f"duration_ms={payload['duration_ms']!r}")
check("last_scan：成功时没有失败原因",
      payload["error"] is None and payload["failed_roots"] == [] and payload["removal_skipped"] is False,
      f"error={payload['error']!r} failed_roots={payload['failed_roots']}")

with Session() as db:
    listed = emby_portal.list_libraries(staff=None, db=db, realm_id=0)["libraries"]
row = next(x for x in listed if x["id"] == lib_id)
check("管理端列表里的 last_scan 与库内一致",
      row["last_scan"] == payload,
      "" if row["last_scan"] == payload else f"{row['last_scan']} != {payload}")

# ==================== 3. 重扫：覆盖上一轮（不是累加） ====================
print("\n=== 3. 重扫：覆盖上一轮 ===")
os.remove(movie_path(0))
second = scan()
snap2 = snapshot()
check("重扫：删掉的文件计入 removed", second["removed"] == 1 and snap2["stats"].get("removed") == 1,
      f"removed={second['removed']} / 落库 {snap2['stats'].get('removed')}")
check("重扫：新增数被清零（是覆盖不是累加）", snap2["stats"].get("added") == 0,
      f"added={snap2['stats'].get('added')}")
check("重扫：未变动与更新的条目合计 = 剩下的文件数",
      (snap2["stats"].get("updated") or 0) + (snap2["stats"].get("unchanged") or 0) == MOVIES - 1,
      f"updated={snap2['stats'].get('updated')} unchanged={snap2['stats'].get('unchanged')}")
check("重扫：状态仍是 success、removed 出现在 last_scan 里",
      snap2["payload"]["status"] == "success" and snap2["payload"]["removed"] == 1,
      str(snap2["payload"]))
check("重扫：完成时间向前推进", snap2["last_scan_at"] >= snap1["last_scan_at"],
      f"{snap1['last_scan_at']} → {snap2['last_scan_at']}")

# ==================== 4. 来源读不到：partial + 点名来源 ====================
print("\n=== 4. 来源读不到：partial ===")
bogus = os.path.join(lib_dir, "does-not-exist")
with Session() as db:
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    lib.paths = f"{lib_dir},{bogus}"
    db.commit()

# 同一个来源里再加一个新文件、同时删掉一个旧文件：
# 可读来源必须照常扫描（新文件入库），而清理阶段要跳过（旧文件的行留着）
with open(movie_path(9), "wb") as f:
    f.write(b"\x00" * 2048)
os.remove(movie_path(1))

third = scan()
snap3 = snapshot()
check("部分失败：状态 partial", snap3["status"] == "partial", str(snap3["status"]))
check("部分失败：读不到的来源被点名",
      any(bogus in r for r in snap3["stats"].get("failed_roots") or []),
      str(snap3["stats"].get("failed_roots")))
check("部分失败：removal_skipped 落库、payload 也标记",
      snap3["stats"].get("removal_skipped") is True and snap3["payload"]["removal_skipped"] is True,
      f"{snap3['stats'].get('removal_skipped')} / {snap3['payload']['removal_skipped']}")
check("部分失败：原因进了 last_scan.error（面板不用猜）",
      "does-not-exist" in (snap3["payload"]["error"] or ""), repr(snap3["payload"]["error"]))
check("部分失败：可读来源照常扫描（新文件入库）",
      third["added"] == 1 and third["removed"] == 0,
      f"added={third['added']} removed={third['removed']}")
check("部分失败：跳过清理 → 磁盘上已消失的条目仍留在库里（宁肯多留不误删）",
      item_count() == MOVIES, f"条目={item_count()} 期望={MOVIES}")

# ==================== 5. 来源恢复：回到 success 并补上清理 ====================
print("\n=== 5. 来源恢复 ===")
with Session() as db:
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    lib.paths = lib_dir
    db.commit()

fourth = scan()
snap4 = snapshot()
check("来源恢复后：状态回到 success", snap4["status"] == "success", str(snap4["status"]))
check("来源恢复后：补上上一轮被跳过的清理",
      fourth["removed"] == 1 and snap4["stats"].get("removed") == 1,
      f"removed={fourth['removed']} 条目={item_count()}")
check("来源恢复后：error 清空、failed_roots 清空",
      snap4["payload"]["error"] is None and snap4["payload"]["failed_roots"] == [],
      f"error={snap4['payload']['error']!r}")
check("来源恢复后：条目数与磁盘一致", item_count() == MOVIES - 1,
      f"条目={item_count()} 期望={MOVIES - 1}")

# ==================== 6. 扫描抛异常：failed + 原因落库 + 互斥复位 ====================
print("\n=== 6. 扫描抛异常 ===")


def boom(db, library, snap):  # noqa: ANN001, ARG001
    raise RuntimeError("模拟扫描崩溃")


real_body = sc._scan_library_body
sc._scan_library_body = boom
raised = False
try:
    scan()
except RuntimeError:
    raised = True
finally:
    sc._scan_library_body = real_body

snap5 = snapshot()
check("异常：向上抛出（调用方要知道这一轮失败了）", raised)
check("异常：状态 failed 落库", snap5["status"] == "failed", str(snap5["status"]))
check("异常：原因含异常类型与消息（不吞异常）",
      "RuntimeError" in (snap5["error"] or "") and "模拟扫描崩溃" in (snap5["error"] or ""),
      repr(snap5["error"]))
check("异常：last_scan 带 failed 与原因",
      snap5["payload"]["status"] == "failed"
      and "模拟扫描崩溃" in (snap5["payload"]["error"] or ""), str(snap5["payload"]))
check("异常：is_scanning 复位（不会永远显示「扫描中」）", snap5["is_scanning"] is False)
check("异常：进程内互斥已释放（这个库还能再扫）", sc.is_scan_active(lib_id) is False)

recovered = scan()
snap6 = snapshot()
check("异常之后能正常重扫并回到 success",
      recovered["added"] == 0 and snap6["status"] == "success" and snap6["payload"]["error"] is None,
      f"added={recovered['added']} status={snap6['status']} error={snap6['payload']['error']!r}")
check("重扫后 last_scan 不再残留上一轮的失败",
      snap6["payload"]["status"] == "success" and snap6["payload"]["failed_roots"] == [],
      str(snap6["payload"]))

# ==================== 7. 扫描中：running ====================
print("\n=== 7. 扫描中：running ===")
with Session() as db:
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    sc.begin_scan(db, lib)
pending = snapshot()
check("扫描中：状态 running 且 is_scanning 落库",
      pending["status"] == "running" and pending["is_scanning"] is True,
      f"status={pending['status']} is_scanning={pending['is_scanning']}")
check("扫描中：last_scan 报 running（前端据此显示「未完成」）",
      pending["payload"]["status"] == "running", str(pending["payload"]))
with Session() as db:
    lib = db.query(em.Library).filter(em.Library.id == lib_id).first()
    sc.finish_scan(db, lib, {"added": 0, "updated": 0, "removed": 0})
done = snapshot()
check("收尾后：状态 success 且 is_scanning 复位",
      done["status"] == "success" and done["is_scanning"] is False,
      f"status={done['status']} is_scanning={done['is_scanning']}")

# ==================== 8. 虚拟库与「没有来源」 ====================
print("\n=== 8. 虚拟库 / 没有来源 ===")
with Session() as db:
    vlib = em.Library(guid="v" * 32, name="平台虚拟库", collection_type="movies",
                      paths="", is_virtual=True)
    elib = em.Library(guid="e" * 32, name="没有来源的库", collection_type="movies", paths="")
    db.add_all([vlib, elib])
    db.commit()
    vid, eid = vlib.id, elib.id

with Session() as db:
    vrow = db.query(em.Library).filter(em.Library.id == vid).first()
    sc.scan_library_sync(db, vrow)
with Session() as db:
    vrow = db.query(em.Library).filter(em.Library.id == vid).first()
    vpay = sc.scan_result_payload(vrow)
check("虚拟库（没有自己的目录）算成功，不会被报成「来源不可用」",
      vpay["status"] == "success" and vpay["failed_roots"] == [],
      str(vpay))

with Session() as db:
    erow = db.query(em.Library).filter(em.Library.id == eid).first()
    sc.scan_library_sync(db, erow)
with Session() as db:
    erow = db.query(em.Library).filter(em.Library.id == eid).first()
    epay = sc.scan_result_payload(erow)
check("完全没配来源：算 partial（清理被跳过，不能报「一切正常」）",
      epay["status"] == "partial" and epay["removal_skipped"] is True, str(epay))
check("没有来源时的原因说清楚（不是含糊的「失败」）",
      "来源" in (epay["error"] or ""), repr(epay["error"]))

# ==================== 汇总 ====================
print()
if FAILED:
    print(f"❌ 扫描结果冒烟测试失败 {len(FAILED)}/{TOTAL} 项：")
    for label in FAILED:
        print(f"   - {label}")
    sys.exit(1)
print(f"✅ 扫描结果冒烟测试全部通过（{TOTAL} 项）")
