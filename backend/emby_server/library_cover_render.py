"""媒体库封面渲染：从库里最近的海报自动拼一张 1920×1080 的横版封面

后台「媒体库封面」三种自动样式，管理员不用传图配字，系统自己去库里挑：

- ``poster``    海报拼贴：底图虚化铺满，前景放多张海报扇形排布
- ``visual``    主视觉：一张大图铺满，底部渐变压文字
- ``filmstrip`` 胶片带：横向三格，每格不同海报

**选图规则**「最新入库的海报」：按 ``emby_items.last_scraped_at``（刮削完成时刻）倒序，
取最近入库且有海报的条目。不能用 ``updated_at``——进度刷盘每几秒就刷一次，
它永远是「刚刚」，排不出新片。海报优先用 ``poster_path``（已本地化到磁盘
的文件），没有才退回 ``primary_image_url`` 远程地址。这样刚补完刮削的库
会立刻换成新海报，不用手动点重新生成。

标题 / 副标题支持三个变量：``{library}`` 媒体库名、``{type}`` 内容类型、
``{year}`` 当前年份（内容年份要从条目聚合才有意义，这里刻意不查库，
避免每改一个字都打一次库）。

**字体不可用时自动省略文字**：字体缺失/损坏/Pillow 没装时仍出图（纯底图），
不抛异常——封面是锦上添花，不能因字体问题连上传和展示都做不了。

输出统一 1920×1080 WebP（面板展示就是横版，与自动生成样式一致）。
"""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import List, Optional, Sequence

logger = logging.getLogger("aetrix.library_cover")

CANVAS_W = 1920
CANVAS_H = 1080

TEMPLATES = ("poster", "visual", "filmstrip")
DEFAULT_TEMPLATE = "poster"
# 各模板需要几张海报（不够就少放几张，不补空白）
TEMPLATE_POSTER_COUNT = 5
TEMPLATE_FILMSTRIP_COUNT = 3

_FONT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts"
)
_FONT_BOLD = os.path.join(_FONT_DIR, "NotoSansSC-Bold.ttf")
_FONT_REGULAR = os.path.join(_FONT_DIR, "NotoSansSC-Regular.ttf")

_font_cache: dict = {}


def _pil():
    """Pillow 不可用时返回 None，调用方据此走「无字出图」"""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont

        return Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:  # pragma: no cover
        logger.warning("Pillow 不可用，封面将不渲染文字")
        return None


def _font(size: int, bold: bool = False):
    """取一个已缓存的中文字体；取不到返回 None（调用方省略文字）"""
    pil = _pil()
    if pil is None:
        return None
    _img, _draw, _filter, ImageFont = pil
    path = _FONT_BOLD if bold else _FONT_REGULAR
    key = (path, size)
    if key in _font_cache:
        return _font_cache[key]
    if not os.path.isfile(path):
        logger.warning("封面字体缺失：%s，文字将被省略", path)
        _font_cache[key] = None
        return None
    try:
        loaded = ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        logger.warning("封面字体无法加载：%s，文字将被省略", path, exc_info=True)
        loaded = None
    _font_cache[key] = loaded
    return loaded


# collection_type 存的是 API 名（tvshows/movies…），直接显示给管理员看是英文，
# 这里映射成中文；未知值原样透出，至少不空。
TYPE_LABELS = {
    "tvshows": "剧集", "tvshow": "剧集", "series": "剧集",
    "movies": "电影", "movie": "电影", "film": "电影",
    "music": "音乐", "musicalbum": "音乐", "audio": "音乐",
    "mixed": "混合", "boxset": "合集",
}


def human_media_type(media_type: str) -> str:
    """把 collection_type 的 API 名翻成中文（未知值原样返回）"""
    key = (media_type or "").strip().lower()
    return TYPE_LABELS.get(key, media_type or "")


def render_text(text: str, library_name: str, media_type: str,
                year: Optional[int] = None) -> str:
    """把 ``{library}`` / ``{type}`` / ``{year}`` 换成实际值

    未知占位符原样保留（便于管理员看出写错了），纯空白返回空串。
    """
    if not text:
        return ""
    return (text
            .replace("{library}", library_name or "")
            .replace("{type}", human_media_type(media_type))
            .replace("{year}", str(year or datetime.now().year))
            ).strip()


# ---------------- 选图 ----------------

def pick_recent_posters(db, library, limit: int) -> List[str]:
    """取该库**最新入库**且有海报的若干条，返回可用的本地文件路径

    排序用 ``last_scraped_at``（刮削完成时刻）。两个坑：

    - 不能用 ``updated_at``：进度刷盘每几秒写一次，它永远是「刚刚」；
    - 表上没有 ``created_at``（模型有、PG 库没补上这列），而刮削完成才
      意味着海报就位，所以 ``last_scraped_at`` 才是「新入库且有图」的准确
      时刻，排出来的正是刚补完刮削的那批新片。

    海报优先 ``poster_path``（已本地化到磁盘），其次 ``primary_image_url``。
    取不够 ``limit`` 张时继续往后翻，不足就少给——渲染层会按实际张数排版。
    """
    from backend.emby_server.models import MediaItem

    query = (db.query(MediaItem)
             .filter(MediaItem.library_id == library.id)
             .filter(MediaItem.last_scraped_at.isnot(None))
             .filter((MediaItem.poster_path.isnot(None)) | (MediaItem.primary_image_url.isnot(None)))
             .order_by(MediaItem.last_scraped_at.desc())
             .limit(max(limit * 4, 20)))
    rows = query.all()

    def _usable(value) -> Optional[str]:
        """海报值 → 可读路径；不可用返回 None

        ``poster_path`` 存的就是磁盘上的本地文件，**不能**再过
        ``image_store.local_path()``——那个函数是给远程 URL 算内容寻址
        缓存路径的（sha1(url)[:24] + 后缀），把本地路径喂进去会得到一个
        根本不存在的文件名，于是「明明有海报却一张都选不出来」。
        """
        if not value:
            return None
        text = str(value)
        if text.startswith(("http://", "https://")):
            return text  # 远程：留给出图阶段按需下载
        return text if os.path.isfile(text) else None

    picked: List[str] = []
    for item in rows:
        for candidate in (item.poster_path, item.primary_image_url):
            usable = _usable(candidate)
            if usable:
                picked.append(usable)
                break
        if len(picked) >= limit:
            break
    return picked[:limit]


# ---------------- 出图 ----------------

def _open_source(Image_, src: str):
    """打开一张海报：本地路径直接读，远程 URL 现下载（带超时）"""
    if str(src).startswith(("http://", "https://")):
        import httpx

        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(src)
                if resp.status_code >= 400:
                    return None
                return Image_.open(io.BytesIO(resp.content))
        except Exception:  # noqa: BLE001
            logger.debug("封面底图下载失败：%s", src, exc_info=True)
            return None
    try:
        return Image_.open(src)
    except Exception:  # noqa: BLE001
        logger.debug("封面底图无法打开：%s", src, exc_info=True)
        return None


def _text_block(img, title: str, subtitle: str) -> bool:
    """底部渐变遮罩 + 标题/副标题。返回是否真的画了字"""
    pil = _pil()
    if pil is None:
        return False
    Image_, ImageDraw, _filter, _font_mod = pil

    title_font = _font(int(img.height * 0.082), bold=True) if title else None
    sub_font = _font(int(img.height * 0.040)) if subtitle else None
    if title_font is None and sub_font is None:
        return False

    grad_top = int(img.height * 0.42)
    grad_h = img.height - grad_top
    strip = Image_.new("L", (1, grad_h), 0)
    for y in range(grad_h):
        strip.putpixel((0, y), int(215 * ((y / max(1, grad_h - 1)) ** 1.6)))
    alpha = Image_.new("RGBA", (img.width, grad_h), (8, 10, 18, 0))
    alpha.putalpha(strip.resize((img.width, grad_h)))
    img.alpha_composite(alpha, (0, grad_top))

    draw = ImageDraw.Draw(img)
    pad = int(img.width * 0.055)
    if title_font is not None:
        y = img.height - int(img.height * 0.20) - (int(img.height * 0.055)
                                                 if sub_font is not None else 0)
        draw.text((pad, y), title, font=title_font, fill=(255, 255, 255, 255))
    if sub_font is not None:
        y = img.height - int(img.height * 0.115)
        x = pad
        for ch in subtitle:   # 副标题带字距，手写逐字排
            draw.text((x, y), ch, font=sub_font, fill=(206, 214, 232, 255))
            x += draw.textlength(ch, font=sub_font) + 2
    return True


def _cover_fit(crop_anchor: float = 0.5):
    """等比缩放到目标框内并居中裁切；``crop_anchor`` 纵向取景位置"""
    def fit(image, box_w: int, box_h: int, Image_):
        scale = max(box_w / image.width, box_h / image.height)
        big = image.resize((max(1, int(image.width * scale)),
                            max(1, int(image.height * scale))), Image_.LANCZOS)
        left = (big.width - box_w) // 2
        top = int((big.height - box_h) * crop_anchor)
        return big.crop((left, top, left + box_w, top + box_h))
    return fit


def _template_visual(img, posters, Image_, ImageFilter) -> None:
    """主视觉：第一张铺满；底图不够大时用自身模糊放大补底"""
    base = _open_source(Image_, posters[0]).convert("RGB")
    scale = max(img.width / base.width, img.height / base.height)
    big = base.resize((max(1, int(base.width * scale)), max(1, int(base.height * scale))),
                      Image_.LANCZOS)
    if scale > 1:
        blur = big.filter(ImageFilter.GaussianBlur(radius=20))
        img.paste(_cover_fit()(blur, img.width, img.height, Image_), (0, 0))
    img.paste(_cover_fit()(big, img.width, img.height, Image_), (0, 0))


def _template_poster(img, posters, Image_, ImageFilter) -> None:
    """海报拼贴：最近的海报虚化铺底，前面扇形排布最多 5 张"""
    first = _open_source(Image_, posters[0]).convert("RGB")
    bg = first.filter(ImageFilter.GaussianBlur(radius=30))
    scale = max(img.width / bg.width, img.height / bg.height)
    bg = bg.resize((max(1, int(bg.width * scale)), max(1, int(bg.height * scale))),
                   Image_.LANCZOS)
    img.paste(_cover_fit()(bg, img.width, img.height, Image_), (0, 0))

    count = min(len(posters), TEMPLATE_POSTER_COUNT)
    gap = int(img.width * 0.012)
    # 先按可用宽度反推单张宽度：宁可矮一点，也不让最外侧的海报被画布切掉
    usable = int(img.width * 0.86)
    pw = (usable - (count - 1) * gap) // max(1, count)
    ph = int(pw * 3 / 2)                # 2:3 比例
    ph = min(ph, int(img.height * 0.54))
    pw = int(ph * 2 / 3)
    x = (img.width - (count * pw + (count - 1) * gap)) // 2
    top = int(img.height * 0.06)
    fit = _cover_fit(0.5)
    for i in range(count):
        src = _open_source(Image_, posters[i])
        if src is None:
            x += pw + gap
            continue
        card = fit(src.convert("RGB"), pw, ph, Image_)
        # 侧边卡略微下沉 + 缩小，形成层次
        offset = int((count - 1 - abs(i - count // 2)) * img.height * 0.012)
        shade = Image_.new("RGBA", card.size, (0, 0, 0, 0))
        img.alpha_composite(shade, (x, top + offset))
        img.paste(card, (x, top + offset))
        x += pw + gap


def _template_filmstrip(img, posters, Image_, ImageFilter) -> None:
    """胶片带：横向三格（窄-宽-窄），每格一张不同的海报"""
    cell_h = int(img.height * 0.54)
    gap = int(img.width * 0.012)
    widths = [int(img.width * 0.20), int(img.width * 0.28), int(img.width * 0.20)]
    anchors = [0.35, 0.5, 0.65]
    x = (img.width - (sum(widths) + gap * 2)) // 2
    top = int(img.height * 0.10)
    for idx, w in enumerate(widths):
        src = _open_source(Image_, posters[idx % len(posters)])
        if src is None:
            x += w + gap
            continue
        img.paste(_cover_fit(anchors[idx])(src.convert("RGB"), w, cell_h, Image_),
                  (x, top))
        x += w + gap


def render_cover_bytes(
    db,
    library,
    template: str = DEFAULT_TEMPLATE,
    title: str = "",
    subtitle: str = "",
) -> Optional[bytes]:
    """按模板渲染封面并返回 WebP 字节；无法渲染时返回 None

    选图与渲染都在这里完成，调用方只需给 db + library（库名与内容类型
    从 library 自身取，避免两处传参对不上）。任何异常只记日志返回 None，
    调用方据此保留原封面。
    """
    pil = _pil()
    if pil is None:
        return None
    Image_, _draw, ImageFilter, _font_mod = pil
    if template not in TEMPLATES:
        template = DEFAULT_TEMPLATE

    need = 1 if template == "visual" else (
        TEMPLATE_POSTER_COUNT if template == "poster" else TEMPLATE_FILMSTRIP_COUNT)
    posters = pick_recent_posters(db, library, need)
    if not posters:
        logger.info("媒体库「%s」没有可用海报，跳过封面生成", getattr(library, "name", "?"))
        return None

    title_text = render_text(title, library.name, library.collection_type or "")
    sub_text = render_text(subtitle, library.name, library.collection_type or "")

    try:
        img = Image_.new("RGBA", (CANVAS_W, CANVAS_H), (12, 15, 24, 255))
        if template == "visual":
            _template_visual(img, posters, Image_, ImageFilter)
        elif template == "filmstrip":
            _template_filmstrip(img, posters, Image_, ImageFilter)
        else:
            _template_poster(img, posters, Image_, ImageFilter)
        _text_block(img, title_text, sub_text)
        out = io.BytesIO()
        img.convert("RGB").save(out, format="WEBP", quality=86, method=5)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - 封面是锦上添花，失败不该中断保存
        logger.warning("媒体库「%s」封面渲染失败", getattr(library, "name", "?"),
                       exc_info=True)
        return None


def render_cover_for_library(db, library) -> Optional[bytes]:
    """按库里已保存的模板/标题配置重新生成封面（扫描后或保存时调用）"""
    return render_cover_bytes(
        db, library,
        template=library.cover_template or DEFAULT_TEMPLATE,
        title=library.cover_title or "",
        subtitle=library.cover_subtitle or "",
    )