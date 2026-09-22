"""挂载目录列举缓存冒烟测试（v2.17.0）

「列目录」是远程挂载唯一的高频网络动作。扫描方向本来就有「本次扫描内只列一次」的缓存，
但**播放**方向完全裸奔：``resolve_play_target`` 每次请求都新建提供者，实例上的 cid/pickcode
缓存对播放等于不存在——一次播放要重新逐级列目录（115 上 ``/电影/2024/x.mkv`` 就是 3 次网盘往返）。

本测试覆盖下沉到提供者层的共用缓存（``mounts.cached_listing``）：

- **共用**：扫描里的提供者与播放新建的提供者共享同一份缓存（底层只请求一次）
- **TTL**：有效期内不请求，过期后重新请求
- **拷贝**：返回的是拷贝，调用方排序 / 裁剪不会污染缓存
- **失败不缓存**：网盘抖动不会被固化 TTL 秒
- **配置指纹**：同一挂载改了配置（换目录 / 换地址）不命中旧缓存
- **单飞**：并发请求同一目录只请求一次，大家都拿到完整列表
- **扫描优先看当下**：``scanner.clear_dir_cache`` 会清掉这份共用缓存
- **有上限**：缓存不会随库变大无限增长
- **开关**：``MOUNT_LIST_CACHE_SECONDS=0`` 回到旧行为（每次都真列）
- **播放侧真实路径**：``exists`` / ``size`` 复用同一份列表
- **115**：raw 列表缓存让目录列举与 cid 解析共用一份（不再列两次）

全程不发真实网络请求：底层由计数提供者替代。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("DATABASE_URL", "sqlite:///./royalbot_unified.db")
os.environ.setdefault("SECRET_KEY", "smoke-test-only-secret-key-not-for-production")

from backend.emby_server import mounts as mnt
from backend.emby_server import scanner as sc

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


class FakeMount:
    """最小挂载对象：缓存键只关心 id / 类型 / 配置"""

    def __init__(self, mid: int = 1, mtype: str = "fake", config: str = '{"root": "/a"}'):
        self.id = mid
        self.mount_type = mtype
        self.config = config


class CountingProvider(mnt.MountProvider):
    """底层被替换成计数器的远程提供者（缓存包在 list_dir 外面）"""

    def __init__(self, mount, counter: dict, entries=None, fail: bool = False, delay: float = 0.0):
        super().__init__(mount)
        self._counter = counter
        self._entries = entries if entries is not None else [
            mnt.MountEntry(name="电影", rel="/电影", is_dir=True),
            mnt.MountEntry(name="a.mkv", rel="/a.mkv", is_dir=False, size=1024),
        ]
        self._fail = fail
        self._delay = delay

    @mnt.cached_listing
    def list_dir(self, rel: str = "/") -> list:
        self._counter["calls"] = self._counter.get("calls", 0) + 1
        self._counter.setdefault("rels", []).append(rel)
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            raise mnt.MountError("网盘抖动（测试用）")
        return [mnt.MountEntry(name=e.name, rel=e.rel, is_dir=e.is_dir, size=e.size,
                               entry_id=e.entry_id) for e in self._entries]


def reset(ttl: float = 5.0, cap: int = 2000) -> None:
    """每个小节开始前重置：清缓存、清计数、定 TTL / 上限"""
    mnt.invalidate_list_cache()
    for key in ("hits", "misses", "expired", "evictions", "waits"):
        mnt._LIST_CACHE_STATS[key] = 0
    mnt.MOUNT_LIST_CACHE_SECONDS = ttl
    mnt.MOUNT_LIST_CACHE_MAX = cap


def fresh_counter() -> dict:
    return {"calls": 0, "rels": []}


# ==================== 1. 扫描与播放共用同一份 ====================
# 这是本项改动的核心：播放方向每次请求新建提供者，实例级缓存帮不上忙，
# 只有把缓存放到提供者层之外（模块级）才能让两个方向共用。
reset()
mount = FakeMount()
counter = fresh_counter()
scan_provider = CountingProvider(mount, counter)
play_provider = CountingProvider(mount, counter)          # 模拟播放：另一个实例

scan_entries = scan_provider.list_dir("/电影")
play_entries = play_provider.list_dir("/电影")
check("扫描与播放共用一份目录列举（底层只请求一次）", counter["calls"] == 1,
      f"底层请求 {counter['calls']} 次")
check("两个方向拿到的内容逐项一致",
      [(e.name, e.rel, e.is_dir, e.size) for e in scan_entries] ==
      [(e.name, e.rel, e.is_dir, e.size) for e in play_entries])

# 第三次（不同挂载 / 不同目录）仍要各自请求：缓存不能串味
other = CountingProvider(FakeMount(mid=2), counter)
other.list_dir("/电影")
other.list_dir("/别的目录")
check("不同挂载 / 不同目录各自请求（不会串味）", counter["calls"] == 3,
      f"底层请求 {counter['calls']} 次，rels={counter['rels']}")

# ==================== 2. TTL：有效期内不请求，过期后重新请求 ====================
reset(ttl=0.25)
counter = fresh_counter()
provider = CountingProvider(mount, counter)
provider.list_dir("/")
provider.list_dir("/")
check("TTL 内命中缓存（不请求）", counter["calls"] == 1, f"底层请求 {counter['calls']} 次")
time.sleep(0.3)
provider.list_dir("/")
check("TTL 过期后重新请求（不会永久吃旧目录）", counter["calls"] == 2,
      f"底层请求 {counter['calls']} 次")
stats = mnt.list_cache_stats()
check("统计口径：命中 / 过期都被记下", stats["hits"] >= 1 and stats["expired"] >= 1,
      f"hits={stats['hits']} expired={stats['expired']} misses={stats['misses']}")

# ==================== 3. 返回的是拷贝 ====================
reset()
counter = fresh_counter()
provider = CountingProvider(mount, counter)
first = provider.list_dir("/")
first.append("被调用方塞进来的东西")
first.sort(key=lambda x: str(x))
second = provider.list_dir("/")
check("调用方改动返回值不会污染缓存", len(second) == 2 and "被调用方塞进来的东西" not in second,
      f"第二次拿到 {len(second)} 项")

# ==================== 4. 失败不缓存 ====================
reset()
counter = fresh_counter()
broken = CountingProvider(mount, counter, fail=True)
first_raised = False
try:
    broken.list_dir("/")
except mnt.MountError:
    first_raised = True
check("底层失败时向上抛（调用方按不可用处理）", first_raised)
try:
    broken.list_dir("/")
except mnt.MountError:
    pass
check("失败**不**进缓存：下一次仍然真去请求（网盘抖动不被固化）", counter["calls"] == 2,
      f"底层请求 {counter['calls']} 次")

# ==================== 5. 配置指纹：改配置不吃旧缓存 ====================
reset()
counter = fresh_counter()
m1 = FakeMount(mid=7, config='{"root": "/电影"}')
m2 = FakeMount(mid=7, config='{"root": "/电视剧"}')        # 同一个挂载 id，换了根目录
CountingProvider(m1, counter).list_dir("/")
CountingProvider(m2, counter).list_dir("/")
check("同一挂载改了配置后不命中旧缓存", counter["calls"] == 2, f"底层请求 {counter['calls']} 次")

# ==================== 6. 单飞：并发请求同一目录只请求一次 ====================
reset()
counter = fresh_counter()
slow = CountingProvider(mount, counter, delay=0.15)
results: list = []
threads = [threading.Thread(target=lambda: results.append(slow.list_dir("/电影"))) for _ in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("并发请求同一目录只请求一次（单飞）", counter["calls"] == 1, f"底层请求 {counter['calls']} 次")
check("等待中的线程都拿到完整列表",
      len(results) == 8 and all(len(r) == 2 for r in results),
      f"拿到 {len(results)} 份，长度 {sorted({len(r) for r in results})}")
check("单飞等待有计数（能看出省了多少次）", mnt.list_cache_stats()["waits"] >= 1,
      str(mnt.list_cache_stats()))

# ==================== 7. 扫描必须看到当下的目录 ====================
# 扫描前会 clear_dir_cache()：如果只有本机缓存被清、挂载缓存留着，
# 刚上传的文件会被「播放刚踩过」的缓存挡住，要等下一轮扫描才入库。
reset()
counter = fresh_counter()
provider = CountingProvider(mount, counter)
provider.list_dir("/")
check("（前置）缓存已建立", counter["calls"] == 1)
sc.clear_dir_cache()
provider.list_dir("/")
check("clear_dir_cache 同时清掉挂载缓存（扫描看当下）", counter["calls"] == 2,
      f"底层请求 {counter['calls']} 次")

# ==================== 8. 有上限：不随库变大无限增长 ====================
reset(cap=3)
counter = fresh_counter()
many = CountingProvider(mount, counter)
for i in range(6):
    many.list_dir(f"/第{i}层")
stats = mnt.list_cache_stats()
check("缓存条目有上限（满了清空，内存可控）", stats["entries"] <= 3, f"entries={stats['entries']}")
check("上限触发被记进统计", stats["evictions"] >= 1, f"evictions={stats['evictions']}")
check("满了之后功能仍然正确（重新请求、内容不缺）", counter["calls"] == 6 and
      len(many.list_dir("/第5层")) == 2, f"底层请求 {counter['calls']} 次")

# ==================== 9. 开关：TTL=0 回到旧行为 ====================
reset(ttl=0)
counter = fresh_counter()
off = CountingProvider(mount, counter)
off.list_dir("/")
off.list_dir("/")
check("MOUNT_LIST_CACHE_SECONDS=0 时每次都真列（可回退）", counter["calls"] == 2,
      f"底层请求 {counter['calls']} 次")
check("关掉开关不写缓存", mnt.list_cache_stats()["entries"] == 0)

# ==================== 10. 播放侧真实路径：exists / size 复用同一份列表 ====================
# 远程挂载上，Emby 客户端播放一个条目会问「在不在」「多大」——这两个都在基类里，
# 都走 self.list_dir，因此天然复用同一份缓存。
reset()
counter = fresh_counter()
provider = CountingProvider(mount, counter)
check("exists 用缓存列表判定存在", provider.exists("/a.mkv") is True)
check("size 从同一份列表里取大小", provider.size("/a.mkv") == 1024, str(provider.size("/a.mkv")))
check("不存在也走同一份（不额外请求）", provider.exists("/nope.mkv") is False)
check("播放侧三个问句只列了一次目录", counter["calls"] == 1, f"底层请求 {counter['calls']} 次")

# 需要当下目录的调用方（后台选择器 / 刷新）可以明确绕过缓存
uncached = mnt.list_dir_uncached(provider, "/")
check("list_dir_uncached 绕过缓存（后台目录选择器看当下）", counter["calls"] == 2,
      f"底层请求 {counter['calls']} 次")
check("绕过缓存不会破坏已有缓存", len(uncached) == 2 and provider.list_dir("/") and
      counter["calls"] == 2, f"底层请求 {counter['calls']} 次")
_before = counter["calls"]
provider.list_dir("/", fresh=True)
check("list_dir(fresh=True) 同样绕过", counter["calls"] == _before + 1,
      f"底层请求 {counter['calls']} 次")

# ==================== 11. 115：raw 列表与目录列举共用一份 ====================
# 115 是最常见的直挂类型：一次播放要「列出父目录 → 找子目录 cid → 再列一层拿 pickcode」，
# 旧实现每次都真问网盘。现在 raw 列表也走同一套缓存。
reset()
mount115 = FakeMount(mid=9, mtype="115", config='{"root_cid": "0", "cookie": "UID=x"}')
fake_client_calls: list = []


class Fake115Client:
    def list_dir(self, cid: str = "0"):
        fake_client_calls.append(cid or "0")
        return [
            {"name": "电影", "is_dir": True, "cid": "c1", "size": 0},
            {"name": "a.mkv", "is_dir": False, "cid": "f1", "size": 2048, "pickcode": "p1"},
        ]


provider115 = mnt.Pan115Mount(mount115)
provider115._client = lambda: Fake115Client()          # 只替换客户端，缓存代码路径真实执行
entries_115 = provider115.list_dir("/")
check("115 目录列举可用（带 cid）",
      [e.name for e in entries_115] == ["电影", "a.mkv"] and
      entries_115[0].entry_id == "c1",
      str([(e.name, e.entry_id) for e in entries_115]))
after_first = len(fake_client_calls)
raw_again = provider115._raw_list("0")
check("115 的目录列举与 cid 解析共用同一份 raw 列表（不再列两次）",
      len(fake_client_calls) == after_first and len(raw_again) == 2,
      f"网盘请求 {fake_client_calls}")
check("（前置）确实发生过网盘请求", len(fake_client_calls) >= 1)
provider115.list_dir("/")                              # 再来一次：仍然命中缓存
check("115 重复列举不再问网盘", len(fake_client_calls) == after_first,
      f"网盘请求 {fake_client_calls}")

# 最实在的一条：模拟「两次播放」——每次都像生产那样新建提供者（见 resolve_play_target），
# 数一数到底问了网盘几次。定位 ``/电影/a.mkv`` 需要：列根目录找“电影”的 cid，再列该目录找 pickcode。
reset()
fake_client_calls.clear()
for _ in range(2):
    p = mnt.Pan115Mount(mount115)
    p._client = lambda: Fake115Client()
    located = p._locate("/电影/a.mkv")
    assert located["pickcode"] == "p1", located
check("两次播放（各自新建提供者）问网盘 2 次而不是 4 次", len(fake_client_calls) == 2,
      f"网盘请求 {fake_client_calls}")
check("缓存让第二次播放不再重复解析 cid", len(set(fake_client_calls)) == 2,
      f"不同的请求参数 {fake_client_calls}")

# ==================== 12. 收尾：把开关还原，避免影响后续测试 ====================
mnt.MOUNT_LIST_CACHE_SECONDS = 5.0
mnt.MOUNT_LIST_CACHE_MAX = 2000
mnt.invalidate_list_cache()
check("收尾：缓存已清空、开关还原", mnt.list_cache_stats()["entries"] == 0)

print("\n" + "=" * 60)
if failures:
    print(f"❌ 失败 {len(failures)} 项: {failures}")
    sys.exit(1)
print("✅ 挂载目录列举缓存冒烟测试全部通过（0 失败）")
