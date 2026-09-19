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
    collection_type = Column(String(30), default="movies")  # movies / tvshows / mixed
    paths = Column(Text, default="")  # 逗号分隔的扫描根目录
    is_enabled = Column(Boolean, default=True)
    is_scanning = Column(Boolean, default=False)
    last_scan_at = Column(DateTime)
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
    tmdb_id = Column(String(20), index=True)

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
    is_hidden = Column(Boolean, default=False)
    date_added = Column(DateTime, default=datetime.now)
    premiere_date = Column(DateTime)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)


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
    "MediaItem",
    "MediaStream",
    "UserMediaData",
    "PlaybackSession",
    "EmbyApiToken",
]
