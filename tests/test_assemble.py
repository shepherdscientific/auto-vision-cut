"""Tests for the automated assembly module."""
import json
import os
import tempfile
from unittest import mock

from autovideo.assemble import run
from autovideo.render import _moviepy_assemble


class TestMoviePyAssemble:
    def _make_cut_list_file(self, keep_ranges: list[dict]) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"keep": keep_ranges}, f)
        f.close()
        return f.name

    def test_moviepy_basic_assembly(self):
        ranges = [{"start": 0, "end": 10}, {"start": 20, "end": 30}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            _moviepy_assemble("test.mp4", ranges, "/tmp/output.mp4")

            mock_vfc.assert_called_once_with("test.mp4")
            assert mock_clip.subclipped.call_count == 2
            mock_concat.assert_called_once()
            mock_final.write_videofile.assert_called_once()
            mock_clip.close.assert_called_once()
            mock_final.close.assert_called_once()

    def test_moviepy_clamps_ranges_to_video_duration(self):
        ranges = [{"start": 0, "end": 100}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 15.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            _moviepy_assemble("test.mp4", ranges, "/tmp/output.mp4")

            call_args = mock_clip.subclipped.call_args
            assert call_args[0][0] == 0.0
            assert call_args[0][1] == 15.0

    def test_moviepy_skips_invalid_range_where_end_le_start(self):
        ranges = [{"start": 10, "end": 5}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            _moviepy_assemble("test.mp4", ranges, "/tmp/output.mp4")

            mock_clip.subclipped.assert_not_called()
            mock_concat.assert_not_called()
            mock_clip.close.assert_called_once()

    def test_moviepy_no_keep_ranges_skips_assembly(self):
        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc:
            _moviepy_assemble("test.mp4", [], "/tmp/output.mp4")
            mock_vfc.assert_not_called()

    def test_moviepy_negative_start_clamped_to_zero(self):
        ranges = [{"start": -5, "end": 10}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            _moviepy_assemble("test.mp4", ranges, "/tmp/output.mp4")

            call_args = mock_clip.subclipped.call_args
            assert call_args[0][0] == 0.0

    def test_moviepy_creates_output_directory(self):
        ranges = [{"start": 0, "end": 5}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "subdir", "output.mp4")
                _moviepy_assemble("test.mp4", ranges, output_path)

    def test_moviepy_cleanup_removes_temp_dir(self):
        ranges = [{"start": 0, "end": 5}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat, mock.patch("autovideo.render.shutil.rmtree") as mock_rmtree:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            with mock.patch("pathlib.Path.exists", return_value=True):
                _moviepy_assemble(
                    "test.mp4", ranges, "/tmp/output.mp4",
                    temp_dir="output/temp", cleanup=True,
                )

            mock_rmtree.assert_called_once()

    def test_moviepy_cleanup_skips_when_dir_missing(self):
        ranges = [{"start": 0, "end": 5}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat, mock.patch("autovideo.render.shutil.rmtree") as mock_rmtree:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            with mock.patch("pathlib.Path.exists", return_value=False):
                _moviepy_assemble(
                    "test.mp4", ranges, "/tmp/output.mp4",
                    temp_dir="output/temp", cleanup=True,
                )

            mock_rmtree.assert_not_called()

    def test_moviepy_with_voiceover_applies_overlay(self):
        ranges = [{"start": 0, "end": 10}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat, mock.patch(
            "autovideo.render.AudioFileClip"
        ) as mock_afc, mock.patch(
            "autovideo.render.CompositeAudioClip"
        ) as mock_cac:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            final_audio = mock.MagicMock()
            mock_final = mock.MagicMock()
            mock_final.audio = final_audio
            mock_final.duration = 10.0
            mock_concat.return_value = mock_final

            mock_vo = mock.MagicMock()
            mock_vo.duration = 5.0
            mock_vo.with_volume_scaled.return_value = mock_vo
            mock_afc.return_value = mock_vo

            mock_mixed = mock.MagicMock()
            mock_cac.return_value = mock_mixed

            _moviepy_assemble(
                "test.mp4", ranges, "/tmp/output.mp4",
                cleanup=False, voiceover_path="voiceover.aac",
            )

            mock_afc.assert_called_once_with("voiceover.aac")
            mock_vo.with_volume_scaled.assert_called_once_with(0.7)
            mock_cac.assert_called_once()
            mock_final.with_audio.assert_called_once_with(mock_mixed)

    def test_moviepy_with_voiceover_clips_to_video_duration(self):
        ranges = [{"start": 0, "end": 10}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat, mock.patch(
            "autovideo.render.AudioFileClip"
        ) as mock_afc, mock.patch(
            "autovideo.render.CompositeAudioClip"
        ):
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_final.duration = 10.0
            mock_concat.return_value = mock_final

            mock_vo = mock.MagicMock()
            mock_vo.duration = 60.0
            mock_vo.with_volume_scaled.return_value = mock_vo
            mock_afc.return_value = mock_vo

            _moviepy_assemble(
                "test.mp4", ranges, "/tmp/output.mp4",
                cleanup=False, voiceover_path="voiceover.aac",
            )

            mock_vo.subclipped.assert_called_once_with(0, 10.0)

    def test_moviepy_voiceover_failure_is_handled_gracefully(self):
        ranges = [{"start": 0, "end": 10}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat, mock.patch(
            "autovideo.render.AudioFileClip"
        ) as mock_afc:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_final.duration = 10.0
            mock_concat.return_value = mock_final

            mock_afc.side_effect = RuntimeError("TTS audio file missing")

            _moviepy_assemble(
                "test.mp4", ranges, "/tmp/output.mp4",
                cleanup=False, voiceover_path="missing.aac",
            )

            mock_final.write_videofile.assert_called_once()

    def test_moviepy_with_voiceover_handles_missing_video_audio(self):
        ranges = [{"start": 0, "end": 10}]

        with mock.patch("autovideo.render.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.render.concatenate_videoclips"
        ) as mock_concat, mock.patch(
            "autovideo.render.AudioFileClip"
        ) as mock_afc, mock.patch(
            "autovideo.render.CompositeAudioClip"
        ):
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = None
            mock_final.duration = 10.0
            mock_concat.return_value = mock_final

            mock_vo = mock.MagicMock()
            mock_vo.duration = 5.0
            mock_vo.with_volume_scaled.return_value = mock_vo
            mock_afc.return_value = mock_vo

            _moviepy_assemble(
                "test.mp4", ranges, "/tmp/output.mp4",
                cleanup=False, voiceover_path="voiceover.aac",
            )

            mock_final.with_audio.assert_called_once_with(mock_vo)


class TestAssembleRun:
    def _make_cut_list_file(self, keep_ranges: list[dict]) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"keep": keep_ranges}, f)
        f.close()
        return f.name

    def test_run_delegates_to_render(self):
        cut_list_path = self._make_cut_list_file([{"start": 0, "end": 10}])

        with mock.patch("autovideo.assemble.render_run") as mock_render:
            run("test.mp4", cut_list_path, "/tmp/output.mp4", cleanup=False)
            mock_render.assert_called_once_with(
                video_path="test.mp4",
                cut_list_path=cut_list_path,
                output_path="/tmp/output.mp4",
                temp_dir="output/temp",
                cleanup=False,
                voiceover_path=None,
            )

        os.unlink(cut_list_path)
