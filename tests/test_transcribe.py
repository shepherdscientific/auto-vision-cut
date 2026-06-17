"""Tests for the transcription module."""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from autovideo.transcribe import _build_segment, transcribe


class TestBuildSegment:
    def test_basic_segment_no_words(self):
        seg = {"start": 0.0, "end": 2.5, "text": " Hello world ", "avg_logprob": -0.2}
        result = _build_segment(seg, 0)
        assert result["id"] == 0
        assert result["start"] == 0.0
        assert result["end"] == 2.5
        assert result["text"] == "Hello world"
        assert result["confidence"] == -0.2
        assert "words" not in result

    def test_segment_with_word_timestamps(self):
        seg = {
            "start": 0.0,
            "end": 2.5,
            "text": "Hello world",
            "avg_logprob": -0.1,
            "words": [
                {"word": " Hello", "start": 0.0, "end": 0.8},
                {"word": " world", "start": 0.9, "end": 2.5},
            ],
        }
        result = _build_segment(seg, 1)
        assert result["id"] == 1
        assert len(result["words"]) == 2
        assert result["words"][0] == {"w": "Hello", "start": 0.0, "end": 0.8}
        assert result["words"][1] == {"w": "world", "start": 0.9, "end": 2.5}

    def test_segment_skips_empty_words(self):
        seg = {
            "start": 0.0,
            "end": 1.0,
            "text": "Hi",
            "words": [
                {"word": "", "start": 0.0, "end": 0.5},
            ],
        }
        result = _build_segment(seg, 0)
        assert "words" not in result

    def test_segment_confidence_default(self):
        seg = {"start": 0.0, "end": 1.0, "text": "Hi"}
        result = _build_segment(seg, 2)
        assert result["confidence"] == 0.0


class TestTranscribe:
    def test_transcribe_writes_transcript_json(self):
        mock_result = {
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "Hello world", "avg_logprob": -0.1},
                {"start": 3.5, "end": 6.0, "text": "This is a test.", "avg_logprob": -0.2},
            ],
            "language": "en",
        }

        with mock.patch("autovideo.transcribe.mlx_whisper") as w:
            with mock.patch("autovideo.transcribe.extract_audio") as ex:
                w.transcribe.return_value = mock_result

                with tempfile.TemporaryDirectory() as tmpdir:
                    Path(os.path.join(tmpdir, "test.mp4")).touch()
                    output_path = transcribe(tmpdir + "/test.mp4", tmpdir, model_path="tiny")

                    ex.assert_called_once()
                    assert output_path == os.path.join(tmpdir, "transcript.json")
                    assert os.path.isfile(output_path)

                    with open(output_path) as f:
                        data = json.load(f)

                    assert len(data["segments"]) == 2
                    assert data["segments"][0]["id"] == 0
                    assert data["segments"][0]["text"] == "Hello world"
                    assert data["segments"][1]["text"] == "This is a test."
                    assert data["language"] == "en"
                    assert data["model"] == "tiny"

    def test_transcribe_with_word_timestamps(self):
        mock_result = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.5,
                    "text": "Hello world",
                    "avg_logprob": -0.1,
                    "words": [
                        {"word": " Hello", "start": 0.0, "end": 0.8},
                        {"word": " world", "start": 0.9, "end": 2.5},
                    ],
                },
            ],
            "language": "en",
        }

        with mock.patch("autovideo.transcribe.mlx_whisper") as w:
            with mock.patch("autovideo.transcribe.extract_audio"):
                w.transcribe.return_value = mock_result

                with tempfile.TemporaryDirectory() as tmpdir:
                    Path(os.path.join(tmpdir, "test.mp4")).touch()
                    transcribe(os.path.join(tmpdir, "test.mp4"), tmpdir)

                w.transcribe.assert_called_once()
                _, kwargs = w.transcribe.call_args
                assert kwargs.get("word_timestamps") is True
                assert kwargs.get("path_or_hf_repo") == "mlx-community/whisper-tiny"

    def test_transcribe_removes_temp_audio(self):
        mock_result = {"segments": [], "language": "en"}

        with mock.patch("autovideo.transcribe.mlx_whisper") as w:
            with mock.patch("autovideo.transcribe.extract_audio") as ex:
                w.transcribe.return_value = mock_result

                with tempfile.TemporaryDirectory() as tmpdir:
                    Path(os.path.join(tmpdir, "test.mp4")).touch()
                    temp_audio = os.path.join(tmpdir, "temp_audio.aac")

                    def _fake_extract(v, o):
                        Path(o).parent.mkdir(parents=True, exist_ok=True)
                        Path(o).touch()
                        return o

                    ex.side_effect = _fake_extract
                    transcribe(os.path.join(tmpdir, "test.mp4"), tmpdir)
                    assert not os.path.isfile(temp_audio)

    def test_transcribe_handles_empty_segments(self):
        mock_result = {"segments": [], "language": "en"}

        with mock.patch("autovideo.transcribe.mlx_whisper") as w:
            with mock.patch("autovideo.transcribe.extract_audio"):
                w.transcribe.return_value = mock_result

                with tempfile.TemporaryDirectory() as tmpdir:
                    Path(os.path.join(tmpdir, "test.mp4")).touch()
                    output_path = transcribe(os.path.join(tmpdir, "test.mp4"), tmpdir)

                    with open(output_path) as f:
                        data = json.load(f)
                    assert data["segments"] == []
                    assert data["language"] == "en"
