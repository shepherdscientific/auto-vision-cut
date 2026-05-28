"""Tests for the output validation and verification module."""

import json
import os
import tempfile
from unittest import mock

import pytest

from autovideo.validate import _get_video_info, _load_cut_list, run


class TestGetVideoInfo:
    def test_returns_video_metadata(self):
        probe_data = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "44100",
                },
            ],
            "format": {
                "duration": "30.5",
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            },
        }
        with mock.patch("autovideo.validate.ffmpeg.probe", return_value=probe_data), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=5242880
        ), mock.patch("autovideo.validate.os.path.exists", return_value=True):
            info = _get_video_info("/tmp/output.mp4")
            assert info["duration"] == 30.5
            assert info["video_codec"] == "h264"
            assert info["video_width"] == 1920
            assert info["video_height"] == 1080
            assert info["video_fps"] == "30/1"
            assert info["audio_codec"] == "aac"
            assert info["audio_channels"] == 2
            assert info["audio_sample_rate"] == "44100"
            assert info["file_size_bytes"] == 5242880
            assert info["file_size_mb"] == 5.0

    def test_handles_missing_video_stream(self):
        probe_data = {
            "streams": [
                {"codec_type": "audio", "codec_name": "aac", "channels": 2},
            ],
            "format": {"duration": "10.0", "format_name": "aac"},
        }
        with mock.patch("autovideo.validate.ffmpeg.probe", return_value=probe_data), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=1000
        ):
            info = _get_video_info("/tmp/output.mp4")
            assert info["duration"] == 10.0
            assert info["audio_codec"] == "aac"
            assert "video_codec" not in info

    def test_handles_missing_audio_stream(self):
        probe_data = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 480},
            ],
            "format": {"duration": "5.0", "format_name": "mp4"},
        }
        with mock.patch("autovideo.validate.ffmpeg.probe", return_value=probe_data), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=2000
        ):
            info = _get_video_info("/tmp/output.mp4")
            assert info["duration"] == 5.0
            assert info["video_codec"] == "h264"
            assert "audio_codec" not in info

    def test_handles_zero_duration(self):
        probe_data = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
            ],
            "format": {"duration": "0.0", "format_name": "mp4"},
        }
        with mock.patch("autovideo.validate.ffmpeg.probe", return_value=probe_data), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=500
        ):
            info = _get_video_info("/tmp/output.mp4")
            assert info["duration"] == 0.0

    def test_handles_missing_format_duration(self):
        probe_data = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
            ],
            "format": {"format_name": "mp4"},
        }
        with mock.patch("autovideo.validate.ffmpeg.probe", return_value=probe_data), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=3000
        ):
            info = _get_video_info("/tmp/output.mp4")
            assert info["duration"] == 0.0


class TestLoadCutList:
    def test_loads_valid_cut_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = {"keep": [{"start": 0, "end": 10}, {"start": 20, "end": 30}]}
            json.dump(data, f)
            path = f.name
        try:
            result = _load_cut_list(path)
            assert result == data
        finally:
            os.unlink(path)

    def test_loads_empty_cut_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"keep": []}, f)
            path = f.name
        try:
            result = _load_cut_list(path)
            assert result == {"keep": []}
        finally:
            os.unlink(path)

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            _load_cut_list("/nonexistent/path.json")

    def test_raises_on_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json")
            path = f.name
        try:
            with pytest.raises(json.JSONDecodeError):
                _load_cut_list(path)
        finally:
            os.unlink(path)


class TestRun:
    def _make_cut_list_file(self, keep_ranges):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"keep": keep_ranges}, f)
        f.close()
        return f.name

    def test_run_validates_successfully(self):
        cut_list_path = self._make_cut_list_file(
            [{"start": 0, "end": 10}, {"start": 20, "end": 30}]
        )

        probe_data = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                },
            ],
            "format": {"duration": "45.0", "format_name": "mp4"},
        }

        with mock.patch(
            "autovideo.validate.ffmpeg.probe", return_value=probe_data
        ), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=10485760
        ), mock.patch(
            "pathlib.Path.exists", return_value=True
        ):
            result = run("/tmp/output_master.mp4", cut_list_path)
            assert result["keep_range_count"] == 2
            assert result["video_info"]["duration"] == 45.0
            assert result["video_info"]["file_size_mb"] == 10.0
            assert result["video_info"]["video_codec"] == "h264"
            assert result["video_info"]["audio_codec"] == "aac"

        os.unlink(cut_list_path)

    def test_run_raises_on_missing_output_file(self):
        cut_list_path = self._make_cut_list_file(
            [{"start": 0, "end": 10}]
        )

        with mock.patch(
            "autovideo.validate.os.path.exists", return_value=False
        ), mock.patch(
            "pathlib.Path.exists", return_value=False
        ):
            with pytest.raises(FileNotFoundError, match="Output video not found"):
                run("/tmp/nonexistent.mp4", cut_list_path)

        os.unlink(cut_list_path)

    def test_run_raises_on_zero_duration(self):
        cut_list_path = self._make_cut_list_file(
            [{"start": 0, "end": 10}]
        )

        probe_data = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
            ],
            "format": {"duration": "0.0", "format_name": "mp4"},
        }

        with mock.patch(
            "autovideo.validate.ffmpeg.probe", return_value=probe_data
        ), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=100
        ), mock.patch(
            "pathlib.Path.exists", return_value=True
        ):
            with pytest.raises(ValueError, match="zero or negative duration"):
                run("/tmp/output_master.mp4", cut_list_path)

        os.unlink(cut_list_path)

    def test_run_with_empty_keep_ranges(self):
        cut_list_path = self._make_cut_list_file([])

        probe_data = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
            ],
            "format": {"duration": "30.0", "format_name": "mp4"},
        }

        with mock.patch(
            "autovideo.validate.ffmpeg.probe", return_value=probe_data
        ), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=5000
        ), mock.patch(
            "pathlib.Path.exists", return_value=True
        ):
            result = run("/tmp/output_master.mp4", cut_list_path)
            assert result["keep_range_count"] == 0

        os.unlink(cut_list_path)

    def test_run_logs_all_video_info_fields(self):
        cut_list_path = self._make_cut_list_file(
            [{"start": 5, "end": 15}]
        )

        probe_data = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "r_frame_rate": "60/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "opus",
                    "channels": 6,
                    "sample_rate": "48000",
                },
            ],
            "format": {"duration": "120.5", "format_name": "matroska,webm"},
        }

        with mock.patch(
            "autovideo.validate.ffmpeg.probe", return_value=probe_data
        ), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=524288000
        ), mock.patch(
            "pathlib.Path.exists", return_value=True
        ):
            result = run("/tmp/output_master.mp4", cut_list_path)
            info = result["video_info"]
            assert info["video_codec"] == "hevc"
            assert info["video_width"] == 3840
            assert info["video_height"] == 2160
            assert info["video_fps"] == "60/1"
            assert info["audio_codec"] == "opus"
            assert info["audio_channels"] == 6
            assert info["audio_sample_rate"] == "48000"
            assert info["file_size_mb"] == 500.0
            assert info["format_name"] == "matroska,webm"

        os.unlink(cut_list_path)

    def test_run_fails_on_nonexistent_cut_list(self):
        with mock.patch(
            "autovideo.validate.os.path.exists", return_value=True
        ), mock.patch(
            "autovideo.validate.ffmpeg.probe", return_value={
                "streams": [{"codec_type": "video", "codec_name": "h264"}],
                "format": {"duration": "10.0", "format_name": "mp4"},
            }
        ), mock.patch(
            "autovideo.validate.os.path.getsize", return_value=1000
        ):
            with pytest.raises(FileNotFoundError):
                run("/tmp/output_master.mp4", "/nonexistent/cut_list.json")
