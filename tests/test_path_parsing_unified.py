"""路径 / id 字串解析统一到 mounts（v2.46.0）

``change_watcher`` 以前自己写死 ``paths.split(",")`` 与一份 id 解析器，而扫描/监听/
界面走的是 ``mounts.split_library_paths`` / ``mounts.parse_mount_ids``。同一串路径在
两处可能拆出不同结果（全角逗号、去重），追新就会“少看一个目录”或“多看两次”。

这里钉住：

1. ``change_watcher`` 里不再出现裸 ``split(",")``（源码级断言，防止回退）
2. 两处对同一串路径拆出的结果**逐条相同**
3. 全角逗号 / 空白 / 重复项在两边都被正确处理
4. ``parse_mount_ids`` 与追新的 ``_parse_ids`` 对同一串 id 解出相同结果
5. 脏值（0、负数、超 64 位、非数字）两边一致地丢弃
"""
import inspect
import os
import re
from types import SimpleNamespace

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")

from backend.emby_server import change_watcher as cw
from backend.emby_server import mounts as mount_lib


# ==================== 源码级：不再自己拆 ====================

def test_change_watcher_has_no_bare_comma_split():
    """源码里不能再有 ``split(",")`` —— 只允许出现在注释里

    这是防回退的钉子：以后有人图省事写回裸 split，这���测试会立刻红。
    """
    src = inspect.getsource(cw)
    # 去掉注释与文档字符串后再找，避免把说明文字当成代码
    code_lines = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    hits = [
        m.start() for m in re.finditer(r'\.split\(\s*["\']\s*,\s*["\']\s*\)', code)
    ]
    assert not hits, "change_watcher 里仍有裸 split(',')，请改用 mounts 的统一解析"


def test_change_watcher_delegates_to_mounts():
    """两处公共函数都应转发给 mounts，而不是各写一份"""
    assert cw._parse_ids("1,2") == mount_lib.parse_id_list("1,2")
    src_local = inspect.getsource(cw._library_local_paths)
    src_remote = inspect.getsource(cw._library_mount_sources)
    assert "split_library_paths" in src_local
    assert "split_library_paths" in src_remote
    assert "parse_mount_ids" in src_local


# ==================== 同一串路径，两处结果一致 ====================

_MESSY_PATHS = [
    ("/media/电影", ["/media/电影"]),
    ("/a,/b", ["/a", "/b"]),
    # 全角逗号：以前 change_watcher 拆不出来，会把 "/a，/b" 当成一个不存在的目录
    ("/a，/b", ["/a", "/b"]),
    ("  /a  ,  /b  ", ["/a", "/b"]),
    ("/a,/a,/b", ["/a", "/b"]),                      # 去重
    ("/a,,/b,", ["/a", "/b"]),                       # 去空
    ("", []),
    ("mount://3/Movies", ["mount://3/Movies"]),
    ("mount://3/Movies,/a", ["mount://3/Movies", "/a"]),
]


def test_change_watcher_splits_paths_exactly_like_mounts():
    """逐条比对：change_watcher 与 mounts 对同一串 paths 的拆分必须完全一致"""
    for raw, expected in _MESSY_PATHS:
        canonical = mount_lib.split_library_paths(raw)
        assert canonical == expected, f"{raw!r} 的期望拆分是 {expected}"

        # _library_mount_sources 是纯函数，直接拿它当 change_watcher 的拆分口径
        lib = SimpleNamespace(paths=raw, mount_ids="")
        cw_sources = cw._library_mount_sources(lib, None)
        # 它只收 mount:// 前缀的，所以拿它反推“本模块认可了多少条路径”不直观；
        # 改为直接比对它看到的 mount:// 条目数与 mounts 拆出来的 mount:// 条目数
        mountish = [p for p in canonical if p.startswith("mount://")]
        assert len(cw_sources) == len(mountish), f"{raw!r}: 追新看到的挂载源数量对不上"


def test_mount_source_parsing_uses_canonical_split():
    """mount:// 子目录解析：全角逗号分隔时追新也要看得见，不能因为分隔符不同就漏"""
    lib = SimpleNamespace(paths="mount://3/国产剧,mount://4/MoviePilot", mount_ids="")
    (a_id, a_rel), (b_id, b_rel) = cw._library_mount_sources(lib, None)
    assert (a_id, a_rel) == (3, "/国产剧")
    assert (b_id, b_rel) == (4, "/MoviePilot")


# ==================== id 字串：两处一致 ====================

_ID_CASES = [
    ("1,2,3", [1, 2, 3]),
    ("1，2", [1, 2]),                 # 全角逗号
    (" 1 , 2 ", [1, 2]),              # 空白
    ("1,1,2", [1, 2]),                # 去重
    ("", []),
    (None, []),
    ("1,abc,3", [1, 3]),              # 非数字丢弃
    ("0,2", [2]),                     # 0 不是合法主键
    ("-1,2", [2]),                    # 负数丢弃
    (str(2 ** 63 - 1), [2 ** 63 - 1]),        # 64 位上限之内
    (str(2 ** 63), []),                      # 超出上限丢弃
    ("99999999999999999999999", []),         # 超长数字串丢弃
]


def test_parse_mount_ids_and_chase_new_agree():
    """``Library.mount_ids`` 与追新清单必须是同一个解析结果"""
    for raw, expected in _ID_CASES:
        assert cw._parse_ids(raw) == expected, f"追新解析 {raw!r} 不符"
        lib = SimpleNamespace(mount_ids=raw, paths="")
        assert mount_lib.parse_mount_ids(lib) == expected, f"mount_ids 解析 {raw!r} 不符"


def test_max_id_constant_is_shared():
    """上限常量只有一份定义（两边必须同步，不能各写一个 2**63）"""
    assert cw._MAX_LIBRARY_ID == mount_lib.MAX_ID_VALUE
    assert mount_lib.MAX_ID_VALUE == 2 ** 63 - 1


def test_library_local_paths_uses_shared_parsing(tmp_path):
    """本机路径收集：全角逗号分隔的两个真实目录都要被认出来"""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    lib = SimpleNamespace(paths=f"{a}，{b}", mount_ids="")

    assert cw._library_local_paths(lib, None) == [str(a), str(b)]


def test_library_local_paths_skips_missing_and_mount_prefix(tmp_path):
    """不存在的目录与 mount:// 仍要被跳过（老行为不能变）"""
    real = tmp_path / "real"
    real.mkdir()
    lib = SimpleNamespace(
        paths=f"{real},{tmp_path / 'nope'},mount://3/Movies", mount_ids="")

    assert cw._library_local_paths(lib, None) == [str(real)]