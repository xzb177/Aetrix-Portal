"""自建 Emby 媒体服务器数据模型"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from backend.database import Base


class Library(Base):
    """媒体库"""

    __tablename__ = "emby_libraries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guid = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    # 属于哪个服（server_realms.id）。服之间内容隔离：某个服的 EA 只提供本服的库。
    # 老部署由迁移统一回填到默认服，行为不变。
    realm_id = Column(Integer)
    collection_type = Column(String(30), default="movies")  # movies / tvshows / mixed
    paths = Column(Text, default="")  # 逗号分隔的扫描根目录；虚拟媒体库为空
    is_enabled = Column(Boolean, default=True)
    is_scanning = Column(Boolean, default=False)
    # 刮削策略：missing_only / 3m / 6m / 1y / all（见 scanner.SCAN_POLICIES）
    scrape_policy = Column(String(20), default="missing_only")
    # 管理员上传的媒体库封面；保存为图片目录下的相对路径，扫描/刮削不会覆盖它。
    cover_path = Column(String(500))
    # 虚拟媒体库：按发行平台（Netflix / Disney+ …）自动生成，没有自己的文件与路径
    is_virtual = Column(Boolean, default=False)
    platform = Column(String(30))  # 虚拟库对应的平台 id（见 scanner.PLATFORM_LABELS）
    # 绑定 115 账号配置档（pan115_accounts.id）：不同媒体库可用不同 115 账号转存/下载。
    # 未绑定时回退到默认账号，再回退到服务器级 PAN115_COOKIE（兼容旧部署）。
    account_115_id = Column(Integer)
    # 负责这台库的播放节点（remote_servers.id，kind=ea 的那条）。
    # **NULL = 未分配**：任何节点都能看到它、由面板（EM）扫描——单节点部署与
    # 「刚加完节点还没来得及分配」的过渡期都靠这个语义保持与以前完全一致。
    # 已分配时：只有那台节点会向客户端展示它、只有它会扫描它（见 emby_server/nodes.py）。
    node_id = Column(Integer)
    # 绑定的存储挂载（storage_mounts.id，逗号分隔）：媒体库的内容来源之一。
    # `paths` 是**本机目录**（rclone / CloudDrive2 / SMB 挂载盘最终也是本机目录），
    # `mount_ids` 则是显式声明的挂载来源（本地目录 / STRM / 115 直挂 / WebDAV / AList），
    # 两者可同时存在，扫描时一起遍历；远程挂载的条目 file_path 形如 mount://<id>/<相对路径>。
    mount_ids = Column(Text, default="")
    last_scan_at = Column(DateTime)
    # 最近一次扫描的结果（v2.22.0）：只靠 is_scanning + last_scan_at 看不出「扫得怎么样」——
    # 新增/更新/删除多少、哪些来源读不到、有没有异常都只留在日志里，扫描结束就查不到了。
    # 这里把结果落库，管理端列表直接带回（见 scanner.begin_scan / finish_scan / scan_result_payload）。
    # scan_status: running / success / partial / failed（partial = 有来源不可用、已跳过清理）
    scan_status = Column(String(20))
    scan_stats = Column(Text)          # JSON：added/updated/removed/probed/scraped/unchanged…
    scan_error = Column(String(500))   # 异常摘要（仅 failed 时写入），来源失败原因进 stats.failed_roots
    # 扫描进行中的进度快照（v2.27.0）：只有 running 时有值，结束时清空。
    # 只靠 scan_status=running 看不出「扫到哪了」——四库同点扫描时 item_count 长时间是 0，
    # 面板只能显示「扫描中」；这里带上阶段 / 已发现 / 已处理 / 当前目录 / 本轮远程请求数，
    # 由 scan_queue 的刷盘线程每几秒写一次。
    scan_progress = Column(Text)       # JSON：phase/enumerated/processed/current/remote_lists…
    item_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class MediaItem(Base):
    """媒体条目（电影 / 剧集 / 季 / 集）"""

    __tablename__ = "emby_items"
    __table_args__ = (
        Index("idx_item_lib_type", "library_id", "item_type"),
        Index("idx_item_parent", "parent_id"),
        Index("idx_item_series", "series_id"),
        # 两阶段扫描 Phase 2：后台探测按（状态，优先级）取待探测条目
        Index("idx_item_probe", "probe_status", "probe_priority", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 32 位稳定 ID（Emby 风格），由路径 md5 生成
    guid = Column(String(32), unique=True, nullable=False, index=True)
    library_id = Column(Integer, ForeignKey("emby_libraries.id"), nullable=False)
    item_type = Column(String(20), nullable=False)  # movie / series / season / episode
    name = Column(String(300), nullable=False)
    original_title = Column(String(300))
    sort_name = Column(String(300))
    overview = Column(Text)
    tagline = Column(String(300))

    # 层级
    parent_id = Column(Integer, ForeignKey("emby_items.id"))
    series_id = Column(Integer, ForeignKey("emby_items.id"))
    season_number = Column(Integer)
    episode_number = Column(Integer)
    production_year = Column(Integer)

    # 评分与元数据
    community_rating = Column(Float)
    official_rating = Column(String(20))  # 分级
    genres = Column(Text, default="")  # 逗号分隔
    tags = Column(Text, default="")
    studios = Column(Text, default="")
    # 发行平台（逗号分隔的平台 id）：扫描时从文件名/目录标签识别，供虚拟媒体库聚合
    platforms = Column(Text, default="")
    tmdb_id = Column(String(20), index=True)
    imdb_id = Column(String(20))
    # 多别名（逗号分隔）：TMDB 的 also known as / 原名等，供中英文与繁简搜索命中
    aliases = Column(Text, default="")

    # 媒体文件
    file_path = Column(String(1024), index=True)
    container = Column(String(20))
    size = Column(BigInteger, default=0)
    duration_ticks = Column(BigInteger, default=0)  # 100ns ticks
    bitrate = Column(Integer, default=0)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    video_codec = Column(String(30))
    audio_codec = Column(String(30))
    audio_languages = Column(String(200), default="")
    subtitle_languages = Column(String(200), default="")

    # 图片
    poster_path = Column(String(1024))  # 本地海报文件
    backdrop_path = Column(String(1024))
    primary_image_url = Column(String(1024))  # TMDB 刮削到的远程图
    backdrop_image_url = Column(String(1024))

    # 状态
    last_probed_at = Column(DateTime)  # 上次 ffprobe 时间，供刮削策略判断是否重探
    # 两阶段扫描（v2.39.0）：Phase 1 只入库结构不做 ffprobe，需要探测的条目由
    # 后台 worker 按优先级探测。pending=待探测 probing=探测中 done=已探测 failed=放弃。
    probe_status = Column(String(20), default="pending")
    probe_priority = Column(Integer, default=0)  # 越大越先探；新文件 100，按需插队 1000
    probe_attempts = Column(Integer, default=0)  # 已尝试次数，超限转 failed
    probe_next_retry_at = Column(DateTime)  # 下次可重试时间（退避）
    last_scraped_at = Column(DateTime)  # 上次刮削时间，供 3m/6m/1y 策略判断是否到期
    # 数据库里有图片记录但本地文件丢失时置位，等待后台重新刮削修复
    repair_requested_at = Column(DateTime)
    is_hidden = Column(Boolean, default=False)
    date_added = Column(DateTime, default=datetime.now)
    premiere_date = Column(DateTime)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # 分层扫描（v2.40.0）：L1 只做文件发现与秒跳，L2/L3 后台补全元数据。
    # file_fingerprint: 文件指纹（本地=path|size|mtime_ns，远程=path|size 的 md5）。
    #   指纹命中且 enrich_status='done' 时整文件秒跳，不做任何 IO。
    # enrich_status: 补全状态 pending=待补全（L2/L3 排队中） done=已补全。
    #   「文件变没变」与「元数据全不全」解耦——旧 _can_skip_file 把条件绞在一起，
    #   配了 TMDB 的剧集库每轮都全量重做，增量形同虚设，这是根因。
    file_fingerprint = Column(String(64), index=True)
    enrich_status = Column(String(20), default='pending', index=True)
    # v2.40.0 补全 worker 重试：attempts=已尝试次数，超限转 failed；
    # next_retry_at=下次可重试时间（指数退避）。老库补列后默认 0/NULL。
    enrich_attempts = Column(Integer, default=0)
    enrich_next_retry_at = Column(DateTime)


from sqlalchemy.orm import relationship  # noqa: E402

MediaItem.library = relationship("Library", foreign_keys=[MediaItem.library_id])
MediaItem.parent = relationship("MediaItem", remote_side="MediaItem.id", foreign_keys=[MediaItem.parent_id])
MediaItem.series = relationship(
    "MediaItem", remote_side="MediaItem.id", foreign_keys=[MediaItem.series_id]
)


class MediaStream(Base):
    """媒体流轨道（视频/音频/字幕）"""

    __tablename__ = "emby_media_streams"
    __table_args__ = (Index("idx_stream_item", "item_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("emby_items.id"), nullable=False)
    stream_index = Column(Integer, default=0)
    stream_type = Column(String(10))  # Video / Audio / Subtitle
    codec = Column(String(30))
    language = Column(String(20))
    display_title = Column(String(200))
    title = Column(String(200))
    is_default = Column(Boolean, default=False)
    is_forced = Column(Boolean, default=False)
    is_external = Column(Boolean, default=False)
    external_path = Column(String(1024))
    channels = Column(Integer)
    bit_rate = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)


MediaItem.streams = relationship(
    "MediaStream", foreign_keys=[MediaStream.item_id], cascade="all, delete-orphan"
)


class UserMediaData(Base):
    """用户媒体数据（播放进度 / 收藏 / 已看）"""

    __tablename__ = "emby_user_media_data"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_umdata_user_item"),
        Index("idx_umdata_user", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("web_users.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("emby_items.id"), nullable=False)
    playback_position_ticks = Column(BigInteger, default=0)
    play_count = Column(Integer, default=0)
    played = Column(Boolean, default=False)
    is_favorite = Column(Boolean, default=False)
    last_played_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PlaybackSession(Base):
    """播放会话"""

    __tablename__ = "emby_playback_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(String(64), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("web_users.id"))
    item_id = Column(Integer, ForeignKey("emby_items.id"))
    device_name = Column(String(100))
    client_name = Column(String(100))
    client_version = Column(String(50))
    remote_addr = Column(String(64))
    play_method = Column(String(30))  # DirectStream / Transcode
    start_time = Column(DateTime, default=datetime.now)
    last_update_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    position_ticks = Column(BigInteger, default=0)
    is_paused = Column(Boolean, default=False)
    ended_at = Column(DateTime)


class ItemFacet(Base):
    """条目 ↔ 分类值（流派 / 工作室 / 标签 / 发行平台）关联表（v2.15.0）

    这些值原先只存在 :class:`MediaItem` 的逗号分隔文本列里，筛选时只能写
    ``genres ILIKE '%动作%'`` —— 前置通配符用不上任何索引，每次筛选都是整库扫描。
    现在由扫描器与元数据刮削在写条目的同时维护本表，筛选改成先在
    ``(kind, value, item_id)`` 上定位 item_id，再按 id 过滤条目（见 `facets.py`）。
    """

    __tablename__ = "emby_item_facets"

    __table_args__ = (
        # 筛选走这条：kind + value 定位候选条目
        Index("idx_item_facet_kind_value", "kind", "value", "item_id"),
        # 重建单个条目 / 清理孤儿行走这条
        Index("idx_item_facet_item", "item_id", "kind"),
        UniqueConstraint("item_id", "kind", "value", name="uq_item_facet"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("emby_items.id"), nullable=False)
    # genre / studio / tag / platform
    kind = Column(String(16), nullable=False)
    value = Column(String(200), nullable=False)


class ScanDirState(Base):
    """增量扫描的目录指纹（v2.17.0）

    「追新」场景里绝大多数目录一个文件都没动过，但重扫会把里面每个文件重走一遍：
    找本地图片、找外挂字幕、重建外挂字幕轨、提交事务（实测 2000 个文件的重扫 ≈ 冷扫
    的 95%，约 4 条 SQL + 1 次 commit / 文件）。

    这里按目录存一份指纹：本机是 ``目录 mtime_ns : 目录项数``，挂载是 ``目录项数 : 总字节数``。
    指纹没变的目录直接跳过逐文件的活，只把 guid 记进 ``seen_guids`` 并确认库里那一行
    存在且不需要重探/重刮——库中缺行、大小变了、要补图补详情都照旧完整处理，
    所以“跳过”永远不会漏掉还没入库的文件。详见 `scanner` 的增量扫描小节。
    """

    __tablename__ = "emby_scan_dirs"

    __table_args__ = (
        UniqueConstraint("library_id", "dir_key", name="uq_scan_dir_state"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    library_id = Column(Integer, nullable=False, index=True)
    # 本机绝对路径，或 mount://<挂载 id>/<相对路径>
    dir_key = Column(String(1000), nullable=False)
    fingerprint = Column(String(128), nullable=False)
    updated_at = Column(DateTime, default=datetime.now)


class ScanRun(Base):
    """一次媒体库扫描的记录（v2.23.0）

    只留「最近一次」不够解释「为什么这个库的内容一直没更新」：一个库每轮都失败、
    或只是最近一轮失败，处理方式完全不同。这里按库留最近若干轮的流水
    （状态 / 触发方 / 耗时 / 同一份统计 / 失败原因），管理端可查。

    保留条数由 ``scanner.SCAN_RUN_KEEP`` 控制（``EMBY_SCAN_HISTORY=0`` 关闭记录），
    每轮扫描结束后就地回收旧行；媒体库删掉后剩下的行由维护周期回收。
    """

    __tablename__ = "emby_scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 不加外键：媒体库删除后这些行要能被维护周期清掉（而不是阻断删除）
    library_id = Column(Integer, nullable=False, index=True)
    # running / success / partial / failed（与 Library.scan_status 同一套取值）
    status = Column(String(20), nullable=False)
    # 谁触发的：manual（面板按钮）/ client（Emby 客户端刷新）/ node（归属节点）/ repair（修复队列）。
    # 列名不叫 trigger：它在 MySQL / PG 里是保留字，裸写要处处加引号（属性名照旧叫 trigger）
    trigger = Column("trigger_kind", String(20))
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)
    stats = Column(Text)          # JSON，与 Library.scan_stats 同一份编码
    error = Column(String(500))   # partial / failed 的原因摘要


class StorageMount(Base):
    """存储挂载：媒体库的内容来源

    一个挂载 = 一种「把内容接到媒体库上」的方式。挂载本身不拥有条目，
    媒体库通过 `Library.mount_ids` 引用它，因此同一个挂载可以被多个库共用。

    支持的类型（见 ``mounts.MOUNT_TYPES``）：

    - ``local``：本机目录。rclone / CloudDrive2 / SMB / NFS 已经挂到本机后，对面板就是一条路径；
    - ``strm``：STRM 目录。扫描 ``.strm`` 文件内容作为播放直链（本地只放小文件，媒体在远端）；
    - ``115``：115 网盘直挂。Cookie 型 API 直接读网盘目录，**不需要本地挂载**；
    - ``webdav``：通用 WebDAV（群晖 / Nextcloud / 自建）；
    - ``alist``：AList / OpenList（一个挂载聚合多种网盘）。

    远程挂载的媒体由 EA 按 Range 代理转发，播放地址不落到客户端，Cookie / 令牌不下发。
    """

    __tablename__ = "storage_mounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    # 属于哪个服（server_realms.id）：挂载是主机相对的资源，跟着服走
    realm_id = Column(Integer)
    # local / strm / 115 / webdav / alist
    mount_type = Column(String(20), nullable=False, default="local")
    # 本机目录（local / strm）：远程挂载留空
    path = Column(String(1024), default="")
    # 类型相关配置（JSON 文本）：115 的 cid/账号、WebDAV 的 url/账号、AList 的 url/token 等
    config = Column(Text, default="{}")
    is_enabled = Column(Boolean, default=True)
    remark = Column(String(300), default="")
    # 最近一次连接测试结果（仅展示，不参与鉴权判断）
    last_checked_at = Column(DateTime)
    last_check_ok = Column(Boolean)
    last_check_message = Column(String(300))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class RcloneRemote(Base):
    """rclone remote 配置（数据驱动，不写 rclone.conf 文件）

    一个 remote = 一种访问云盘的方式。支持：
    - drive (OAuth 个人盘)：client_id/secret/token
    - drive (服务账号)：service_account_file + team_drive
    - 可扩展其它 type

    系统从本表生成 rclone.conf，探测 worker 按 ``probe_remote`` 选择用哪个。
    """

    __tablename__ = "rclone_remotes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)  # remote 名，如 paul_emby / MP
    remote_type = Column(String(30), nullable=False, default="drive")  # drive / s3 / ...
    # OAuth 方式
    client_id = Column(String(300), default="")
    client_secret = Column(String(300), default="")
    token_json = Column(Text, default="")  # OAuth token JSON
    scope = Column(String(100), default="drive")
    # 服务账号方式
    sa_file_id = Column(Integer, default=None)  # 关联 service_account_files.id
    team_drive = Column(String(100), default="")  # 团队盘 ID，空=个人盘
    # 通用
    chunk_size = Column(String(20), default="64M")
    is_enabled = Column(Boolean, default=True)
    is_probe_remote = Column(Boolean, default=False)  # 是否为探测用 remote（全局唯一）
    remark = Column(String(300), default="")
    last_checked_at = Column(DateTime)
    last_check_ok = Column(Boolean)
    last_check_message = Column(String(300))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ServiceAccountFile(Base):
    """服务账号 JSON 文件（元数据，文件本体存安全目录）"""

    __tablename__ = "service_account_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(200), nullable=False)  # 原始文件名
    stored_path = Column(String(1024), nullable=False)  # 服务器上的安全路径
    client_email = Column(String(300), default="")  # 从 JSON 解析，方便识别
    project_id = Column(String(200), default="")
    is_enabled = Column(Boolean, default=True)
    remark = Column(String(300), default="")
    created_at = Column(DateTime, default=datetime.now)


class Pan115Account(Base):
    """115 账号配置档（Cookie 型，不依赖 115 OpenAPI）

    一个站点可以配置多个命名账号（如「主号」「影库专号」），其中一个作为默认账号；
    媒体库可以单独绑定账号（`Library.account_115_id`），未绑定时回退到默认账号，
    再回退到服务器级 `PAN115_COOKIE`（兼容历史上只在 .env 里放一个 Cookie 的部署）。
    """

    __tablename__ = "pan115_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    cookie = Column(Text, nullable=False)
    is_default = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)
    remark = Column(String(300), default="")
    # 最近一次校验结果（仅展示，不参与鉴权判断）
    last_verified_at = Column(DateTime)
    last_verify_ok = Column(Boolean)
    last_verify_message = Column(String(300))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class EmbyApiToken(Base):
    """Emby 客户端 Access Token"""

    __tablename__ = "emby_api_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("web_users.id"), nullable=False)
    device_id = Column(String(100))
    app_name = Column(String(100))
    app_version = Column(String(50))
    last_ip = Column(String(64))
    created_at = Column(DateTime, default=datetime.now)
    last_used_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    is_revoked = Column(Boolean, default=False)


__all__ = [
    "Library",
    "ScanRun",
    "MediaItem",
    "MediaStream",
    "UserMediaData",
    "PlaybackSession",
    "StorageMount",
    "Pan115Account",
    "EmbyApiToken",
]
