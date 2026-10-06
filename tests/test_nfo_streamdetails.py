# -*- coding: utf-8 -*-
"""Tests for NFO streamdetails parsing (media info enrichment)."""
import sys
import os

# Import nfo directly without backend/__init__ (avoids dotenv dependency)
import importlib.util

_nfo_path = os.path.join(
    os.path.dirname(__file__), '..', 'backend', 'emby_server', 'nfo.py'
)
_nfo_path = os.path.abspath(_nfo_path)
spec = importlib.util.spec_from_file_location('nfo_test_mod', _nfo_path)
nfo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nfo)


class FakeItem:
    """Minimal MediaItem stand-in for apply_nfo testing."""
    def __init__(self):
        self.name = ""
        self.sort_name = ""
        self.original_title = ""
        self.aliases = ""
        self.production_year = None
        self.official_rating = ""
        self.genres = ""
        self.studios = ""
        self.tmdb_id = ""
        self.imdb_id = ""
        self.last_scraped_at = None
        self.metadata_source = ""
        self.overview = ""
        self.community_rating = None
        self.video_codec = ""
        self.audio_codec = ""
        self.width = 0
        self.height = 0
        self.duration_ticks = 0


def test_parse_streamdetails_full():
    nfo_text = """<movie>
  <title>Test Movie</title>
  <fileinfo>
    <streamdetails>
      <video>
        <codec>h264</codec>
        <width>1920</width>
        <height>1080</height>
        <durationinseconds>5400</durationinseconds>
      </video>
      <audio>
        <codec>aac</codec>
        <channels>2</channels>
      </audio>
    </streamdetails>
  </fileinfo>
</movie>"""
    data = nfo.parse_nfo(nfo_text)
    assert data is not None
    sd = data["streamdetails"]
    assert sd["video_codec"] == "h264"
    assert sd["video_width"] == 1920
    assert sd["video_height"] == 1080
    assert sd["video_duration"] == 5400
    assert sd["audio_codec"] == "aac"
    assert sd["audio_channels"] == 2


def test_parse_streamdetails_no_fileinfo():
    nfo_text = """<movie><title>No Stream Info</title></movie>"""
    data = nfo.parse_nfo(nfo_text)
    assert data is not None
    assert data["streamdetails"] == {}


def test_parse_streamdetails_micodec_fallback():
    # Some NFOs use <micodec> instead of <codec>
    nfo_text = """<movie>
  <title>Test</title>
  <fileinfo>
    <streamdetails>
      <video><micodec>hevc</micodec><width>3840</width><height>2160</height></video>
      <audio><micodec>truehd</micodec></audio>
    </streamdetails>
  </fileinfo>
</movie>"""
    data = nfo.parse_nfo(nfo_text)
    sd = data["streamdetails"]
    assert sd["video_codec"] == "hevc"
    assert sd["video_width"] == 3840
    assert sd["audio_codec"] == "truehd"


def test_parse_streamdetails_invalid_numbers():
    # Invalid width/height should be skipped, not crash
    nfo_text = """<movie>
  <title>Test</title>
  <fileinfo>
    <streamdetails>
      <video><codec>h264</codec><width>abc</width><height></height></video>
    </streamdetails>
  </fileinfo>
</movie>"""
    data = nfo.parse_nfo(nfo_text)
    sd = data["streamdetails"]
    assert sd["video_codec"] == "h264"
    assert "video_width" not in sd
    assert "video_height" not in sd


def test_apply_nfo_writes_streamdetails():
    nfo_text = """<movie>
  <title>Test Movie</title>
  <fileinfo>
    <streamdetails>
      <video><codec>h264</codec><width>1920</width><height>1080</height>
      <durationinseconds>3600</durationinseconds></video>
      <audio><codec>aac</codec></audio>
    </streamdetails>
  </fileinfo>
</movie>"""
    data = nfo.parse_nfo(nfo_text)
    item = FakeItem()
    nfo.apply_nfo(item, data, "movie")
    assert item.video_codec == "h264"
    assert item.width == 1920
    assert item.height == 1080
    assert item.audio_codec == "aac"
    # duration_ticks = seconds * 10_000_000 (100ns ticks)
    assert item.duration_ticks == 3600 * 10_000_000


def test_apply_nfo_no_streamdetails_keeps_existing():
    # When NFO has no streamdetails, existing values should be untouched
    nfo_text = """<movie><title>Test</title></movie>"""
    data = nfo.parse_nfo(nfo_text)
    item = FakeItem()
    item.video_codec = "existing"
    item.width = 1280
    nfo.apply_nfo(item, data, "movie")
    assert item.video_codec == "existing"
    assert item.width == 1280
