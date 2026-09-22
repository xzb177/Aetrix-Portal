"""用户端 v2.5.0 新增/修复端点冒烟测试

覆盖：
- GET    /api/user/media-seek/lookup        求片前库存查询（已在库直接引导播放）
- POST   /api/user/media-seek               求片提交（去重 409 / 每日额度 429）
- DELETE /api/user/media-seek/{id}          撤回未处理的求片（已处理 → 400）
- GET    /api/user/media-seek               列表 + 今日额度
-        新求片/新工单落站内消息给管理员（此前只有 TODO 未实现）
- GET    /api/user/emby/history             观看历史（按条目去重 + 类型筛选）
- GET    /api/user/emby/sessions            我的播放会话
- DELETE /api/user/emby/sessions/{key}      结束自己的会话（他人会话 → 404）
- GET    /api/user/emby-servers             死接口已下线（404）
"""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("DATABASE_URL", "sqlite:///./royalbot_unified.db")

from fastapi.testclient import TestClient

from backend import models
from backend.database import SessionLocal, init_db
from backend.emby_server import models as em
from backend.main import app
from backend.security import hash_password

init_db()
client = TestClient(app)
suf = str(random.randint(100000, 999999))
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


# ---------- 造数据 ----------
db = SessionLocal()
staff = models.WebUser(username=f"stf{suf}", password_hash=hash_password("staff12345"), is_staff=True)
user = models.WebUser(username=f"usr{suf}", password_hash=hash_password("user12345"))
other = models.WebUser(username=f"oth{suf}", password_hash=hash_password("user12345"))
db.add_all([staff, user, other])
db.commit()
for row in (staff, user, other):
    db.refresh(row)

library = em.Library(guid=f"lib{suf}", name=f"电影库{suf}", collection_type="movies")
db.add(library)
db.commit()
db.refresh(library)

db.add_all([
    em.MediaItem(
        guid=f"mv{suf}", library_id=library.id, item_type="movie",
        name=f"盗梦空间{suf}", production_year=2010, duration_ticks=8_880_000_000,
    ),
    em.MediaItem(
        guid=f"ep{suf}", library_id=library.id, item_type="episode",
        name=f"绝命毒师 S01E01{suf}", duration_ticks=3_600_000_000,
    ),
])
db.commit()
movie = db.query(em.MediaItem).filter(em.MediaItem.guid == f"mv{suf}").first()
episode = db.query(em.MediaItem).filter(em.MediaItem.guid == f"ep{suf}").first()

# 用户观看记录：同一电影两次会话（历史应去重），外加一集剧
now = datetime.now()
db.add_all([
    em.PlaybackSession(
        session_key=f"old{suf}", user_id=user.id, item_id=movie.id,
        device_name="iPad", client_name="Infuse", play_method="DirectStream",
        start_time=now - timedelta(days=2), last_update_at=now - timedelta(days=2),
        position_ticks=1_000, ended_at=now - timedelta(days=1),
    ),
    em.PlaybackSession(
        session_key=f"new{suf}", user_id=user.id, item_id=movie.id,
        device_name="Apple TV", client_name="Emby", play_method="Transcode",
        start_time=now - timedelta(hours=3), last_update_at=now - timedelta(hours=2),
        position_ticks=4_440_000_000, ended_at=now - timedelta(hours=1),
    ),
    em.PlaybackSession(
        session_key=f"live{suf}", user_id=user.id, item_id=episode.id,
        device_name="Chrome", client_name="Web", play_method="DirectStream",
        start_time=now, last_update_at=now, position_ticks=600_000_000,
    ),
    em.PlaybackSession(
        session_key=f"other{suf}", user_id=other.id, item_id=episode.id,
        device_name="手机", client_name="Emby", start_time=now, last_update_at=now,
    ),
    em.UserMediaData(
        user_id=user.id, item_id=movie.id, playback_position_ticks=4_440_000_000,
        play_count=2, played=True,
    ),
])
# 每日额度配置做 upsert，保证脚本可重复执行
limit_cfg = db.query(models.SystemConfig).filter(
    models.SystemConfig.key == "media_seek_daily_limit"
).first()
if limit_cfg:
    limit_cfg.value = "3"
else:
    db.add(models.SystemConfig(key="media_seek_daily_limit", value="3", description="冒烟测试用"))
db.commit()
user_name, staff_name, other_name = user.username, staff.username, other.username
db.close()

r = client.post("/api/user/auth/login", json={"username": user_name, "password": "user12345"})
check("用户登录", r.status_code == 200, str(r.status_code))
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

r = client.post("/api/user/auth/login", json={"username": staff_name, "password": "staff12345"})
check("管理员登录", r.status_code == 200, str(r.status_code))
staff_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------- 求片：库存查询 ----------
r = client.get("/api/user/media-seek/lookup", params={"name": f"盗梦空间{suf}"}, headers=headers)
body = r.json() if r.status_code == 200 else {}
check("库存查询：片名命中媒体库", r.status_code == 200 and body.get("in_library") is True
      and body["items"][0]["name"].startswith("盗梦空间"), str(r.status_code))

r = client.get("/api/user/media-seek/lookup", params={"name": f"不存在的片子{suf}"}, headers=headers)
check("库存查询：未入库", r.status_code == 200 and r.json()["in_library"] is False, str(r.status_code))


# ---------- 求片：提交 / 去重 / 额度 ----------
seek_name = f"沙丘{suf}"
r = client.post("/api/user/media-seek", json={"movie_name": seek_name, "year": "2021"}, headers=headers)
first_id = r.json().get("request_id") if r.status_code == 200 else None
check("提交求片", r.status_code == 200 and bool(first_id), str(r.status_code))

r = client.post("/api/user/media-seek", json={"movie_name": seek_name}, headers=headers)
check("同名处理中去重 → 409", r.status_code == 409, str(r.status_code))

r = client.post("/api/user/media-seek", json={"movie_name": "   "}, headers=headers)
check("空片名 → 400", r.status_code == 400, str(r.status_code))

# 额度：limit=3，已用 1，再提交 2 条后第 4 条应 429
for i in range(2):
    client.post("/api/user/media-seek", json={"movie_name": f"额度片{i}{suf}"}, headers=headers)
r = client.post("/api/user/media-seek", json={"movie_name": f"超额片{suf}"}, headers=headers)
check("每日额度上限 → 429", r.status_code == 429, str(r.status_code))

r = client.get("/api/user/media-seek", headers=headers)
body = r.json() if r.status_code == 200 else {}
check("求片列表带额度",
      r.status_code == 200 and body["quota"] == {"used_today": 3, "daily_limit": 3, "remaining": 0},
      str(body.get("quota")))

# ---------- 求片：通知管理员（此前是 TODO） ----------
r = client.get("/api/user/messages", headers=staff_headers)
titles = [m["title"] for m in r.json()] if r.status_code == 200 else []
check("新求片已落站内消息给管理员", any("求片" in t for t in titles), str(titles[:3]))


# ---------- 求片：撤回（改状态而非删行） ----------
r = client.delete(f"/api/user/media-seek/{first_id}", headers=headers)
check("撤回未处理求片", r.status_code == 200, str(r.status_code))

# 撤回不退还当天额度：否则「提交 → 撤回 → 再提交」可以无限刷新额度，
# 而每次提交都会给全体管理员推一条站内消息，等于一个通知刷屏器。
r = client.post("/api/user/media-seek", json={"movie_name": f"撤回后再交{suf}"}, headers=headers)
check("撤回不退额度 → 429", r.status_code == 429, str(r.status_code))

r = client.get("/api/user/media-seek", headers=headers)
body = r.json() if r.status_code == 200 else {}
check("额度按今天的提交数算（含已撤回）", body.get("quota") == {
    "used_today": 3, "daily_limit": 3, "remaining": 0,
}, str(body.get("quota")))
check("已撤回的条目不列在求片列表里",
      all(x["id"] != first_id for x in body.get("requests", [])), str(body.get("requests")))

db = SessionLocal()
withdrawn = db.query(models.MovieRequest).filter(
    models.MovieRequest.id == first_id).first()
check("撤回是改状态，不是删行（后台仍看得到这条提交）",
      withdrawn is not None and withdrawn.status == "withdrawn",
      withdrawn.status if withdrawn else "None")
db.close()

db = SessionLocal()
pending = models.MovieRequest(
    user_id=db.query(models.WebUser).filter(models.WebUser.username == user_name).first().id,
    movie_name=f"已批准{suf}", status="approved",
)
db.add(pending)
db.commit()
approved_id = pending.id
db.close()

r = client.delete(f"/api/user/media-seek/{approved_id}", headers=headers)
check("已处理求片不可撤回 → 400", r.status_code == 400, str(r.status_code))

r = client.delete("/api/user/media-seek/99999999", headers=headers)
check("撤回不存在的求片 → 404", r.status_code == 404, str(r.status_code))


# ---------- 观看历史 ----------
r = client.get("/api/user/emby/history", headers=headers)
body = r.json() if r.status_code == 200 else {}
names = [i["name"] for i in body.get("items", [])]
check("观看历史返回记录", r.status_code == 200 and len(names) == 2, str(names))
check("观看历史按条目去重（保留最近一次）",
      body.get("unique_total") == 2 and any("盗梦空间" in n for n in names), str(body.get("unique_total")))
top = next((i for i in body.get("items", []) if i["name"].startswith("盗梦空间")), {})
check("历史取最近会话的设备/进度",
      top.get("device") == "Apple TV" and top.get("position_ticks") == 4_440_000_000, str(top.get("device")))
check("历史合并用户媒体数据", top.get("play_count") == 2 and top.get("played") is True, str(top.get("play_count")))

r = client.get("/api/user/emby/history", params={"item_type": "episode"}, headers=headers)
names = [i["name"] for i in r.json().get("items", [])] if r.status_code == 200 else []
check("历史按类型筛选", r.status_code == 200 and len(names) == 1 and names[0].startswith("绝命毒师"), str(names))


# ---------- 我的播放会话 ----------
r = client.get("/api/user/emby/sessions", headers=headers)
sessions = r.json().get("sessions", []) if r.status_code == 200 else []
check("只返回自己的活跃会话",
      r.status_code == 200 and len(sessions) == 1 and sessions[0]["session_key"] == f"live{suf}",
      str([s["session_key"] for s in sessions]))
check("会话含设备与进度", sessions and sessions[0]["device"] == "Chrome" and sessions[0]["progress"] > 0,
      str(sessions[0].get("progress") if sessions else None))

r = client.delete(f"/api/user/emby/sessions/other{suf}", headers=headers)
check("结束他人会话 → 404", r.status_code == 404, str(r.status_code))

r = client.delete(f"/api/user/emby/sessions/live{suf}", headers=headers)
check("结束自己的会话", r.status_code == 200, str(r.status_code))

r = client.get("/api/user/emby/sessions", headers=headers)
check("会话结束后不再列出", r.status_code == 200 and r.json()["sessions"] == [], str(r.json().get("sessions")))


# ---------- 死接口下线 ----------
for path in ("/api/user/emby-servers", "/api/user/playback-sessions"):
    r = client.get(path, headers=headers)
    check(f"死接口已下线 {path} → 404", r.status_code == 404, str(r.status_code))


print()
if failures:
    print(f"❌ {len(failures)} 项失败：" + "、".join(failures))
    sys.exit(1)
print("✅ 用户端 v2.5.0 冒烟测试全部通过")
