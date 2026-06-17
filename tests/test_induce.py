"""Tests for the criteria induction module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from autovideo.config import Config
from autovideo.induce import (
    InduceError,
    _build_induction_input,
    _call_llm,
    _find_common_fillers,
    _has_mlx_lm,
    _load_model,
    _load_overrides,
    _strip_fences,
    induce_criteria,
    induce_run,
)


def _make_segment(sid: int, start: float, end: float, text: str) -> dict:
    return {
        "id": sid, "start": start, "end": end, "text": text,
        "confidence": 0.9, "duration": round(end - start, 3),
    }


def _write_transcript(path: Path, segments: list[dict]) -> None:
    path.write_text(json.dumps({"segments": segments, "language": "en"}))


def test_strip_fences_no_fences() -> None:
    raw = "# Cut/Keep Criteria\nSome content"
    assert _strip_fences(raw) == raw


def test_strip_fences_with_md_fence() -> None:
    raw = "```md\n# Cut/Keep Criteria\nContent here\n```"
    assert _strip_fences(raw) == "# Cut/Keep Criteria\nContent here"


def test_strip_fences_with_markdown_fence() -> None:
    raw = "```markdown\n# Cut/Keep Criteria\n```"
    assert _strip_fences(raw) == "# Cut/Keep Criteria"


def test_strip_fences_with_prose_before() -> None:
    raw = 'Here is the criteria:\n\n```md\n# Cut/Keep Criteria\nCUT: fillers\n```'
    result = _strip_fences(raw)
    assert "Cut/Keep Criteria" in result


def test_find_common_fillers(tmp_path: Path) -> None:
    segments = [
        _make_segment(0, 0.0, 3.0, "Um, so basically like what we want is"),
        _make_segment(1, 3.0, 6.0, "you know, actually it's like really simple"),
    ]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)
    fillers = _find_common_fillers(str(tpath))
    assert isinstance(fillers, list)
    assert len(fillers) > 0


def test_find_common_fillers_not_found(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 3.0, "This is clean speech with no fillers")]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)
    fillers = _find_common_fillers(str(tpath))
    assert len(fillers) <= 5


def test_find_common_fillers_with_approved(tmp_path: Path) -> None:
    segments = [
        _make_segment(0, 0.0, 3.0, "Um so basically like the thing is"),
        _make_segment(1, 3.0, 6.0, "You know actually this is important content"),
    ]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)
    apath = tmp_path / "cut_list.approved.json"
    apath.write_text(json.dumps({
        "decisions": [{"id": 0, "decision": "cut"}, {"id": 1, "decision": "keep"}],
        "keep": [], "stats": {},
    }))
    fillers = _find_common_fillers(str(tpath), str(apath))
    assert isinstance(fillers, list)


def test_find_common_fillers_fallback_on_bad_path() -> None:
    fillers = _find_common_fillers("/nonexistent/path.json")
    assert fillers == ["um", "uh", "like", "you know"]


def test_build_induction_input_transcript_only(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello world")]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)
    result = _build_induction_input(str(tpath))
    assert "Prior Transcript" in result
    assert "Hello world" in result


def test_build_induction_input_with_approved(tmp_path: Path) -> None:
    segments = [
        _make_segment(0, 0.0, 5.0, "Keep this"),
        _make_segment(1, 5.0, 10.0, "Cut this"),
    ]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)
    apath = tmp_path / "cut_list.approved.json"
    apath.write_text(json.dumps({
        "decisions": [
            {"id": 0, "decision": "keep", "confidence": 0.9, "reason": "good"},
            {"id": 1, "decision": "cut", "confidence": 0.8, "reason": "filler"},
        ],
        "keep": [{"start": 0.0, "end": 5.0}],
        "stats": {"total_kept": 1, "total_cut": 1, "time_saved_seconds": 5.0},
    }))
    result = _build_induction_input(str(tpath), str(apath))
    assert "Approved Cut/Keep Decisions" in result


def test_build_induction_input_raises_on_missing() -> None:
    with pytest.raises(InduceError, match="Failed to read transcript"):
        _build_induction_input("/nonexistent/transcript.json")


def test_has_mlx_lm() -> None:
    with patch.dict("sys.modules", {"mlx_lm": MagicMock()}):
        assert _has_mlx_lm() is True


def test_has_mlx_lm_false() -> None:
    import sys
    mods = {k: v for k, v in sys.modules.items() if k != "mlx_lm"}
    with patch.dict("sys.modules", mods, clear=True):
        assert _has_mlx_lm() is False


def test_load_model(tmp_path: Path) -> None:
    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = _load_model("test-model")
    assert result is not None
    assert result[0] is fake_model
    assert result[1] is fake_tokenizer


def test_load_model_none_on_import_error() -> None:
    import sys
    mods = {k: v for k, v in sys.modules.items() if k != "mlx_lm"}
    with patch.dict("sys.modules", mods, clear=True):
        result = _load_model("test-model")
    assert result is None


def test_call_llm_succeeds() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.return_value = "```md\n# Cut/Keep Criteria\n```"
    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        result = _call_llm(Mock(), Mock(), "prompt")
    assert "# Cut/Keep Criteria" in result


def test_call_llm_retry_then_succeeds() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.side_effect = [RuntimeError("transient"), "```md\n# Criteria\n```"]
    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.induce.time.sleep", return_value=None):
            result = _call_llm(Mock(), Mock(), "prompt")
    assert "Criteria" in result
    assert fake_mlx_lm.generate.call_count == 2


def test_call_llm_exhausts_raises() -> None:
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.generate.side_effect = RuntimeError("persistent")
    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.induce.time.sleep", return_value=None):
            with pytest.raises(InduceError, match="LLM generation failed"):
                _call_llm(Mock(), Mock(), "prompt")
    assert fake_mlx_lm.generate.call_count == 4


def test_call_llm_no_mlx_lm() -> None:
    with patch.dict("sys.modules", {"mlx_lm": None}):
        with pytest.raises(InduceError, match="mlx_lm not available"):
            _call_llm(Mock(), Mock(), "prompt")


def test_induce_criteria_writes_output(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello world this is a test")]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)
    output_path = str(tmp_path / "criteria" / "test.md")

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = (
        "```md\n# Cut/Keep Criteria\n\n## CUT Rules\n\n- filler words\n```"
    )

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.induce.time.sleep", return_value=None):
            result = induce_criteria(
                transcript_path=str(tpath),
                output_criteria_path=output_path,
                model_path="test-model",
                channel_name="test",
            )

    assert result == output_path
    assert Path(output_path).exists()
    content = Path(output_path).read_text()
    assert "Cut/Keep Criteria" in content


def test_induce_criteria_with_approved(tmp_path: Path) -> None:
    segments = [
        _make_segment(0, 0.0, 5.0, "Keep this content"),
        _make_segment(1, 5.0, 10.0, "Um like cut this filler"),
    ]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)
    apath = tmp_path / "cut_list.approved.json"
    apath.write_text(json.dumps({
        "decisions": [
            {"id": 0, "decision": "keep", "confidence": 0.9, "reason": "good"},
            {"id": 1, "decision": "cut", "confidence": 0.8, "reason": "filler"},
        ],
        "keep": [], "stats": {},
    }))
    output_path = str(tmp_path / "criteria" / "test.md")

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = (
        "```md\n# Cut/Keep Criteria\n\nCUT: filler\nKEEP: content\n```"
    )

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.induce.time.sleep", return_value=None):
            induce_criteria(
                transcript_path=str(tpath),
                output_criteria_path=output_path,
                model_path="test-model",
                approved_path=str(apath),
                channel_name="test",
            )

    assert Path(output_path).exists()


def test_induce_criteria_raises_on_empty_llm(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello")]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)
    output_path = str(tmp_path / "criteria" / "test.md")

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = ""

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.induce.time.sleep", return_value=None):
            with pytest.raises(InduceError, match="empty criteria"):
                induce_criteria(
                    transcript_path=str(tpath),
                    output_criteria_path=output_path,
                    model_path="test-model",
                )


def test_induce_criteria_raises_on_load_failure(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello")]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)

    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.side_effect = OSError("model not found")

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with pytest.raises(InduceError, match="Failed to load"):
            induce_criteria(
                transcript_path=str(tpath),
                output_criteria_path=str(tmp_path / "criteria.md"),
                model_path="nonexistent",
            )


def test_induce_run_skips_without_config(tmp_path: Path) -> None:
    config = Config()
    assert config.induce_from_path is None
    result = induce_run(config, str(tmp_path / "transcript.json"))
    assert result is None


def test_induce_run_skips_if_exists(tmp_path: Path) -> None:
    config = Config(
        induce_from_path=str(tmp_path),
        criteria_channel="test",
        induce_force=False,
    )
    criteria_dir = Path("criteria")
    criteria_dir.mkdir(exist_ok=True)
    existing = criteria_dir / "test.md"
    existing.write_text("# Existing criteria")

    result = induce_run(
        config,
        transcript_path=str(tmp_path / "transcript.json"),
    )
    assert result is not None
    assert "criteria/test.md" in result


def test_induce_run_produces_criteria(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello world")]
    prior_dir = tmp_path / "prior"
    prior_dir.mkdir()
    tpath = prior_dir / "transcript.json"
    _write_transcript(tpath, segments)

    config = Config(
        induce_from_path=str(prior_dir),
        criteria_channel="custom",
        induce_force=True,
    )

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = "```md\n# Cut/Keep Criteria\n\nCUT: fillers\n```"

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.induce.time.sleep", return_value=None):
            result = induce_run(
                config,
                transcript_path=str(tpath),
            )

    assert result is not None
    criteria_path = Path(result)
    assert criteria_path.exists()
    assert "Cut/Keep Criteria" in criteria_path.read_text()
    criteria_path.unlink()


def test_load_overrides_nonexistent_file(tmp_path: Path) -> None:
    result = _load_overrides(str(tmp_path))
    assert result is None


def test_load_overrides_loads_file(tmp_path: Path) -> None:
    overrides = [
        {"id": 1, "text": "Filler content", "decision": "cut", "original_decision": "keep", "reason": "user_override: edited in CSV"},
    ]
    opath = tmp_path / "overrides.json"
    opath.write_text(json.dumps(overrides))
    result = _load_overrides(str(tmp_path))
    assert result is not None
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_load_overrides_skips_empty_list(tmp_path: Path) -> None:
    opath = tmp_path / "overrides.json"
    opath.write_text(json.dumps([]))
    result = _load_overrides(str(tmp_path))
    assert result is None


def test_load_overrides_skips_bad_json(tmp_path: Path) -> None:
    opath = tmp_path / "overrides.json"
    opath.write_text("this is not json")
    result = _load_overrides(str(tmp_path))
    assert result is None


def test_build_induction_input_with_overrides(tmp_path: Path) -> None:
    segments = [
        _make_segment(0, 0.0, 5.0, "Keep this content"),
        _make_segment(1, 5.0, 10.0, "Um like filler here"),
    ]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)

    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(json.dumps([
        {"id": 1, "text": "Um like filler here", "decision": "cut", "original_decision": "keep", "reason": "user_override: edited in CSV"},
    ]))

    result = _build_induction_input(str(tpath), overrides_path=str(overrides_path))
    assert "User Override Examples" in result
    assert "Um like filler here" in result


def test_induce_criteria_with_overrides(tmp_path: Path) -> None:
    segments = [
        _make_segment(0, 0.0, 5.0, "Keep this content"),
        _make_segment(1, 5.0, 10.0, "Um like cut this filler"),
    ]
    tpath = tmp_path / "transcript.json"
    _write_transcript(tpath, segments)

    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(json.dumps([
        {"id": 1, "text": "Um like cut this filler", "decision": "cut", "original_decision": "keep", "reason": "user_override: edited in CSV"},
    ]))

    output_path = str(tmp_path / "criteria" / "override_test.md")

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = (
        "```md\n# Cut/Keep Criteria\n\nCUT: fillers\nKEEP: content\n```"
    )

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.induce.time.sleep", return_value=None):
            induce_criteria(
                transcript_path=str(tpath),
                output_criteria_path=output_path,
                model_path="test-model",
                overrides_path=str(overrides_path),
                channel_name="override_test",
            )

    assert Path(output_path).exists()


def test_induce_run_discovers_overrides(tmp_path: Path) -> None:
    segments = [_make_segment(0, 0.0, 5.0, "Hello world")]
    prior_dir = tmp_path / "prior"
    prior_dir.mkdir()
    tpath = prior_dir / "transcript.json"
    _write_transcript(tpath, segments)

    overrides_path = prior_dir / "overrides.json"
    overrides_path.write_text(json.dumps([
        {"id": 0, "text": "Hello world", "decision": "keep", "original_decision": "cut", "reason": "user_override: edited in CSV"},
    ]))

    config = Config(
        induce_from_path=str(prior_dir),
        criteria_channel="override_channel",
        induce_force=True,
    )

    fake_model = Mock()
    fake_tokenizer = Mock()
    fake_mlx_lm = MagicMock()
    fake_mlx_lm.load.return_value = (fake_model, fake_tokenizer)
    fake_mlx_lm.generate.return_value = "```md\n# Cut/Keep Criteria\n\nCUT: fillers\n```"

    with patch.dict("sys.modules", {"mlx_lm": fake_mlx_lm}):
        with patch("autovideo.induce.time.sleep", return_value=None):
            result = induce_run(
                config,
                transcript_path=str(tpath),
            )

    assert result is not None
    criteria_path = Path(result)
    assert criteria_path.exists()
    criteria_path.unlink()
