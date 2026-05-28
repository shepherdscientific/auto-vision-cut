"""Tests for the script and cut-list generation module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from autovideo.generate import (
    _build_voiceover_from_descriptions,
    _events_to_segments,
    _filter_active,
    _generate_deterministic,
    _llm_generate_with_retry,
    _load_vision_log,
    _merge_adjacent_segments,
    run,
)


def test_load_vision_log(tmp_path: Path) -> None:
    log_path = tmp_path / "vision_log.json"
    log_path.write_text(json.dumps([
        {"timestamp": 0, "active": True, "description": "coding"},
        {"timestamp": 3, "active": False, "description": "idle"},
    ]))
    events = _load_vision_log(str(log_path))
    assert len(events) == 2
    assert events[0]["description"] == "coding"
    assert events[1]["active"] is False


def test_load_vision_log_not_a_list(tmp_path: Path) -> None:
    log_path = tmp_path / "vision_log.json"
    log_path.write_text(json.dumps({"not": "a list"}))
    try:
        _load_vision_log(str(log_path))
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_filter_active() -> None:
    events = [
        {"timestamp": 0, "active": True, "description": "coding"},
        {"timestamp": 3, "active": False, "description": "idle"},
        {"timestamp": 6, "active": True, "description": "debugging"},
        {"timestamp": 9, "active": False, "description": "staring at screen"},
        {"timestamp": 12, "description": "no active key, defaults to True"},
    ]
    active = _filter_active(events)
    assert len(active) == 3
    assert active[0]["timestamp"] == 0
    assert active[1]["timestamp"] == 6
    assert active[2]["timestamp"] == 12


def test_events_to_segments_continuous() -> None:
    events = [
        {"timestamp": 0, "active": True},
        {"timestamp": 3, "active": True},
        {"timestamp": 6, "active": True},
    ]
    segments = _events_to_segments(events, frame_interval=3)
    assert len(segments) == 1
    assert segments[0]["start"] == 0
    assert segments[0]["end"] == 9


def test_events_to_segments_with_gaps() -> None:
    events = [
        {"timestamp": 0, "active": True},
        {"timestamp": 3, "active": True},
        {"timestamp": 15, "active": True},
        {"timestamp": 18, "active": True},
    ]
    segments = _events_to_segments(events, frame_interval=3)
    assert len(segments) == 2
    assert segments[0]["start"] == 0
    assert segments[0]["end"] == 6
    assert segments[1]["start"] == 15
    assert segments[1]["end"] == 21


def test_merge_adjacent_segments() -> None:
    segments = [
        {"start": 0, "end": 10},
        {"start": 12, "end": 20},
        {"start": 30, "end": 40},
    ]
    merged = _merge_adjacent_segments(segments, gap_threshold=5)
    assert len(merged) == 2
    assert merged[0]["start"] == 0
    assert merged[0]["end"] == 20
    assert merged[1]["start"] == 30
    assert merged[1]["end"] == 40


def test_merge_adjacent_segments_empty() -> None:
    assert _merge_adjacent_segments([]) == []


def test_events_to_segments_unsorted() -> None:
    events = [
        {"timestamp": 9, "active": True},
        {"timestamp": 0, "active": True},
        {"timestamp": 3, "active": True},
    ]
    segments = _events_to_segments(events, frame_interval=3)
    assert segments[0]["start"] == 0
    assert segments[0]["end"] == 12


def test_events_to_segments_empty() -> None:
    assert _events_to_segments([]) == []


def test_build_voiceover_from_descriptions() -> None:
    events = [
        {"timestamp": 0, "active": True, "description": "User opens VS Code"},
        {"timestamp": 3, "active": False, "description": "Staring at screen"},
        {"timestamp": 6, "active": True, "description": "Writing Python code"},
    ]
    voiceover = _build_voiceover_from_descriptions(events)
    assert "prototyping session" in voiceover
    assert "User opens VS Code" in voiceover
    assert "Writing Python code" in voiceover
    assert "Staring at screen" not in voiceover


def test_build_voiceover_empty() -> None:
    voiceover = _build_voiceover_from_descriptions([])
    assert "No active content" in voiceover


def test_generate_deterministic() -> None:
    events = [
        {"timestamp": 0, "active": True, "description": "Opening IDE"},
        {"timestamp": 3, "active": False, "description": "Idle"},
        {"timestamp": 6, "active": True, "description": "Coding feature"},
        {"timestamp": 9, "active": True, "description": "Running tests"},
    ]
    result = _generate_deterministic(events)
    assert "keep" in result
    assert "voiceover" in result
    assert len(result["keep"]) == 1
    assert result["keep"][0]["start"] == 0
    assert result["keep"][0]["end"] > 0
    assert len(result["voiceover"]) > 0


def test_run_deterministic_mode(tmp_path: Path) -> None:
    log_path = tmp_path / "vision_log.json"
    log_path.write_text(json.dumps([
        {"timestamp": 0, "active": True, "description": "Setup project"},
        {"timestamp": 3, "active": False, "description": "Checking phone"},
        {"timestamp": 6, "active": True, "description": "Implement feature"},
    ]))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    result = run(
        vision_log_path=str(log_path),
        model_path="test-model",
        output_dir=str(output_dir),
        use_llm=False,
    )

    assert "keep" in result
    assert "voiceover" in result

    cut_list_path = output_dir / "cut_list.json"
    assert cut_list_path.exists()
    saved = json.loads(cut_list_path.read_text())
    assert saved["keep"] == result["keep"]


def test_run_all_inactive_yields_empty_keep(tmp_path: Path) -> None:
    log_path = tmp_path / "vision_log.json"
    log_path.write_text(json.dumps([
        {"timestamp": 0, "active": False, "description": "Idle"},
        {"timestamp": 3, "active": False, "description": "Browser tabs"},
    ]))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    result = run(
        vision_log_path=str(log_path),
        model_path="test-model",
        output_dir=str(output_dir),
        use_llm=False,
    )

    assert result["keep"] == []
    assert "No active content" in result["voiceover"]


def test_run_with_llm_fallback_on_load_failure(tmp_path: Path) -> None:
    log_path = tmp_path / "vision_log.json"
    log_path.write_text(json.dumps([
        {"timestamp": 0, "active": True, "description": "Coding"},
    ]))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.side_effect = OSError("Model not found")

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = run(
            vision_log_path=str(log_path),
            model_path="nonexistent-model",
            output_dir=str(output_dir),
            use_llm=True,
        )

    assert "keep" in result
    assert "voiceover" in result


def test_run_with_llm_valid_output(tmp_path: Path) -> None:
    log_path = tmp_path / "vision_log.json"
    log_path.write_text(json.dumps([
        {"timestamp": 0, "active": True, "description": "Planning"},
        {"timestamp": 3, "active": True, "description": "Implementing"},
    ]))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    fake_model = MagicMock()
    fake_tokenizer = MagicMock()
    fake_output = json.dumps({
        "keep": [{"start": 0, "end": 10}],
        "voiceover": "The developer planned and implemented a feature.",
    })

    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = fake_output

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = run(
            vision_log_path=str(log_path),
            model_path="test-model",
            output_dir=str(output_dir),
            use_llm=True,
        )

    assert len(result["keep"]) == 1
    assert result["keep"][0]["start"] == 0
    assert result["keep"][0]["end"] == 10
    assert "planned" in result["voiceover"]


def test_run_with_llm_non_json_output_falls_back(tmp_path: Path) -> None:
    log_path = tmp_path / "vision_log.json"
    log_path.write_text(json.dumps([
        {"timestamp": 0, "active": True, "description": "Coding"},
    ]))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    fake_model = MagicMock()
    fake_tokenizer = MagicMock()

    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = "Just some text, no JSON here"

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = run(
            vision_log_path=str(log_path),
            model_path="test-model",
            output_dir=str(output_dir),
            use_llm=True,
        )

    assert "keep" in result
    assert "voiceover" in result
    assert "Coding" in result["voiceover"]


def test_llm_retry_succeeds_on_first_attempt() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.return_value = '{"keep": [], "voiceover": "test"}'

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = _llm_generate_with_retry(
            model=Mock(),
            tokenizer=Mock(),
            prompt="test prompt",
            max_tokens=512,
        )

    assert result == '{"keep": [], "voiceover": "test"}'
    assert fake_mlx_lm.generate.call_count == 1


def test_llm_retry_after_transient_failure() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.side_effect = [
        RuntimeError("transient error"),
        '{"keep": [{"start": 0, "end": 10}], "voiceover": "ok"}',
    ]

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.generate.time.sleep", return_value=None):
            result = _llm_generate_with_retry(
                model=Mock(),
                tokenizer=Mock(),
                prompt="test prompt",
                max_tokens=512,
            )

    assert result is not None
    assert fake_mlx_lm.generate.call_count == 2


def test_llm_retry_exhausts_and_returns_none() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.side_effect = RuntimeError("persistent failure")

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.generate.time.sleep", return_value=None):
            result = _llm_generate_with_retry(
                model=Mock(),
                tokenizer=Mock(),
                prompt="test prompt",
                max_tokens=512,
            )

    assert result is None
    assert fake_mlx_lm.generate.call_count == 4


def test_llm_retry_returns_none_when_mlx_lm_not_available() -> None:
    with patch.dict("sys.modules", {"mlx_lm": None}):
        result = _llm_generate_with_retry(
            model=Mock(),
            tokenizer=Mock(),
            prompt="test prompt",
            max_tokens=512,
        )

    assert result is None


def test_run_llm_falls_back_after_generate_exhausts_retries(tmp_path: Path) -> None:
    log_path = tmp_path / "vision_log.json"
    log_path.write_text(json.dumps([
        {"timestamp": 0, "active": True, "description": "Coding feature"},
    ]))

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.side_effect = RuntimeError("always fails")

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.generate.time.sleep", return_value=None):
            result = run(
                vision_log_path=str(log_path),
                model_path="test-model",
                output_dir=str(output_dir),
                use_llm=True,
            )

    assert "keep" in result
    assert "voiceover" in result
    assert "Coding feature" in result["voiceover"]
