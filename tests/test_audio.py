"""Tests for the audio extraction and processing module."""

import os
import tempfile
from unittest import mock

from autovideo.audio import extract_audio, mix_voiceover


class TestExtractAudio:
    def test_extract_creates_output_directory(self):
        with mock.patch("autovideo.audio.ffmpeg") as mock_ffmpeg:
            mock_input = mock.MagicMock()
            mock_output = mock.MagicMock()
            mock_ffmpeg.input.return_value = mock_input
            mock_input.output.return_value = mock_output

            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "audio.aac")
                result = extract_audio("test.mp4", output_path)
                assert result == output_path
                assert os.path.isdir(tmpdir)

    def test_extract_calls_ffmpeg_with_correct_params(self):
        with mock.patch("autovideo.audio.ffmpeg") as mock_ffmpeg:
            mock_input = mock.MagicMock()
            mock_output = mock.MagicMock()
            mock_ffmpeg.input.return_value = mock_input
            mock_input.output.return_value = mock_output

            output_path = "/tmp/test/audio.aac"
            extract_audio("test.mp4", output_path)

            mock_ffmpeg.input.assert_called_once_with("test.mp4")
            mock_input.output.assert_called_once()
            call_kwargs = mock_input.output.call_args[1]
            assert call_kwargs["acodec"] == "aac"
            assert call_kwargs["vn"] is None


class TestMixVoiceover:
    def test_mix_creates_output_directory(self):
        with mock.patch("autovideo.audio.ffmpeg") as mock_ffmpeg:
            mock_video = mock.MagicMock()
            mock_voice = mock.MagicMock()
            mock_ffmpeg.input.side_effect = [mock_video, mock_voice]

            mock_filtered = mock.MagicMock()
            mock_ffmpeg.filter.return_value = mock_filtered

            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "mixed.aac")
                result = mix_voiceover("video.aac", "voice.mp3", output_path)
                assert result == output_path
                assert os.path.isdir(tmpdir)

    def test_mix_default_voiceover_volume(self):
        with mock.patch("autovideo.audio.ffmpeg") as mock_ffmpeg:
            mock_video = mock.MagicMock()
            mock_voice = mock.MagicMock()
            mock_ffmpeg.input.side_effect = [mock_video, mock_voice]

            mock_filtered = mock.MagicMock()
            mock_ffmpeg.filter.return_value = mock_filtered

            mix_voiceover("video.aac", "voice.mp3", "/tmp/mixed.aac")

            filter_kwargs = mock_ffmpeg.filter.call_args[1]
            assert filter_kwargs["weights"] == "1 0.7"

    def test_mix_custom_voiceover_volume(self):
        with mock.patch("autovideo.audio.ffmpeg") as mock_ffmpeg:
            mock_video = mock.MagicMock()
            mock_voice = mock.MagicMock()
            mock_ffmpeg.input.side_effect = [mock_video, mock_voice]

            mock_filtered = mock.MagicMock()
            mock_ffmpeg.filter.return_value = mock_filtered

            mix_voiceover("video.aac", "voice.mp3", "/tmp/mixed.aac", voiceover_volume=0.5)

            filter_kwargs = mock_ffmpeg.filter.call_args[1]
            assert filter_kwargs["weights"] == "1 0.5"

    def test_mix_uses_amix_filter(self):
        with mock.patch("autovideo.audio.ffmpeg") as mock_ffmpeg:
            mock_video = mock.MagicMock()
            mock_voice = mock.MagicMock()
            mock_ffmpeg.input.side_effect = [mock_video, mock_voice]

            mock_filtered = mock.MagicMock()
            mock_ffmpeg.filter.return_value = mock_filtered

            mix_voiceover("video.aac", "voice.mp3", "/tmp/mixed.aac")

            filter_args = mock_ffmpeg.filter.call_args[0]
            assert filter_args[1] == "amix"
