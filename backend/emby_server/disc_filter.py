"""蓝光/DVD 原盘目录过滤。

未解原盘长这样::

    精武英雄 (1994)/
    ├── BDMV/            ← 里面 STREAM/*.m2ts 是码流片段，不是影片
    │   ├── STREAM/00000.m2ts
    │   └── PLAYLIST/00800.mpls
    └── CERTIFICATE/

一条 ``00000.m2ts`` 被当成一部叫「00000」的电影入库：名字没法刮削、也没有封面，
还把 ffprobe 队列刷爆（生产上一次扫描产出 3966 条这种碎片，占 movie 总数的 69%）。
所以要在目录层面认结构、整棵子树跳过。
"""

# 目录名本身就是原盘结构的一层：进去只会看到码流、播放列表与证书
DISC_STRUCTURE_DIRS = frozenset({
    "BDMV",          # 蓝光主结构
    "VIDEO_TS",      # DVD
    "CERTIFICATE",   # 证书（蓝光）
    "AUXDATA",       # 附加数据（蓝光）
    "SSIF",          # 立体声索引（少数原盘会单独拆一层）
})


def is_disc_subtree_dir(name: str) -> bool:
    """这个目录要不要整棵跳过（忽略大小写）"""
    cleaned = (name or "").strip().upper()
    return cleaned in DISC_STRUCTURE_DIRS


def is_disc_subtree_rel(rel: str) -> bool:
    """按路径判断：路径里任意一段目录是原盘结构就跳过

    用于本机 ``os.walk``（拿得到完整路径）与远程列表（只有 rel）两种口径。
    最后一段是文件名，不参与判断。
    """
    if not rel:
        return False
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p]
    return any(is_disc_subtree_dir(p) for p in parts[:-1])
