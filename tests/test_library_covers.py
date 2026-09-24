"""媒体库封面上传校验：格式、声明类型、真实文件头与大小上限。"""
import pytest
from fastapi import HTTPException

from backend.emby_server.portal import _LIBRARY_COVER_MAX_BYTES, _validate_library_cover


def test_validate_cover_accepts_supported_images():
    assert _validate_library_cover("poster.jpg", "image/jpeg", b"\xff\xd8\xff\x00rest") == (
        ".jpg", "image/jpeg"
    )
    assert _validate_library_cover("poster.png", "image/png", b"\x89PNG\r\n\x1a\nrest") == (
        ".png", "image/png"
    )
    assert _validate_library_cover("poster.webp", "image/webp", b"RIFF1234WEBPrest") == (
        ".webp", "image/webp"
    )


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "status"),
    [
        ("poster.gif", "image/gif", b"GIF89a", 400),
        ("poster.jpg", "image/png", b"\xff\xd8\xff", 400),
        ("poster.jpg", "image/jpeg", b"not-an-image", 400),
        ("poster.webp", "image/webp", b"RIFF1234NOPE", 400),
        ("poster.png", "image/png", b"", 400),
    ],
)
def test_validate_cover_rejects_mismatched_or_invalid_files(filename, content_type, data, status):
    with pytest.raises(HTTPException) as exc:
        _validate_library_cover(filename, content_type, data)
    assert exc.value.status_code == status


def test_validate_cover_rejects_files_over_limit():
    with pytest.raises(HTTPException) as exc:
        _validate_library_cover(
            "poster.jpg", "image/jpeg", b"\xff\xd8\xff" + b"x" * _LIBRARY_COVER_MAX_BYTES
        )
    assert exc.value.status_code == 413
