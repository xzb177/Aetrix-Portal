"""自建 Emby 服务器：流媒体服务（直连流 / Range / HLS 转码）"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

logger = logging.getLogger(__name__)

TRANSCODE_DIR = os.getenv("EMBY_TRANSCODE_DIR", "/tmp/emby_transcode")
# 远程挂载（115 / WebDAV / AList）代理转发时的 UA
REMOTE_UA = os.getenv("MOUNT_UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
FFMPEG = os.getenv("EMBY_FFMPEG_PATH", "ffmpeg")
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")

CHUNK = 1024 * 256


def _range_header(start: int, end: int, total: int) -> dict:
    return {
        "Content-Range": f"bytes {start}-{end}/{total}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    }


def serve_file(path: str, request: Request, media_type: str = "video/mp4") -> StreamingResponse:
    """带 Range 支持的文件流式响应"""
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Media file not found")
    size = os.path.getsize(path)

    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

    m = RANGE_RE.match(range_header)
    if not m:
        raise HTTPException(status_code=416, detail="Invalid Range")

    start = int(m.group(1)) if m.group(1) else 0
    end = int(m.group(2)) if m.group(2) else min(start + CHUNK * 200, size - 1)
    end = min(end, size - 1)
    if start > end or start >= size:
        raise HTTPException(status_code=416, detail="Requested range not satisfiable")

    def iter_file():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = f.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iter_file(),
        status_code=206,
        media_type=media_type,
        headers=_range_header(start, end, size),
    )


def headers_arg(headers: Optional[dict]) -> list[str]:
    """把请求头转成 ffmpeg/ffprobe 的 ``-headers`` 参数（Cookie / 令牌不出服务器）"""
    if not headers:
        return []
    joined = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    return ["-headers", joined]


def serve_remote(
    url: str,
    request: Request,
    headers: Optional[dict] = None,
    media_type: str = "video/mp4",
) -> StreamingResponse:
    """远程媒体代理：把客户端的请求（含 Range）转发到远端直链并流式回传

    为什么不直接 302 到第三方直链：

    - **凭据不下发**：115 Cookie、WebDAV Basic、AList 令牌全部留在服务器；
    - **地址稳定**：客户端只看到本服务器地址，换源 / 直链过期不需要客户端重新入库；
    - **可控**：代理层可以限速、统计与统一处理 CORS / Referer / UA 白名单。

    响应状态码与 ``Content-Range`` / ``Content-Length`` 原样透传，播放器的拖动与续播
    依赖它们，不能被吞掉。
    """
    import httpx

    forward = {k: v for k, v in (headers or {}).items()}
    forward.setdefault("User-Agent", REMOTE_UA)
    range_header = request.headers.get("range")
    if range_header:
        forward["Range"] = range_header

    client = httpx.Client(timeout=httpx.Timeout(30.0, read=None), follow_redirects=True)
    try:
        resp = client.send(client.build_request("GET", url, headers=forward), stream=True)
    except Exception as exc:  # noqa: BLE001 — 源站不可达：给出干净的 502，而非 500 堆栈
        client.close()
        logger.warning("远程媒体代理失败 %s: %s", url.split("?")[0], exc)
        raise HTTPException(status_code=502, detail="源站不可达")

    if resp.status_code >= 400:
        status = resp.status_code
        resp.close()
        client.close()
        logger.warning("远程媒体源站返回 %s: %s", status, url.split("?")[0])
        raise HTTPException(status_code=502 if status >= 500 else status, detail=f"源站返回 {status}")

    passthrough = {}
    for name in ("content-range", "accept-ranges", "content-length", "last-modified", "etag"):
        value = resp.headers.get(name)
        if value:
            passthrough[name.title()] = value
    content_type = resp.headers.get("content-type") or media_type

    def iter_remote():
        try:
            for chunk in resp.iter_bytes(CHUNK):
                yield chunk
        finally:
            resp.close()
            client.close()

    return StreamingResponse(
        iter_remote(), status_code=resp.status_code, media_type=content_type, headers=passthrough,
    )


def serve_image(path: Optional[str]) -> FileResponse:
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Image not found")
    ext = os.path.splitext(path)[1].lower()
    media_type = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media_type)


def build_hls_command(
    file_path: str,
    out_dir: str,
    start_seconds: float = 0,
    video_bitrate: int = 4_000_000,
    audio_bitrate: int = 128_000,
    height: Optional[int] = None,
    copy_video: bool = False,
    input_headers: Optional[dict] = None,
) -> subprocess.Popen:
    """启动 ffmpeg HLS 转码进程

    ``file_path`` 可以是本机文件，也可以是远程直链（挂载来源）：ffmpeg 本身支持 http(s)
    输入，凭据通过 ``input_headers`` 传入。
    """
    os.makedirs(out_dir, exist_ok=True)
    playlist = os.path.join(out_dir, "master.m3u8")

    seek = ["-ss", str(start_seconds)] if start_seconds > 0 else []
    if copy_video:
        vcodec = ["-c:v", "copy"]
    else:
        vcodec = [
            "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(video_bitrate),
            "-maxrate", str(int(video_bitrate * 1.2)), "-bufsize", str(video_bitrate * 2),
        ]
        if height:
            vcodec += ["-vf", f"scale=-2:{height}"]
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        *seek, *headers_arg(input_headers), "-i", file_path,
        *vcodec,
        "-c:a", "aac", "-b:a", str(audio_bitrate), "-ac", "2",
        "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
        "-hls_flags", "independent_segments+temp_file",
        "-hls_segment_filename", os.path.join(out_dir, "seg%05d.ts"),
        playlist,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_transcode(
    file_path: str,
    start_seconds: float = 0,
    video_bitrate: int = 4_000_000,
    height: Optional[int] = None,
    user_id: Optional[int] = None,
    item_guid: Optional[str] = None,
    input_headers: Optional[dict] = None,
) -> str:
    """启动转码，返回播放列表 URL 路径片段 /emby/videos/{session}/master.m3u8

    同一用户重复请求同一部影片时复用进行中的转码会话，避免客户端重试/多端拉起时
    反复 fork ffmpeg（旧实现每次请求 master.m3u8 都会新建一个进程）。
    """
    reap_stale_transcodes()
    if user_id is not None and item_guid:
        existing = find_active_transcode(user_id, item_guid)
        if existing:
            logger.info("复用进行中的 HLS 转码 %s", existing)
            return existing
    session_id = uuid.uuid4().hex[:16]
    out_dir = os.path.join(TRANSCODE_DIR, session_id)
    proc = build_hls_command(file_path, out_dir, start_seconds, video_bitrate, height,
                             input_headers=input_headers)
    _TRANSCODE_PROCS[session_id] = {
        "proc": proc,
        "dir": out_dir,
        "started": datetime.now(),
        "user_id": user_id,
        "item_guid": item_guid,
        "file_path": file_path,
    }
    logger.info("HLS 转码启动 %s -> %s", os.path.basename(file_path), session_id)
    return session_id


def find_active_transcode(user_id: int, item_guid: str) -> Optional[str]:
    """查找同一用户同一影片仍在运行的转码会话"""
    for sid, info in _TRANSCODE_PROCS.items():
        if info.get("user_id") != user_id or info.get("item_guid") != item_guid:
            continue
        proc = info.get("proc")
        if proc is not None and proc.poll() is None:
            return sid
    return None


def reap_stale_transcodes(max_age_seconds: int = 6 * 3600) -> int:
    """回收已退出 / 超龄的转码会话（含清理磁盘目录）

    客户端异常断开时不会上报 Stopped，若不回收会长期残留 ffmpeg 进程与临时分片。
    """
    now = datetime.now()
    reaped = 0
    for sid, info in list(_TRANSCODE_PROCS.items()):
        proc = info.get("proc")
        started = info.get("started") or now
        exited = proc is not None and proc.poll() is not None
        expired = (now - started).total_seconds() > max_age_seconds
        if exited or expired:
            stop_transcode(sid)
            reaped += 1
    if reaped:
        logger.info("回收 %d 个失效 HLS 转码会话", reaped)
    return reaped


def wait_for_file(path: str, timeout: float = 10.0, interval: float = 0.2) -> bool:
    """等待 ffmpeg 产出目标文件（客户端请求切片往往早于转码进度）"""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return True
        time.sleep(interval)
    return os.path.isfile(path) and os.path.getsize(path) > 0


def stop_transcode(session_id: str) -> None:
    info = _TRANSCODE_PROCS.pop(session_id, None)
    if not info:
        return
    proc = info["proc"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    shutil.rmtree(info["dir"], ignore_errors=True)


def stop_all_transcodes() -> int:
    count = len(_TRANSCODE_PROCS)
    for sid in list(_TRANSCODE_PROCS.keys()):
        stop_transcode(sid)
    return count


def stop_user_transcodes(user_id: int) -> int:
    """停止某用户的全部转码会话（客户端请求 ActiveEncodings/Delete 时调用）"""
    stopped = 0
    for sid, info in list(_TRANSCODE_PROCS.items()):
        if info.get("user_id") == user_id:
            stop_transcode(sid)
            stopped += 1
    return stopped


def get_transcode(session_id: str):
    return _TRANSCODE_PROCS.get(session_id)


def transcode_alive(session_id: str) -> bool:
    """转码进程是否仍在运行（会话登记在册且进程还活着）"""
    info = _TRANSCODE_PROCS.get(session_id)
    if not info:
        return False
    proc = info.get("proc")
    return proc is not None and proc.poll() is None


def active_transcode_ids() -> list:
    """当前登记在册的转码会话 id（维护/健康检查用；不要在遍历中改字典）"""
    return list(_TRANSCODE_PROCS.keys())


_TRANSCODE_PROCS: dict[str, dict] = {}


def is_transcode(session_id: str) -> bool:
    return session_id in _TRANSCODE_PROCS
