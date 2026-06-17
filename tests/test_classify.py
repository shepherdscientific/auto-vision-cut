"""Tests for the LLM segment classifier module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from autovideo.classify import (
    ClassifyError,
    _build_classify_prompt,
    _build_output,
    _chunk_segments,
    _classify_chunk,
    _load_segments,
    _load_vision_log,
    _merge_vision_into_segments,
    _parse_json_output,
    _strip_fences,
    _validate_decisions,
    classify,
    rollback_classify,
    run,
)
from autovideo.config import Config
from autovideo.model_router import RouterError, _MlxLmProvider


def _make_segment(sid: int, start: float, end: float, text: str) -> dict:
    duration = round(end - start, 3)
    return {
        "id": sid, "start": start, "end": end, "text": text,
        "confidence": 0.9, "duration": duration,
    }


def test_strip_fences_no_fences() -> None:
    raw = '{"decisions": []}'
    assert _strip_fences(raw) == raw


def test_strip_fences_with_json_fence() -> None:
    raw = '```json\n{"decisions": []}\n```'
    assert _strip_fences(raw) == '{"decisions": []}'


def test_strip_fences_with_plain_fence() -> None:
    raw = '```\n{"decisions": []}\n```'
    assert _strip_fences(raw) == '{"decisions": []}'


def test_strip_fences_with_prose_before() -> None:
    raw = 'Here is the result:\n\n```json\n{"decisions": [{"id": 0, "decision": "keep"}]}\n```'
    result = _strip_fences(raw)
    parsed = json.loads(result)
    assert parsed["decisions"][0]["id"] == 0


def test_parse_json_output_valid() -> None:
    raw = '{"decisions": [{"id": 0, "decision": "keep"}]}'
    result = _parse_json_output(raw)
    assert result is not None
    assert result["decisions"][0]["decision"] == "keep"


def test_parse_json_output_invalid() -> None:
    with pytest.raises(ClassifyError, match="No JSON object found"):
        _parse_json_output("not json")


def test_parse_json_output_fenced() -> None:
    raw = '```json\n{"decisions": [{"id": 1, "decision": "cut"}]}\n```'
    result = _parse_json_output(raw)
    assert result is not None
    assert result["decisions"][0]["id"] == 1


def test_build_classify_prompt_includes_criteria() -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello world")]
    prompt = _build_classify_prompt(segments, "## CUT RULES")
    assert "## CUT RULES" in prompt
    assert "Hello world" in prompt
    assert "Transcript Segments to Classify" in prompt


def test_build_classify_prompt_with_context() -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Test")]
    prompt = _build_classify_prompt(segments, "## CUT RULES", "**Transcript:** tutorial")
    assert "Supplementary Context" in prompt
    assert "tutorial" in prompt


def test_chunk_segments_single_chunk() -> None:
    segments = [_make_segment(i, float(i * 5), float(i * 5 + 4), f"seg {i}") for i in range(3)]
    chunks = _chunk_segments(segments, max_chars=10000)
    assert len(chunks) == 1
    assert len(chunks[0]) == 3


def test_chunk_segments_multiple_chunks() -> None:
    long_text = "hello " * 1000
    segments = [_make_segment(0, 0.0, 10.0, long_text), _make_segment(1, 10.0, 20.0, long_text)]
    chunks = _chunk_segments(segments, max_chars=500)
    assert len(chunks) >= 2


def test_chunk_segments_empty() -> None:
    assert _chunk_segments([]) == []


def test_load_segments(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello")]
    path = tmp_path / "segments.json"
    path.write_text(json.dumps({"segments": segments}))
    loaded = _load_segments(str(path))
    assert len(loaded) == 1
    assert loaded[0]["id"] == 0


def test_load_segments_invalid(tmp_path: Path) -> None:
    path = tmp_path / "segments.json"
    path.write_text(json.dumps({"not_segments": []}))
    loaded = _load_segments(str(path))
    assert loaded == []


def test_validate_decisions_all_matched() -> None:
    decisions = [
        {"id": 0, "decision": "keep", "reason": "good", "confidence": 0.9, "tag": "substantive"},
        {"id": 1, "decision": "cut", "reason": "filler", "confidence": 0.8, "tag": "filler"},
    ]
    validated = _validate_decisions(decisions, {0, 1})
    assert len(validated) == 2
    assert validated[0]["decision"] == "keep"
    assert validated[1]["decision"] == "cut"


def test_validate_decisions_defaults_unmatched() -> None:
    decisions = [{"id": 0, "decision": "keep", "reason": "ok",
                  "confidence": 0.9, "tag": "substantive"}]
    validated = _validate_decisions(decisions, {0, 1, 2})
    assert len(validated) == 3
    assert validated[0]["id"] == 0
    assert validated[0]["decision"] == "keep"
    assert validated[1]["id"] == 1
    assert validated[1]["decision"] == "keep"
    assert validated[1]["reason"] == "default_keep_unmatched"
    assert validated[2]["id"] == 2
    assert validated[2]["decision"] == "keep"


def test_validate_decisions_dedupes() -> None:
    decisions = [
        {"id": 0, "decision": "keep", "reason": "first", "confidence": 0.9, "tag": "a"},
        {"id": 0, "decision": "cut", "reason": "duplicate", "confidence": 0.9, "tag": "b"},
    ]
    validated = _validate_decisions(decisions, {0})
    assert len(validated) == 1
    assert validated[0]["decision"] == "keep"


def test_validate_decisions_filtered_non_dict() -> None:
    decisions: list = []
    validated = _validate_decisions(decisions, {0})
    assert len(validated) == 1
    assert validated[0]["id"] == 0
    assert validated[0]["decision"] == "keep"


def test_validate_decisions_rejects_unexpected_ids() -> None:
    decisions = [
        {"id": 0, "decision": "keep", "reason": "r", "confidence": 0.9, "tag": "t"},
        {"id": 99, "decision": "cut", "reason": "hallucinated", "confidence": 0.9, "tag": "t"},
    ]
    validated = _validate_decisions(decisions, {0})
    assert len(validated) == 1
    assert validated[0]["id"] == 0


def test_validate_decisions_sorts() -> None:
    decisions = [
        {"id": 3, "decision": "keep", "reason": "r", "confidence": 0.9, "tag": "t"},
        {"id": 0, "decision": "cut", "reason": "r", "confidence": 0.9, "tag": "t"},
    ]
    validated = _validate_decisions(decisions, {0, 3})
    assert validated[0]["id"] == 0
    assert validated[1]["id"] == 3


def test_build_output() -> None:
    decisions = [
        {"id": 0, "decision": "keep", "reason": "good", "confidence": 0.9, "tag": "substantive"},
        {"id": 1, "decision": "cut", "reason": "bad", "confidence": 0.8, "tag": "filler"},
    ]
    keeps = [{"start": 0.0, "end": 5.0}]
    result = _build_output(decisions, keeps, total_duration=10.0)
    assert result["stats"]["total_kept"] == 1
    assert result["stats"]["total_cut"] == 1
    assert result["stats"]["total_segments"] == 2
    assert result["stats"]["time_saved_seconds"] == 5.0
    assert len(result["decisions"]) == 2
    assert len(result["keep"]) == 1


def test_build_output_no_cut() -> None:
    decisions = [{"id": 0, "decision": "keep", "reason": "ok", "confidence": 0.9, "tag": "demo"}]
    keeps = [{"start": 0.0, "end": 10.0}]
    result = _build_output(decisions, keeps, total_duration=10.0)
    assert result["stats"]["time_saved_seconds"] == 0.0


def test_rollback_classify() -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello")]
    result = rollback_classify(segments)
    assert result["stats"]["total_kept"] == 1
    assert result["stats"]["total_cut"] == 0
    assert len(result["keep"]) == 1
    assert result["decisions"][0]["reason"] == "fallback_classifier_unavailable"


def test_classify_write_output(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello"), _make_segment(1, 5.0, 10.0, "World")]
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(json.dumps({"segments": segments}))
    output_dir = str(tmp_path / "output")

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_llm_output = json.dumps({
        "decisions": [
            {"id": 0, "decision": "keep", "reason": "substantive",
             "confidence": 0.95, "tag": "substantive"},
            {"id": 1, "decision": "cut", "reason": "filler",
             "confidence": 0.8, "tag": "filler"},
        ],
        "keep": [{"start": 0.0, "end": 5.0}],
        "stats": {"total_kept": 1, "total_cut": 1, "time_saved_seconds": 5.0},
    })
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = fake_llm_output

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = classify(
            segments_path=str(seg_path),
            criteria_text="## CUT RULES",
            model_path="test-model",
            output_dir=output_dir,
        )

    assert result["stats"]["total_kept"] == 1
    assert result["stats"]["total_cut"] == 1
    assert len(result["decisions"]) == 2

    cut_list_path = Path(output_dir) / "cut_list.json"
    assert cut_list_path.exists()
    saved = json.loads(cut_list_path.read_text())
    assert saved["stats"] == result["stats"]


def test_classify_empty_segments(tmp_path: Path) -> None:
    seg_path = tmp_path / "empty.json"
    seg_path.write_text(json.dumps({"segments": []}))
    output_dir = str(tmp_path / "output")
    result = classify(
        segments_path=str(seg_path),
        criteria_text="## CUT RULES",
        model_path="test-model",
        output_dir=output_dir,
    )
    assert result["stats"]["total_segments"] == 0
    assert result["stats"]["total_cut"] == 0


def test_classify_raises_on_no_mlx_lm(tmp_path: Path) -> None:
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(json.dumps({"segments": [_make_segment(0, 0.0, 5.0, "Hi")]}))

    with patch.dict("sys.modules", {"mlx_lm": None}):
        with pytest.raises(ClassifyError, match="Failed to load"):
            classify(
                segments_path=str(seg_path),
                criteria_text="## CUT RULES",
                model_path="test-model",
                output_dir=str(tmp_path / "output"),
            )


def test_classify_raises_on_load_failure(tmp_path: Path) -> None:
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(json.dumps({"segments": [_make_segment(0, 0.0, 5.0, "Hi")]}))

    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.side_effect = OSError("model not found")

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with pytest.raises(ClassifyError, match="Failed to load"):
            classify(
                segments_path=str(seg_path),
                criteria_text="## CUT RULES",
                model_path="nonexistent",
                output_dir=str(tmp_path / "output"),
            )


def test_classify_raises_on_chunk_failure(tmp_path: Path) -> None:
    seg_path = tmp_path / "segments.json"
    segments = [_make_segment(0, 0.0, 5.0, "Hi"), _make_segment(1, 5.0, 10.0, "Bye")]
    seg_path.write_text(json.dumps({"segments": segments}))

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.side_effect = RuntimeError("LLM crashed")

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.classify.time.sleep", return_value=None):
            with pytest.raises(ClassifyError, match="mlx_lm generation failed"):
                classify(
                    segments_path=str(seg_path),
                    criteria_text="## CUT RULES",
                    model_path="test-model",
                    output_dir=str(tmp_path / "output"),
                )


def test_mlx_provider_generate_succeeds() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.return_value = '{"decisions": []}'
    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        provider = _MlxLmProvider()
        result = provider.generate(Mock(), Mock(), "prompt")
    assert result == '{"decisions": []}'


def test_mlx_provider_retry_then_succeeds() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.side_effect = [RuntimeError("transient"), '{"decisions": []}']
    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.model_router.time.sleep", return_value=None):
            provider = _MlxLmProvider()
            result = provider.generate(Mock(), Mock(), "prompt")
    assert result == '{"decisions": []}'
    assert fake_mlx_lm.generate.call_count == 2


def test_mlx_provider_exhausts_raises() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.side_effect = RuntimeError("persistent")
    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.model_router.time.sleep", return_value=None):
            with pytest.raises(RouterError, match="mlx_lm generation failed"):
                provider = _MlxLmProvider()
                provider.generate(Mock(), Mock(), "prompt")
    assert fake_mlx_lm.generate.call_count == 4


def test_mlx_provider_no_mlx_lm() -> None:
    import sys as _sys
    mods = {k: v for k, v in _sys.modules.items() if k != "mlx_lm"}
    with patch.dict("sys.modules", mods, clear=True):
        with pytest.raises(RouterError, match="mlx_lm not available"):
            provider = _MlxLmProvider()
            provider.generate(Mock(), Mock(), "prompt")


def test_classify_chunk_returns_decisions() -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello")]
    provider = MagicMock()
    provider.generate.return_value = json.dumps({
        "decisions": [{"id": 0, "decision": "keep", "reason": "good",
                       "confidence": 0.9, "tag": "substantive"}],
    })
    decisions = _classify_chunk(provider, Mock(), Mock(), segments, "## CUT RULES")
    assert len(decisions) == 1


def test_classify_chunk_raises_on_bad_json() -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello")]
    provider = MagicMock()
    provider.generate.return_value = "not json"
    with pytest.raises(ClassifyError, match="No JSON object found"):
        _classify_chunk(provider, Mock(), Mock(), segments, "## CUT RULES")


def test_classify_chunk_missing_decisions() -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello")]
    provider = MagicMock()
    provider.generate.return_value = json.dumps({"keep": []})
    with pytest.raises(ClassifyError, match="missing.*decisions"):
        _classify_chunk(provider, Mock(), Mock(), segments, "## CUT RULES")


def test_merge_vision_into_segments_no_vision() -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello")]
    result = _merge_vision_into_segments(segments, [])
    assert len(result) == 1
    assert "vision_active" not in result[0]


def test_merge_vision_into_segments_adds_active(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 10.0, "Hello world")]
    vision_events = [
        {"timestamp": 2, "active": True, "description": "typing code", "frame": "000002.jpg"},
        {"timestamp": 5, "active": False, "description": "staring", "frame": "000005.jpg"},
        {"timestamp": 7, "active": True, "description": "scrolling", "frame": "000007.jpg"},
    ]
    result = _merge_vision_into_segments(segments, vision_events)
    assert result[0]["vision_active"] is True
    assert len(result[0]["vision_descriptions"]) == 3


def test_merge_vision_into_segments_inactive_majority() -> None:
    segments = [_make_segment(0, 0.0, 10.0, "Hello world")]
    vision_events = [
        {"timestamp": 2, "active": False, "description": "staring", "frame": "000002.jpg"},
        {"timestamp": 5, "active": False, "description": "idle", "frame": "000005.jpg"},
        {"timestamp": 7, "active": True, "description": "typing", "frame": "000007.jpg"},
    ]
    result = _merge_vision_into_segments(segments, vision_events)
    assert result[0]["vision_active"] is False


def test_merge_vision_into_segments_no_coverage() -> None:
    segments = [_make_segment(0, 10.0, 20.0, "Hello world")]
    vision_events = [
        {"timestamp": 2, "active": False, "description": "idle", "frame": "000002.jpg"},
    ]
    result = _merge_vision_into_segments(segments, vision_events)
    assert result[0]["vision_active"] is None
    assert result[0]["vision_descriptions"] == []


def test_load_vision_log_exists(tmp_path: Path) -> None:
    events = [{"timestamp": 0, "active": True, "description": "coding", "frame": "000000.jpg"}]
    path = tmp_path / "vision_log.json"
    path.write_text(json.dumps(events))
    result = _load_vision_log(str(tmp_path))
    assert len(result) == 1
    assert result[0]["active"] is True


def test_load_vision_log_not_exists(tmp_path: Path) -> None:
    result = _load_vision_log(str(tmp_path))
    assert result == []


def test_load_vision_log_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "vision_log.json"
    path.write_text("not json")
    result = _load_vision_log(str(tmp_path))
    assert result == []


def test_vision_integration_in_classify(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello"), _make_segment(1, 5.0, 10.0, "World")]
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(json.dumps({"segments": segments}))

    output_dir = str(tmp_path / "output")

    vision_events = [
        {"timestamp": 2, "active": True, "description": "coding", "frame": "000002.jpg"},
        {"timestamp": 7, "active": False, "description": "idle", "frame": "000007.jpg"},
    ]
    vision_path = Path(output_dir) / "vision_log.json"
    vision_path.parent.mkdir(parents=True, exist_ok=True)
    vision_path.write_text(json.dumps(vision_events))

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_llm_output = json.dumps({
        "decisions": [
            {"id": 0, "decision": "keep", "reason": "substantive",
             "confidence": 0.95, "tag": "substantive"},
            {"id": 1, "decision": "cut", "reason": "filler",
             "confidence": 0.8, "tag": "filler"},
        ],
        "keep": [{"start": 0.0, "end": 5.0}],
        "stats": {"total_kept": 1, "total_cut": 1, "time_saved_seconds": 5.0},
    })
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = fake_llm_output

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = classify(
            segments_path=str(seg_path),
            criteria_text="## CUT RULES",
            model_path="test-model",
            output_dir=output_dir,
        )

    assert result["stats"]["total_segments"] == 2
    assert result["stats"]["total_kept"] == 1


def test_run_with_config(tmp_path: Path) -> None:
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(json.dumps({"segments": [_make_segment(0, 0.0, 5.0, "Hello")]}))
    output_dir = str(tmp_path / "output")
    Path(output_dir).mkdir()

    criteria_path = tmp_path / "test_criteria.md"
    criteria_path.write_text("## CUT RULES\nCut filler words.\n## JSON Output Contract\n")
    config = Config(
        criteria_path=str(criteria_path),
        llm_model_path="test-model",
        output_dir=output_dir,
    )
    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = json.dumps({
        "decisions": [{"id": 0, "decision": "keep", "reason": "good",
                       "confidence": 0.9, "tag": "substantive"}],
        "keep": [{"start": 0.0, "end": 5.0}],
        "stats": {"total_kept": 1, "total_cut": 0, "time_saved_seconds": 0.0},
    })
    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = run(config, str(seg_path), output_dir=output_dir)

    assert result["stats"]["total_segments"] == 1
    assert result["stats"]["total_kept"] == 1
