"""自建 Emby 服务器：字幕投递

Emby 客户端取字幕走
``GET /Videos/{Id}/{MediaSourceId}/Subtitles/{Index}/Stream.{Format}``，
本模块负责把它落到本地：外挂字幕直接读取（含中文常见 GBK 编码嗅探），
内封文本字幕用 ffmpeg 抽取为 WebVTT 并按「条目 + 轨道」缓存。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from typing import Optional

from fastapi import HTTPException, Response

logger = logging.getLogger(__name__)

FFMPEG = os.getenv("EMBY_FFMPEG_PATH", "ffmpeg")
SUB_CACHE_DIR = os.getenv(
    "EMBY_SUBTITLE_DIR",
    os.path.join(os.getenv("EMBY_TRANSCODE_DIR", "/tmp/emby_transcode"), "subs"),
)

# 文本类字幕编码名（可转换为 VTT）；图片类（PGS/VobSub）无法转文本
TEXT_SUB_CODECS = {
    "subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text", "vtt", "smi", "sami", "ttml",
}
IMAGE_SUB_CODECS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub", "dvb_subtitle", "xsub"}

TEXT_EXTS = {".srt", ".vtt", ".ass", ".ssa", ".sub", ".smi", ".sami", ".ttml", ".txt"}
# 源文件扩展名 → 客户端可直接按该格式取原始文件
RAW_OK = {
    "srt": {".srt"},
    "vtt": {".vtt"},
    "ass": {".ass"},
    "ssa": {".ssa"},
    "sub": {".sub"},
    "smi": {".smi", ".sami"},
}
MIME = {
    "vtt": "text/vtt; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "ass": "text/x-ssa; charset=utf-8",
    "ssa": "text/x-ssa; charset=utf-8",
}
DEFAULT_MIME = "text/plain; charset=utf-8"

_SRT_TS = re.compile(r"(\d{2}:\d{2}:\d{2}),(\d{3})")
_VTT_TS = re.compile(r"(\d{2}:\d{2}:\d{2})\.(\d{3})")
_ASS_TAG = re.compile(r"\{[^}]*\}")
_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[.:](\d{1,3})")
_ASS_SKIP = (
    "format:", "title:", "scripttype:", "wrapstyle:", "scaledborderandshadow:",
    "collisions:", "playres", "yscrolledby:", "timer:", "synctime",
)


def decode_text(raw: bytes) -> str:
    """按常见中文编码顺序尝试解码（UTF-8 → GB18030/Big5 → 兜底忽略错误）"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


def srt_to_vtt(text: str) -> str:
    body = _SRT_TS.sub(lambda m: f"{m.group(1)}.{m.group(2)}", text.replace("\r\n", "\n"))
    return "WEBVTT\n\n" + body.lstrip("\ufeff").strip() + "\n"


def vtt_to_srt(text: str) -> str:
    body = text.replace("\r\n", "\n")
    if body.lstrip().startswith("WEBVTT"):
        body = body.lstrip()[len("WEBVTT"):].lstrip("\n")
    return _VTT_TS.sub(lambda m: f"{m.group(1)},{m.group(2)}", body).strip() + "\n"


def ass_to_vtt(text: str) -> str:
    """ASS/SSA 事件行 → WebVTT（丢掉样式标签与特效，保留时间轴与文本）"""
    out = ["WEBVTT", ""]
    in_events = False
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_events = line.lower() == "[events]"
            continue
        if not in_events or not line or line.lower().startswith(_ASS_SKIP):
            continue
        # Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        parts = line.split(",", 9)
        if len(parts) < 10 or not parts[0].lower().startswith("dialogue"):
            continue

        def _ts(value: str) -> Optional[str]:
            m = _ASS_TIME.fullmatch(value.strip())
            if not m:
                return None
            h, mnt, sec, frac = m.groups()
            return f"{int(h):02d}:{mnt}:{sec}.{int(frac.ljust(3, '0')[:3]):03d}"

        start, end = _ts(parts[1]), _ts(parts[2])
        if not start or not end:
            continue
        body = _ASS_TAG.sub("", parts[9]).replace("\\N", "\n").replace("\\n", "\n").strip()
        if body:
            out += [f"{start} --> {end}", body, ""]
    return "\n".join(out)


def to_vtt(text: str) -> str:
    """把任意文本字幕规范化为 WebVTT"""
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith("WEBVTT"):
        return text
    if "[Script Info]" in text or _ASS_TIME.search(text):
        return ass_to_vtt(text)
    return srt_to_vtt(text)


def is_text_track(codec: Optional[str]) -> bool:
    codec = (codec or "").lower()
    if codec in IMAGE_SUB_CODECS:
        return False
    return codec in TEXT_SUB_CODECS or codec == ""


def _cache_path(item_guid: str, stream_index: int) -> str:
    return os.path.join(SUB_CACHE_DIR, f"{item_guid}_{stream_index}.vtt")


def extract_embedded(media_path: str, item_guid: str, stream_index: int, subtitle_ordinal: int) -> str:
    """用 ffmpeg 把内封字幕轨抽取为 WebVTT，结果按条目+轨道缓存到磁盘"""
    cached = _cache_path(item_guid, stream_index)
    if os.path.isfile(cached) and os.path.getsize(cached) > 0:
        return cached
    if not media_path or not os.path.isfile(media_path):
        raise HTTPException(status_code=404, detail="Media file not found")
    if not shutil.which(FFMPEG):
        raise HTTPException(status_code=503, detail="服务器未安装 ffmpeg，无法抽取内封字幕")
    os.makedirs(SUB_CACHE_DIR, exist_ok=True)
    tmp = cached + ".part"
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", media_path, "-map", f"0:s:{subtitle_ordinal}", "-c:s", "webvtt", tmp,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="字幕抽取超时")
    if proc.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise HTTPException(status_code=404, detail="该字幕轨无法抽取为文本字幕")
    os.replace(tmp, cached)
    logger.info("内封字幕已抽取 %s 轨道 %s", item_guid, stream_index)
    return cached


def render_subtitle(
    *,
    item_guid: str,
    media_path: Optional[str],
    stream,
    fmt: str,
    subtitle_ordinal: int,
) -> Response:
    """产出字幕响应体

    stream: em.MediaStream 行（需有 codec / is_external / external_path / stream_index）
    """
    fmt = (fmt or "vtt").lower().lstrip(".")
    if fmt not in RAW_OK:
        fmt = "vtt"

    external = (stream.external_path or "").strip() if stream.is_external else ""
    if external and os.path.isfile(external):
        ext = os.path.splitext(external)[1].lower()
        if ext not in TEXT_EXTS:
            raise HTTPException(status_code=415, detail="该外挂字幕不是文本字幕")
        with open(external, "rb") as f:
            text = decode_text(f.read())
        # 源格式与请求格式一致时原样返回，避免无意义转换
        if ext in RAW_OK.get(fmt, set()):
            return Response(content=text, media_type=MIME.get(fmt, DEFAULT_MIME))
        vtt = to_vtt(text)
        if fmt == "vtt":
            return Response(content=vtt, media_type=MIME["vtt"])
        if fmt == "srt":
            return Response(content=vtt_to_srt(vtt), media_type=MIME["srt"])
        return Response(content=vtt, media_type=DEFAULT_MIME)

    if not is_text_track(stream.codec):
        raise HTTPException(status_code=415, detail="图片类字幕（PGS/VobSub）不支持直接投递")
    path = extract_embedded(media_path or "", item_guid, stream.stream_index, subtitle_ordinal)
    with open(path, "rb") as f:
        vtt = decode_text(f.read())
    if fmt == "srt":
        return Response(content=vtt_to_srt(vtt), media_type=MIME["srt"])
    if fmt == "vtt":
        return Response(content=vtt, media_type=MIME["vtt"])
    return Response(content=vtt, media_type=DEFAULT_MIME)
