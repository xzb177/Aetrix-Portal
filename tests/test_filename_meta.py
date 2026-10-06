"""filename_meta 单元测试：纯字符串解析，无外部依赖。"""
from backend.emby_server.filename_meta import parse_filename, resolution_to_wh


def test_resolution_1080p():
    assert parse_filename("Movie.2020.1080p.WEB-DL.x264.mkv")["resolution"] == "1080p"


def test_resolution_4k_normalized_to_2160p():
    assert parse_filename("Movie.2020.4K.BluRay.x265.mkv")["resolution"] == "2160p"
    assert parse_filename("Movie.2020.UHD.BluRay.mkv")["resolution"] == "2160p"


def test_resolution_720p_480p():
    assert parse_filename("drama ep03 720p HDTV aac.mp4")["resolution"] == "720p"
    assert parse_filename("old.show.480p.DVDRip.xvid.avi")["resolution"] == "480p"


def test_resolution_priority_highest_wins():
    # 文件名里同时出现多个时，取最高的
    assert parse_filename("Movie.1080p.2160p.WEB-DL.mkv")["resolution"] == "2160p"


def test_video_codec():
    assert parse_filename("Movie.2020.1080p.WEB-DL.x264.mkv")["video_codec"] == "H.264"
    assert parse_filename("Movie.2020.1080p.WEB-DL.h264.mkv")["video_codec"] == "H.264"
    assert parse_filename("Show.S01E01.2160p.BluRay.x265.10bit.mkv")["video_codec"] == "H.265"
    assert parse_filename("Show.S01E01.2160p.BluRay.HEVC.mkv")["video_codec"] == "H.265"


def test_audio_codec():
    assert parse_filename("Movie.1080p.BluRay.DTS.mkv")["audio_codec"] == "DTS"
    assert parse_filename("Movie.1080p.WEB-DL.AAC.mp4")["audio_codec"] == "AAC"
    assert parse_filename("Movie.1080p.BluRay.AC3.mkv")["audio_codec"] == "AC3"
    assert parse_filename("Movie.1080p.BluRay.FLAC.mkv")["audio_codec"] == "FLAC"


def test_source():
    assert parse_filename("Movie.2020.1080p.WEB-DL.x264.mkv")["source"] == "WEB-DL"
    assert parse_filename("Movie.2020.1080p.WEBDL.x264.mkv")["source"] == "WEB-DL"
    assert parse_filename("Movie.2020.2160p.BluRay.x265.mkv")["source"] == "BluRay"
    assert parse_filename("Movie.2020.2160p.Blu-ray.x265.mkv")["source"] == "BluRay"
    assert parse_filename("Show.S01E01.720p.HDTV.x264.mkv")["source"] == "HDTV"
    assert parse_filename("Show.S01E01.720p.WEBRip.x264.mkv")["source"] == "WEBRip"
    assert parse_filename("old.show.480p.DVDRip.avi")["source"] == "DVDRip"


def test_full_parse():
    meta = parse_filename("黑暗美食：墨西哥.Heavenly.Bites.Mexico.S01E01.1080p.WEB-DL.x264.AAC.mkv")
    assert meta == {
        "resolution": "1080p",
        "video_codec": "H.264",
        "audio_codec": "AAC",
        "source": "WEB-DL",
    }


def test_no_match_returns_empty():
    assert parse_filename("movie.mkv") == {}


def test_path_only_uses_basename():
    # 路径里的目录名不参与解析（目录名不可靠）
    assert parse_filename("/mnt/paul/video/movie.mkv") == {}


def test_resolution_to_wh():
    assert resolution_to_wh("1080p") == (1920, 1080)
    assert resolution_to_wh("720p") == (1280, 720)
    assert resolution_to_wh("480p") == (854, 480)
    assert resolution_to_wh("2160p") == (3840, 2160)
    assert resolution_to_wh(None) == (0, 0)
    assert resolution_to_wh("bogus") == (0, 0)
