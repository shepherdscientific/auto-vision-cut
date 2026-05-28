"""Tests for the automated assembly module."""

import json
import os
import tempfile
from unittest import mock

import pytest

from autovideo.assemble import _load_cut_list, run


class TestLoadCutList:
    def test_loads_valid_cut_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = {"keep": [{"start": 0, "end": 5}, {"start": 10, "end": 15}], "voiceover": "test"}
            json.dump(data, f)
            path = f.name
        try:
            result = _load_cut_list(path)
            assert result == [{"start": 0, "end": 5}, {"start": 10, "end": 15}]
        finally:
            os.unlink(path)

    def test_loads_empty_keep(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"keep": [], "voiceover": "test"}, f)
            path = f.name
        try:
            result = _load_cut_list(path)
            assert result == []
        finally:
            os.unlink(path)

    def test_loads_cut_list_without_keep_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"voiceover": "test"}, f)
            path = f.name
        try:
            result = _load_cut_list(path)
            assert result == []
        finally:
            os.unlink(path)

    def test_raises_on_non_list_keep(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"keep": "not_a_list"}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="must be a list"):
                _load_cut_list(path)
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
    def _make_cut_list_file(self, keep_ranges: list[dict]) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"keep": keep_ranges}, f)
        f.close()
        return f.name

    def _mock_clip_factory(self, duration: float = 30.0):
        mock_clip = mock.MagicMock()
        mock_clip.duration = duration

        mock_subclip = mock.MagicMock()
        mock_subclip.audio = mock.MagicMock()

        mock_final = mock.MagicMock()
        mock_final.audio = mock.MagicMock()

        def subclipped(start, end):
            sub = mock.MagicMock()
            sub.audio = mock.MagicMock()
            return sub

        mock_clip.subclipped = mock.MagicMock(side_effect=subclipped)

        return mock_clip, mock_final

    def test_run_basic_assembly(self):
        ranges = [{"start": 0, "end": 10}, {"start": 20, "end": 30}]
        cut_list_path = self._make_cut_list_file(ranges)

        with mock.patch("autovideo.assemble.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.assemble.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            run("test.mp4", cut_list_path, "/tmp/output.mp4", cleanup=False)

            mock_vfc.assert_called_once_with("test.mp4")
            assert mock_clip.subclipped.call_count == 2
            mock_concat.assert_called_once()
            mock_final.write_videofile.assert_called_once()
            mock_clip.close.assert_called_once()
            mock_final.close.assert_called_once()

        os.unlink(cut_list_path)

    def test_run_clamps_ranges_to_video_duration(self):
        cut_list_path = self._make_cut_list_file([{"start": 0, "end": 100}])

        with mock.patch("autovideo.assemble.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.assemble.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 15.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            run("test.mp4", cut_list_path, "/tmp/output.mp4", cleanup=False)

            call_args = mock_clip.subclipped.call_args
            assert call_args[0][0] == 0.0
            assert call_args[0][1] == 15.0

        os.unlink(cut_list_path)

    def test_run_skips_invalid_range_where_end_le_start(self):
        cut_list_path = self._make_cut_list_file([{"start": 10, "end": 5}])

        with mock.patch("autovideo.assemble.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.assemble.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            run("test.mp4", cut_list_path, "/tmp/output.mp4", cleanup=False)

            mock_clip.subclipped.assert_not_called()
            mock_concat.assert_not_called()
            mock_clip.close.assert_called_once()

        os.unlink(cut_list_path)

    def test_run_no_keep_ranges_skips_assembly(self):
        cut_list_path = self._make_cut_list_file([])

        with mock.patch("autovideo.assemble.VideoFileClip") as mock_vfc:
            run("test.mp4", cut_list_path, "/tmp/output.mp4", cleanup=False)
            mock_vfc.assert_not_called()

        os.unlink(cut_list_path)

    def test_run_negative_start_clamped_to_zero(self):
        cut_list_path = self._make_cut_list_file([{"start": -5, "end": 10}])

        with mock.patch("autovideo.assemble.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.assemble.concatenate_videoclips"
        ) as mock_concat:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            run("test.mp4", cut_list_path, "/tmp/output.mp4", cleanup=False)

            call_args = mock_clip.subclipped.call_args
            assert call_args[0][0] == 0.0

        os.unlink(cut_list_path)

    def test_run_creates_output_directory(self):
        cut_list_path = self._make_cut_list_file([{"start": 0, "end": 5}])

        with mock.patch("autovideo.assemble.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.assemble.concatenate_videoclips"
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
                run("test.mp4", cut_list_path, output_path, cleanup=False)

        os.unlink(cut_list_path)

    def test_run_cleanup_removes_temp_dir(self):
        cut_list_path = self._make_cut_list_file([{"start": 0, "end": 5}])

        with mock.patch("autovideo.assemble.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.assemble.concatenate_videoclips"
        ) as mock_concat, mock.patch("autovideo.assemble.shutil.rmtree") as mock_rmtree:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            with mock.patch("pathlib.Path.exists", return_value=True):
                run(
                    "test.mp4", cut_list_path, "/tmp/output.mp4",
                    temp_dir="output/temp", cleanup=True,
                )

            mock_rmtree.assert_called_once()

        os.unlink(cut_list_path)

    def test_run_cleanup_skips_when_dir_missing(self):
        cut_list_path = self._make_cut_list_file([{"start": 0, "end": 5}])

        with mock.patch("autovideo.assemble.VideoFileClip") as mock_vfc, mock.patch(
            "autovideo.assemble.concatenate_videoclips"
        ) as mock_concat, mock.patch("autovideo.assemble.shutil.rmtree") as mock_rmtree:
            mock_clip = mock.MagicMock()
            mock_clip.duration = 30.0
            mock_clip.subclipped = mock.MagicMock()
            mock_clip.subclipped.side_effect = lambda s, e: mock.MagicMock()
            mock_vfc.return_value = mock_clip

            mock_final = mock.MagicMock()
            mock_final.audio = mock.MagicMock()
            mock_concat.return_value = mock_final

            with mock.patch("pathlib.Path.exists", return_value=False):
                run(
                    "test.mp4", cut_list_path, "/tmp/output.mp4",
                    temp_dir="output/temp", cleanup=True,
                )

            mock_rmtree.assert_not_called()

        os.unlink(cut_list_path)
