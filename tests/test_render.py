"""Tests for the frame-accurate render module."""
import json
import os
import tempfile
from unittest import mock

from autovideo.render import (
    _build_concat_file,
    _moviepy_assemble,
    _run_ffmpeg_concat,
    run,
)


class TestBuildConcatFile:
    def _make_concat_path(self) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.close()
        return f.name

    def test_builds_concat_entries(self):
        concat_path = self._make_concat_path()
        try:
            count = _build_concat_file(
                video_path="/videos/test.mp4",
                keep_ranges=[{"start": 0, "end": 10}, {"start": 20, "end": 30}],
                duration=60.0,
                concat_path=concat_path,
            )
            assert count == 2
            with open(concat_path) as f:
                content = f.read()
            assert "file '/videos/test.mp4'" in content
            assert "inpoint 0" in content
            assert "outpoint 10" in content
            assert "inpoint 20" in content
            assert "outpoint 30" in content
        finally:
            os.unlink(concat_path)

    def test_skips_invalid_ranges(self):
        concat_path = self._make_concat_path()
        try:
            count = _build_concat_file(
                video_path="/videos/test.mp4",
                keep_ranges=[{"start": 10, "end": 5}, {"start": 0, "end": 10}],
                duration=60.0,
                concat_path=concat_path,
            )
            assert count == 1
        finally:
            os.unlink(concat_path)

    def test_clamps_to_video_duration(self):
        concat_path = self._make_concat_path()
        try:
            count = _build_concat_file(
                video_path="/videos/test.mp4",
                keep_ranges=[{"start": 0, "end": 100}],
                duration=30.0,
                concat_path=concat_path,
            )
            assert count == 1
            with open(concat_path) as f:
                content = f.read()
            assert "outpoint 30" in content
        finally:
            os.unlink(concat_path)

    def test_clamps_negative_start_to_zero(self):
        concat_path = self._make_concat_path()
        try:
            count = _build_concat_file(
                video_path="/videos/test.mp4",
                keep_ranges=[{"start": -5, "end": 10}],
                duration=60.0,
                concat_path=concat_path,
            )
            assert count == 1
            with open(concat_path) as f:
                content = f.read()
            assert "inpoint 0" in content
        finally:
            os.unlink(concat_path)

    def test_returns_zero_for_no_valid_segments(self):
        concat_path = self._make_concat_path()
        try:
            count = _build_concat_file(
                video_path="/videos/test.mp4",
                keep_ranges=[],
                duration=60.0,
                concat_path=concat_path,
            )
            assert count == 0
        finally:
            os.unlink(concat_path)


class TestRunFFmpegConcat:
    def test_creates_output_directory(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "nested", "output.mp4")
                _run_ffmpeg_concat(
                    concat_path="/tmp/concat.txt",
                    output_path=output_path,
                )
                assert os.path.isdir(os.path.dirname(output_path))

    def test_invokes_ffmpeg_with_correct_args(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            _run_ffmpeg_concat(
                concat_path="/tmp/concat.txt",
                output_path="/tmp/output.mp4",
            )
            call_args = mock_run.call_args[0][0]
            assert "ffmpeg" in call_args[0]
            assert "-f" in call_args
            assert "concat" in call_args
            assert "-i" in call_args
            assert "/tmp/concat.txt" in call_args
            assert "/tmp/output.mp4" in call_args
            assert "-c:v" in call_args
            assert "libx264" in call_args
            assert "-c:a" in call_args
            assert "aac" in call_args

    def test_raises_on_ffmpeg_failure(self):
        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = "error output"
            mock_result.stderr = "ffmpeg failed"
            mock_run.return_value = mock_result

            import pytest
            with pytest.raises(RuntimeError, match="ffmpeg concat failed"):
                _run_ffmpeg_concat(
                    concat_path="/tmp/concat.txt",
                    output_path="/tmp/output.mp4",
                )


class TestMoviePyAssemble:
    def test_preserves_audio_in_sync(self):
        ranges = [{"start": 0, "end": 10}]
        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.audio = mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            _moviepy_assemble("test.mp4", ranges, "/tmp/output.mp4")

            mock_clip.subclipped.assert_called_once_with(0.0, 10.0)
            mock_concat.assert_called_once()
            mock_final.write_videofile.assert_called_once_with(
                "/tmp/output.mp4", codec="libx264", audio_codec="aac", logger=None
            )

    def test_handles_many_segments(self):
        ranges = [{"start": i, "end": i + 1} for i in range(100)]
        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 200.0
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            _moviepy_assemble("test.mp4", ranges, "/tmp/output.mp4")
            assert mock_clip.subclipped.call_count == 100
            mock_concat.assert_called_once()

    def test_handles_missing_audio_track(self):
        ranges = [{"start": 0, "end": 10}]
        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.audio = None
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = None
            mock_concat.return_value = mock_final

            _moviepy_assemble("test.mp4", ranges, "/tmp/output.mp4")
            mock_final.write_videofile.assert_called_once()

    def test_run_delegates_to_moviepy_when_voiceover_provided(self):
        cut_list = {"keep": [{"start": 0, "end": 10}]}
        cut_list_path = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False).name
        with open(cut_list_path, "w") as f:
            json.dump(cut_list, f)
        try:
            with mock.patch("autovideo.render._moviepy_assemble") as mock_mp:
                run(
                    video_path="test.mp4",
                    cut_list_path=cut_list_path,
                    output_path="/tmp/output.mp4",
                    voiceover_path="voiceover.aac",
                )
                mock_mp.assert_called_once()
        finally:
            os.unlink(cut_list_path)

    def test_run_skips_when_no_keep_ranges(self):
        cut_list = {"keep": []}
        cut_list_path = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False).name
        with open(cut_list_path, "w") as f:
            json.dump(cut_list, f)
        try:
            with mock.patch("autovideo.render._run_ffmpeg_concat") as mock_ffmpeg:
                run(
                    video_path="test.mp4",
                    cut_list_path=cut_list_path,
                    output_path="/tmp/output.mp4",
                )
                mock_ffmpeg.assert_not_called()
        finally:
            os.unlink(cut_list_path)

    def test_ffmpeg_fallback_to_moviepy(self):
        cut_list = {"keep": [{"start": 0, "end": 10}]}
        cut_list_path = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False).name
        with open(cut_list_path, "w") as f:
            json.dump(cut_list, f)
        try:
            with mock.patch("autovideo.render.ffmpeg.probe") as mock_probe, mock.patch(
                "autovideo.render._run_ffmpeg_concat"
            ) as mock_ffmpeg, mock.patch(
                "autovideo.render._moviepy_assemble"
            ) as mock_mp:
                mock_probe.return_value = {"format": {"duration": "60.0"}}
                mock_ffmpeg.side_effect = RuntimeError("ffmpeg crashed")
                run(
                    video_path="test.mp4",
                    cut_list_path=cut_list_path,
                    output_path="/tmp/output.mp4",
                )
                mock_ffmpeg.assert_called_once()
                mock_mp.assert_called_once()
        finally:
            os.unlink(cut_list_path)

    def test_raises_on_invalid_cut_list(self):
        cut_list = {"keep": "not_a_list"}
        cut_list_path = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False).name
        with open(cut_list_path, "w") as f:
            json.dump(cut_list, f)
        try:
            import pytest
            with pytest.raises(ValueError, match="must be a list"):
                run(
                    video_path="test.mp4",
                    cut_list_path=cut_list_path,
                    output_path="/tmp/output.mp4",
                )
        finally:
            os.unlink(cut_list_path)
