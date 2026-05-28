"""Tests for the vision analysis module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from autovideo.analyze import _generate_frame, _resolve_frames, run


def test_resolve_frames_from_directory(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "000000.jpg").write_text("")
    (frames_dir / "000003.jpg").write_text("")
    (frames_dir / "000006.jpg").write_text("")
    (frames_dir / "notes.txt").write_text("")

    result = _resolve_frames(str(frames_dir))
    assert len(result) == 3
    assert all(p.suffix == ".jpg" for p in result)
    names = [p.name for p in result]
    assert names == ["000000.jpg", "000003.jpg", "000006.jpg"]


def test_resolve_frames_from_list(tmp_path: Path) -> None:
    frames = [
        tmp_path / "000000.jpg",
        tmp_path / "000003.jpg",
    ]
    for f in frames:
        f.write_text("")

    result = _resolve_frames(frames)
    assert len(result) == 2
    assert result == sorted(frames)


def test_resolve_frames_missing_directory() -> None:
    try:
        _resolve_frames("/nonexistent/dir/path")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_resolve_frames_empty_directory(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result = _resolve_frames(str(empty_dir))
    assert result == []


class FakeGenerationResult:
    def __init__(self, text: str) -> None:
        self.text = text


def test_run_returns_events_for_frames(tmp_path: Path) -> None:
    frame1 = tmp_path / "000003.jpg"
    frame1.write_text("")
    frame2 = tmp_path / "000006.jpg"
    frame2.write_text("")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    fake_result = FakeGenerationResult(
        '{"active": true, "description": "User is typing code in an IDE"}'
    )

    with patch("autovideo.analyze.load", return_value=(MagicMock(), MagicMock())):
        with patch("autovideo.analyze.generate", return_value=fake_result):
            events = run(
                frames=[frame1, frame2],
                model_path="test-model",
                batch_size=2,
                output_dir=str(output_dir),
            )

    assert len(events) == 2
    assert events[0]["timestamp"] == 3
    assert events[0]["active"] is True
    assert "typing code" in events[0]["description"]
    assert events[0]["frame"] == "000003.jpg"

    assert events[1]["timestamp"] == 6
    assert events[1]["frame"] == "000006.jpg"

    log_path = output_dir / "vision_log.json"
    assert log_path.exists()
    saved = json.loads(log_path.read_text())
    assert len(saved) == 2


def test_run_handles_non_json_output(tmp_path: Path) -> None:
    frame = tmp_path / "000003.jpg"
    frame.write_text("")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    fake_result = FakeGenerationResult("The user appears to be coding")

    with patch("autovideo.analyze.load", return_value=(MagicMock(), MagicMock())):
        with patch("autovideo.analyze.generate", return_value=fake_result):
            events = run(
                frames=[frame],
                model_path="test-model",
                output_dir=str(output_dir),
            )

    assert len(events) == 1
    assert events[0]["active"] is True
    assert events[0]["description"] == "The user appears to be coding"


def test_run_handles_generate_error(tmp_path: Path) -> None:
    frame = tmp_path / "000003.jpg"
    frame.write_text("")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("autovideo.analyze.load", return_value=(MagicMock(), MagicMock())):
        with patch("autovideo.analyze.generate", side_effect=RuntimeError("GPU OOM")):
            events = run(
                frames=[frame],
                model_path="test-model",
                output_dir=str(output_dir),
            )

    assert len(events) == 1
    assert events[0]["error"] == "GPU OOM"
    assert "ERROR" in events[0]["description"]


def test_run_empty_frames(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("autovideo.analyze.load") as mock_load:
        events = run(
            frames=[],
            model_path="test-model",
            output_dir=str(output_dir),
        )
        mock_load.assert_not_called()

    assert events == []


def test_run_saves_vision_log(tmp_path: Path) -> None:
    frame = tmp_path / "000003.jpg"
    frame.write_text("")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    fake_result = FakeGenerationResult(
        '{"active": false, "description": "User is staring at the screen"}'
    )

    with patch("autovideo.analyze.load", return_value=(MagicMock(), MagicMock())):
        with patch("autovideo.analyze.generate", return_value=fake_result):
            run(
                frames=[frame],
                model_path="test-model",
                output_dir=str(output_dir),
            )

    log_path = output_dir / "vision_log.json"
    assert log_path.exists()
    saved = json.loads(log_path.read_text())
    assert saved[0]["active"] is False
    assert "staring" in saved[0]["description"]


class FakeRetryModel:
    pass


def test_generate_frame_retries_on_failure() -> None:
    call_count = 0

    def fake_generate(model, processor, prompt, image=None, max_tokens=256):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("transient VLM error")
        return type("FakeResult", (), {"text": '{"active": true, "description": "ok"}'})()

    with patch("autovideo.analyze.generate", side_effect=fake_generate):
        with patch("time.sleep", return_value=None):
            result = _generate_frame(
                model=FakeRetryModel(),
                processor=Mock(),
                prompt="test prompt",
                frame_path="/tmp/test.jpg",
            )

    assert call_count == 3
    assert result.text == '{"active": true, "description": "ok"}'


def test_generate_frame_raises_after_exhausting_retries() -> None:
    with patch("autovideo.analyze.generate", side_effect=RuntimeError("VLM OOM")):
        with patch("time.sleep", return_value=None):
            try:
                _generate_frame(
                    model=FakeRetryModel(),
                    processor=Mock(),
                    prompt="test prompt",
                    frame_path="/tmp/test.jpg",
                )
                assert False, "Should have raised RuntimeError"
            except RuntimeError as exc:
                assert "VLM OOM" in str(exc)


def test_run_handles_generate_errors_with_error_records(tmp_path: Path) -> None:
    frame1 = tmp_path / "000003.jpg"
    frame1.write_text("")
    frame2 = tmp_path / "000006.jpg"
    frame2.write_text("")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    call_count = 0
    frame2_count = 0

    def fake_generate(model, processor, prompt, image=None, max_tokens=256):
        nonlocal call_count, frame2_count
        call_count += 1
        if "000003" in str(image):
            raise RuntimeError("GPU OOM for frame 3")
        frame2_count += 1
        return type("FakeResult", (), {"text": '{"active": false, "description": "idle"}'})()

    with patch("autovideo.analyze.load", return_value=(Mock(), Mock())):
        with patch("autovideo.analyze.generate", side_effect=fake_generate):
            with patch("time.sleep", return_value=None):
                events = run(
                    frames=[frame1, frame2],
                    model_path="test-model",
                    batch_size=2,
                    output_dir=str(output_dir),
                )

    assert len(events) == 2
    assert events[0]["error"] == "GPU OOM for frame 3"
    assert events[0]["active"] is True
    assert events[1]["active"] is False
    assert events[1]["description"] == "idle"
