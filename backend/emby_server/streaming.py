"""自建 Emby 服务器：流媒体服务（直连流 / Range / HLS 转码）"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from email.utils import formatdate
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

    raw_start, raw_end = m.group(1), m.group(2)
    if not raw_start:
        # 后缀形式 ``bytes=-500``：表示「文件最后 500 字节」。旧实现当成 start=0/end=500，
        # 返回的是文件**开头**——播放器探测 MP4 尾部 moov 时拿到错字节，部分会黑屏/ \
        # 播放失败。这里按 RFC 7233 解析成末尾区间。
        suffix = int(raw_end or 0)
        if suffix <= 0:
            raise HTTPException(status_code=416, detail="Invalid Range")
        start, end = max(0, size - suffix), size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else min(start + CHUNK * 200, size - 1)
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


async def serve_remote_async(
    url: str,
    request: Request,
    headers: Optional[dict] = None,
    media_type: str = "video/mp4",
) -> StreamingResponse:
    """远程媒体代理（异步版）：语义与 ``serve_remote`` 完全一致，但不在事件循环上等源站

    播放路径上的每次 Range 请求都要等「连上源站 + 源站回首字节」，同步客户端会把这等待
    变成整个进程的暂停（一个用户拖进度条，其他人全部卡住）。异步版的等待只挂起当前请求，
    Range / 状态码 / 透传头的口径与同步版逐项对齐，且凭据同样不下发。
    """
    import httpx

    forward = {k: v for k, v in (headers or {}).items()}
    forward.setdefault("User-Agent", REMOTE_UA)
    range_header = request.headers.get("range")
    if range_header:
        forward["Range"] = range_header

    client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None), follow_redirects=True)
    try:
        resp = await client.send(client.build_request("GET", url, headers=forward), stream=True)
    except Exception as exc:  # noqa: BLE001 — 源站不可达：给出干净的 502，而非 500 堆栈
        await client.aclose()
        logger.warning("远程媒体代理失败 %s: %s", url.split("?")[0], exc)
        raise HTTPException(status_code=502, detail="源站不可达") from exc

    if resp.status_code >= 400:
        status = resp.status_code
        await resp.aclose()
        await client.aclose()
        logger.warning("远程媒体源站返回 %s: %s", status, url.split("?")[0])
        raise HTTPException(status_code=502 if status >= 500 else status, detail=f"源站返回 {status}")

    passthrough = {}
    for name in ("content-range", "accept-ranges", "content-length", "last-modified", "etag"):
        value = resp.headers.get(name)
        if value:
            passthrough[name.title()] = value
    content_type = resp.headers.get("content-type") or media_type

    async def iter_remote():
        try:
            async for chunk in resp.aiter_bytes(CHUNK):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        iter_remote(), status_code=resp.status_code, media_type=content_type, headers=passthrough,
    )


def _file_validators(stat: os.stat_result) -> tuple[str, str]:
    """按「mtime + 大小」生成 ETag 与 Last-Modified（内容一变校验器就变）"""
    return f'"{int(stat.st_mtime)}-{stat.st_size}"', formatdate(stat.st_mtime, usegmt=True)


def serve_image(path: Optional[str]) -> FileResponse:
    """图片响应：带 ETag / Last-Modified 与 24h 客户端强制缓存

    浏览媒体库时同一张海报会被反复请求（滚动、返回、切页），旧实现每次整文件重发。
    现在响应带 ``ETag`` / ``Last-Modified`` 与 ``Cache-Control: public, max-age=86400``，
    浏览器与客户端在有效期内直接命中本地缓存，不再为同一张图重复付出磁盘 I/O 与带宽。
    """
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Image not found")
    ext = os.path.splitext(path)[1].lower()
    media_type = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    try:
        stat = os.stat(path)
    except OSError:  # 判断与取属性之间文件被删 / 挂载掉线：干净 404，不要 500
        raise HTTPException(status_code=404, detail="Image not found") from None
    etag, last_modified = _file_validators(stat)
    headers = {
        "ETag": etag,
        "Last-Modified": last_modified,
        "Cache-Control": "public, max-age=86400",
        "Accept-Ranges": "bytes",
    }
    return FileResponse(path, media_type=media_type, headers=headers)


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
    # ffmpeg 的报错不能丢进 DEVNULL：deploy-ea.md 让运维在服务日志里找转码失败原因，
    # 而日志里必须真的有原因。改写到会话目录里的 ffmpeg.log（随会话目录一起清理），
    # 异常退出时再把尾部提升到服务日志（见 _log_ffmpeg_tail）。
    log_path = os.path.join(out_dir, "ffmpeg.log")
    with open(log_path, "wb") as log_file:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log_file)


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
    # 失效会话回收与并发上限保护放到后台线程：它们要 terminate 子进程、等它退出、
    # 删目录（最坏几秒），而本函数是在请求路径（事件循环）上被调用的，不该让本次播放
    # 为别人遗留的会话等待（见 _reap_in_background）。
    threading.Thread(target=_reap_in_background, daemon=True).start()
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
        "item_guid": item_guid,      # 「结束播放」按它反查（见 find_transcodes）
        "file_path": file_path,
    }
    logger.info("HLS 转码启动 %s -> %s", os.path.basename(file_path), session_id)
    return session_id


def find_transcodes(user_id: int, item_guid: Optional[str] = None) -> list:
    """按「用户 + 条目」找转码会话 id（``item_guid`` 省略时 = 该用户全部）

    转码会话 id 是 ``start_transcode`` 生成的随机 uuid，只出现在 HLS 播放列表的
    ``?session=`` 上；而客户端的 ``PlaySessionId``（播放会话键，随机 ``s…``）
    **不是同一个东西**。所以「结束这场播放」必须从播放会话反查出该条目的 guid 再按
    (user_id, item_guid) 找，不能拿播放会话键去 pop——旧实现就是这么写的，等于什么都没停到。
    """
    return [sid for sid, info in list(_TRANSCODE_PROCS.items())
            if info.get("user_id") == user_id
            and (item_guid is None or info.get("item_guid") == item_guid)]


def find_active_transcode(user_id: int, item_guid: str) -> Optional[str]:
    """查找同一用户同一影片仍在运行的转码会话"""
    for sid, info in _TRANSCODE_PROCS.items():
        if info.get("user_id") != user_id or info.get("item_guid") != item_guid:
            continue
        proc = info.get("proc")
        if proc is not None and proc.poll() is None:
            return sid
    return None


def _reap_in_background() -> None:
    """后台回收失效/超龄会话并执行并发上限保护（由 start_transcode 异步触发）

    ``start_transcode`` 是在请求路径（事件循环）上被调用的，而回收要 terminate 子进程、
    等它退出、删目录（最坏几秒）；放到后台线程后，本次播放不再为别人遗留的会话排队。
    """
    try:
        reap_stale_transcodes()
        enforce_transcode_capacity()
    except Exception as exc:  # noqa: BLE001 — 后台回收失败不能影响本次播放
        logger.warning("后台回收转码会话失败: %s", exc)


def reap_stale_transcodes(max_age_seconds: int = 6 * 3600) -> int:
    """回收已退出 / 超龄的转码会话（含清理磁盘目录）

    客户端异常断开时不会上报 Stopped，若不回收会长期残留 ffmpeg 进程与临时分片。

    同步实现，调用方都是**线程**（``_reap_in_background`` 后台线程、维护周期 ``janitor_tick``），
    不在事件循环上：这里会逐个 ``terminate`` + ``wait`` + 删目录，本身就是慢调用。
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


async def wait_for_file(path: str, timeout: float = 10.0, interval: float = 0.2) -> bool:
    """等待 ffmpeg 产出目标文件（客户端请求切片往往早于转码进度）

    异步等待：旧实现用同步 ``time.sleep`` 轮询，等首片（最多 15s）或等切片（最多 12s）
    的请求会把整个事件循环占住，同一进程里其他人正在播放的请求全部排队等待。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return True
        await asyncio.sleep(interval)
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _terminate_and_cleanup(session_id: str, info: dict) -> None:
    """停掉转码的**阻塞部分**：结束子进程 + 提升日志尾部 + 删会话目录

    两处都是慢调用：``proc.wait(timeout=5)`` 要等 ffmpeg 响应 SIGTERM（它可能正在写
    最后几个分片），``shutil.rmtree`` 要递归删掉整场播放的分片（上千个文件，挂载目录上更慢）。
    只在线程 / 同步路由 / 后台回收线程里直接调；事件循环上一律走 ``stop_transcode_async``。
    """
    proc = info["proc"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()          # SIGTERM 不理就 SIGKILL，否则进程会一直挂着
    _log_ffmpeg_tail(info.get("dir") or "", session_id, proc.poll())
    shutil.rmtree(info["dir"], ignore_errors=True)


def stop_transcode(session_id: str) -> None:
    """同步停止一次转码（后台回收线程 / 同步 ``def`` 路由用）

    **不要在 ``async def`` 里直接调它**：它会阻塞到子进程退出与目录删完（最坏 5 秒起），
    一次调用就把整个进程的播放卡住。事件循环上用 ``stop_transcode_async``（同文件下方），
    ``scripts/smoke_test_transcode_stop.py`` 会静态拦住这个错误写法。
    """
    info = _TRANSCODE_PROCS.pop(session_id, None)
    if not info:
        return
    _terminate_and_cleanup(session_id, info)


async def stop_transcode_async(session_id: str) -> None:
    """异步停止一次转码——阻塞部分丢线程池，事件循环不等待

    v2.12/v2.13 修的就是这一类问题（阻塞调用不许出现在事件循环上），但 ``stop_transcode``
    一直是漏网的那一个：管理员点「结束播放」、客户端上报 Stop、维护周期回收会话，
    都会在 ``async def`` 路由里同步等上 5 秒 + 删一轮分片——全站一起顿住。

    登记摘除（``pop``）仍在调用线程里同步完成，所以并发的两次停止只有一个真正拿到会话，
    不会重复 terminate / 重复删目录。
    """
    info = _TRANSCODE_PROCS.pop(session_id, None)
    if not info:
        return
    await asyncio.to_thread(_terminate_and_cleanup, session_id, info)


def _log_ffmpeg_tail(directory: str, session_id: str, returncode) -> None:
    """ffmpeg 异常退出时把日志尾部提升到服务日志（排查转码失败时唯一的线索）"""
    if not directory or returncode in (0, None, -15):  # 正常结束 / 被本服务 SIGTERM
        return
    try:
        with open(os.path.join(directory, "ffmpeg.log"), "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 2048))
            tail = handle.read().decode("utf-8", "replace").strip()
    except OSError:
        return
    if tail:
        logger.warning(
            "HLS 转码 %s 异常退出（code=%s），ffmpeg 日志尾部：\n%s", session_id, returncode, tail,
        )


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


def stop_transcodes_for(user_id: int, item_guid: Optional[str] = None) -> int:
    """同步停掉某用户某个条目的转码会话（同步 ``def`` 路由 / 线程里用）"""
    ids = find_transcodes(user_id, item_guid)
    for sid in ids:
        stop_transcode(sid)
    return len(ids)


async def stop_transcodes_for_async(user_id: int, item_guid: Optional[str] = None) -> int:
    """异步停掉某用户某个条目的转码会话（事件循环上用这个，见 stop_transcode_async）"""
    ids = find_transcodes(user_id, item_guid)
    if ids:
        await asyncio.gather(*(stop_transcode_async(sid) for sid in ids))
    return len(ids)


async def stop_all_transcodes_async() -> int:
    """异步停掉全部转码会话（管理后台「停止全部转码」用）

    并发执行：``async def`` 路由里逐个 ``await`` 会让总耗时变成「会话数 × 等待时间」
    （N 路转码同时被停就是 5×N 秒），gather 之后总耗时≈单个会话。
    """
    ids = list(_TRANSCODE_PROCS.keys())
    if ids:
        await asyncio.gather(*(stop_transcode_async(sid) for sid in ids))
    return len(ids)


async def stop_user_transcodes_async(user_id: int) -> int:
    """异步停掉某用户的全部转码会话（同上，并发执行）"""
    ids = [sid for sid, info in list(_TRANSCODE_PROCS.items())
           if info.get("user_id") == user_id]
    if ids:
        await asyncio.gather(*(stop_transcode_async(sid) for sid in ids))
    return len(ids)


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


def transcode_capacity() -> int:
    """允许同时运行的转码路数（默认按 CPU 核数：veryfast 单路按一核估算）"""
    raw = os.getenv("EMBY_MAX_TRANSCODES", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return max(1, os.cpu_count() or 2)


def transcode_idle_seconds() -> float:
    """输出目录多久没有新分片就认为这场播放已经没人看了（默认 120s）"""
    try:
        value = float(os.getenv("EMBY_TRANSCODE_IDLE", "") or 120)
    except ValueError:
        value = 120.0
    return value if value > 0 else 120.0


def _transcode_idle(info: dict) -> float:
    """转码中 ffmpeg 会持续写分片：目录最近写入时间就是「还有人看」的信号"""
    try:
        return max(0.0, time.time() - os.path.getmtime(info.get("dir") or ""))
    except OSError:
        return float("inf")  # 目录已不在：视为空闲，优先回收


def enforce_transcode_capacity() -> None:
    """并发上限保护：CPU 被多路转码打满时，先停掉已经没人看的会话

    同步实现（内部会等子进程退出 + 删目录）；调用方是后台回收线程，不在事件循环上。

    客户端切清晰度 / 拖进度后重新拉起、或者直接杀掉应用，都不会上报 Stopped，
    只留下一个不再增长的输出目录。这里**只回收闲置超时的会话**，不为了让新请求
    进场而掉头挚掉正在播放的会话：宁可短暂超限并告警，也不能让用户正看着的片子中断
    （上限可用 ``EMBY_MAX_TRANSCODES``、闲置判定用 ``EMBY_TRANSCODE_IDLE`` 调整）。
    """
    cap = transcode_capacity()
    running = {
        sid: info for sid, info in list(_TRANSCODE_PROCS.items())
        if info.get("proc") is not None and info["proc"].poll() is None
    }
    if len(running) < cap:
        return
    idle_limit = transcode_idle_seconds()
    for sid, info in sorted(running.items(), key=lambda kv: _transcode_idle(kv[1]), reverse=True):
        if len(running) <= cap - 1:
            break
        idle = _transcode_idle(info)
        if idle < idle_limit:
            break  # 已按闲置时间降序，后面只会更活跃
        logger.info("回收空闲 HLS 转码会话 %s（闲置 %.0fs，并发上限 %d）", sid, idle, cap)
        stop_transcode(sid)
        running.pop(sid, None)
    if len(running) >= cap:
        logger.warning(
            "HLS 转码并发已达上限 %d，本次仍继续启动（不中断正在播放的用户）；"
            "可用 EMBY_MAX_TRANSCODES 调整上限", cap,
        )


_TRANSCODE_PROCS: dict[str, dict] = {}


def is_transcode(session_id: str) -> bool:
    return session_id in _TRANSCODE_PROCS
