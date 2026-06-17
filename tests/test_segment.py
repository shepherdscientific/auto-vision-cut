"""Tests for the transcript segmentation module."""

import json
import os
import tempfile

from autovideo.segment import (
    _detect_silences,
    _is_sentence_boundary,
    segment_transcript,
)


class TestIsSentenceBoundary:
    def test_sentence_ends_with_period(self):
        assert _is_sentence_boundary("Hello world.")

    def test_sentence_ends_with_question_mark(self):
        assert _is_sentence_boundary("Is this working?")

    def test_sentence_ends_with_exclamation(self):
        assert _is_sentence_boundary("Wow!")

    def test_sentence_ends_with_ellipsis(self):
        assert _is_sentence_boundary("So then I…")

    def test_sentence_mid_clause_no_end(self):
        assert not _is_sentence_boundary("Hello world")

    def test_sentence_with_trailing_quote(self):
        assert _is_sentence_boundary('He said "yes."')

    def test_empty_string(self):
        assert not _is_sentence_boundary("")

    def test_whitespace_only(self):
        assert not _is_sentence_boundary("   ")


class TestDetectSilences:
    def test_no_silences_below_threshold(self):
        segs = [
            {"start": 0.0, "end": 2.0},
            {"start": 2.3, "end": 4.0},
        ]
        result = _detect_silences(segs, pause_threshold=0.5)
        assert len(result) == 0

    def test_silence_detected_above_threshold(self):
        segs = [
            {"start": 0.0, "end": 2.0},
            {"start": 3.0, "end": 5.0},
        ]
        result = _detect_silences(segs, pause_threshold=0.5)
        assert len(result) == 1
        assert result[0]["start"] == 2.0
        assert result[0]["end"] == 3.0
        assert result[0]["duration"] == 1.0

    def test_single_segment_no_silences(self):
        segs = [{"start": 0.0, "end": 10.0}]
        result = _detect_silences(segs)
        assert result == []

    def test_multiple_silences(self):
        segs = [
            {"start": 0.0, "end": 1.0},
            {"start": 3.0, "end": 4.0},
            {"start": 4.5, "end": 5.5},
            {"start": 8.0, "end": 9.0},
        ]
        result = _detect_silences(segs, pause_threshold=0.3)
        assert len(result) == 3
        assert result[0]["duration"] == 2.0
        assert result[1]["duration"] == 0.5
        assert result[2]["duration"] == 2.5


class TestSegmentTranscript:
    def _write_transcript(self, directory: str, segments: list[dict]) -> str:
        path = os.path.join(directory, "transcript.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"segments": segments, "language": "en"}, f, indent=2)
        return path

    def test_empty_transcript(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [])
            output = segment_transcript(transcript_path, tmpdir)
            with open(output) as f:
                data = json.load(f)
            assert data["segments"] == []
            assert data["silences"] == []

    def test_merges_adjacent_segments_below_pause_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 0.0, "end": 1.5, "text": "Hello", "avg_logprob": -0.1},
                {"start": 1.6, "end": 3.0, "text": "world", "avg_logprob": -0.2},
            ])
            output = segment_transcript(transcript_path, tmpdir, pause_threshold=0.5)
            with open(output) as f:
                data = json.load(f)
            assert len(data["segments"]) == 1
            assert data["segments"][0]["text"] == "Hello world"
            assert data["segments"][0]["start"] == 0.0
            assert data["segments"][0]["end"] == 3.0

    def test_splits_on_sentence_boundary_with_sufficient_gap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 0.0, "end": 2.0, "text": "First sentence.", "avg_logprob": -0.1},
                {"start": 3.0, "end": 5.0, "text": "Second sentence.", "avg_logprob": -0.2},
            ])
            output = segment_transcript(transcript_path, tmpdir, pause_threshold=0.7)
            with open(output) as f:
                data = json.load(f)
            assert len(data["segments"]) == 2
            assert data["segments"][0]["text"] == "First sentence."
            assert data["segments"][1]["text"] == "Second sentence."

    def test_does_not_split_sentence_without_end_punctuation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 0.0, "end": 2.0, "text": "Hello world", "avg_logprob": -0.1},
                {"start": 3.0, "end": 5.0, "text": "this is a test", "avg_logprob": -0.2},
            ])
            output = segment_transcript(transcript_path, tmpdir, pause_threshold=0.7)
            with open(output) as f:
                data = json.load(f)
            assert len(data["segments"]) == 2

    def test_detects_silences_between_utterances(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 0.0, "end": 2.0, "text": "Part one.", "avg_logprob": -0.1},
                {"start": 5.0, "end": 7.0, "text": "Part two.", "avg_logprob": -0.2},
            ])
            output = segment_transcript(transcript_path, tmpdir, pause_threshold=0.5)
            with open(output) as f:
                data = json.load(f)
            assert len(data["silences"]) == 1
            assert data["silences"][0]["tag"] == "dead_air"
            assert data["silences"][0]["duration"] == 3.0

    def test_stats_are_calculated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 0.0, "end": 2.0, "text": "Hello.", "avg_logprob": -0.1},
                {"start": 3.0, "end": 4.0, "text": "World.", "avg_logprob": -0.2},
            ])
            output = segment_transcript(transcript_path, tmpdir, pause_threshold=0.5)
            with open(output) as f:
                data = json.load(f)
            stats = data["stats"]
            assert stats["total_segments"] == 2
            assert stats["total_silences"] == 1
            assert stats["total_duration"] == 4.0
            assert stats["speech_duration"] == 3.0
            assert stats["pause_threshold"] == 0.5

    def test_ids_are_sequential_after_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 0.0, "end": 1.0, "text": "Hi.", "avg_logprob": -0.1},
                {"start": 1.2, "end": 2.0, "text": "there", "avg_logprob": -0.2},
                {"start": 3.0, "end": 4.0, "text": "Bye.", "avg_logprob": -0.3},
            ])
            output = segment_transcript(transcript_path, tmpdir, pause_threshold=0.5)
            with open(output) as f:
                data = json.load(f)
            for i, seg in enumerate(data["segments"]):
                assert seg["id"] == i

    def test_each_segment_has_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 0.0, "end": 3.0, "text": "Hello world.", "avg_logprob": -0.1},
            ])
            output = segment_transcript(transcript_path, tmpdir)
            with open(output) as f:
                data = json.load(f)
            assert data["segments"][0]["duration"] == 3.0

    def test_preserves_chronological_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 5.0, "end": 7.0, "text": "Later.", "avg_logprob": -0.2},
                {"start": 10.0, "end": 12.0, "text": "Even later.", "avg_logprob": -0.3},
                {"start": 0.0, "end": 2.0, "text": "Earlier.", "avg_logprob": -0.1},
            ])
            output = segment_transcript(transcript_path, tmpdir, pause_threshold=0.5)
            with open(output) as f:
                data = json.load(f)
            starts = [s["start"] for s in data["segments"]]
            assert starts == sorted(starts)
            assert starts == [0.0, 5.0, 10.0]

    def test_skips_empty_text_segments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [
                {"start": 0.0, "end": 1.0, "text": "Keep me.", "avg_logprob": -0.1},
                {"start": 1.5, "end": 2.0, "text": "   ", "avg_logprob": -0.5},
                {"start": 2.0, "end": 3.0, "text": "Keep too.", "avg_logprob": -0.2},
            ])
            output = segment_transcript(transcript_path, tmpdir, pause_threshold=0.5)
            with open(output) as f:
                data = json.load(f)
            assert len(data["segments"]) == 2
            assert data["segments"][0]["text"] == "Keep me."
            assert data["segments"][1]["text"] == "Keep too."

    def test_output_filename_is_segments_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [])
            output = segment_transcript(transcript_path, tmpdir)
            assert os.path.basename(output) == "segments.json"

    def test_output_in_specified_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = self._write_transcript(tmpdir, [])
            sub = os.path.join(tmpdir, "sub")
            os.makedirs(sub)
            output = segment_transcript(transcript_path, sub)
            assert output == os.path.join(sub, "segments.json")
