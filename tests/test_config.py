"""Tests for the configuration module."""

import json
import tempfile
from pathlib import Path

from autovideo.config import Config


def test_default_config():
    cfg = Config()
    assert cfg.frame_interval == 3
    assert cfg.vlm_model_path == "qwen2.5-vl-7b"
    assert cfg.llm_model_path == "qwen3.8b"
    assert cfg.input_dir == "assets"
    assert cfg.output_dir == "output"
    assert cfg.temp_dir == "output/temp"
    assert cfg.video_path is None
    assert cfg.config_path is None


def test_config_from_dict():
    cfg = Config.from_dict({"frame_interval": 5, "video_path": "/tmp/test.mp4"})
    assert cfg.frame_interval == 5
    assert cfg.video_path == "/tmp/test.mp4"
    assert cfg.vlm_model_path == "qwen2.5-vl-7b"


def test_config_from_dict_ignores_unknown_keys():
    cfg = Config.from_dict({"frame_interval": 4, "nonexistent": "value"})
    assert cfg.frame_interval == 4
    assert not hasattr(cfg, "nonexistent")


def test_config_from_yaml():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write("frame_interval: 4\nvlm_model_path: llama-vl\nvideo_path: /tmp/v.mp4\n")
        tmp_path = f.name
    try:
        cfg = Config.from_yaml(tmp_path)
        assert cfg.frame_interval == 4
        assert cfg.vlm_model_path == "llama-vl"
        assert cfg.video_path == "/tmp/v.mp4"
    finally:
        Path(tmp_path).unlink()


def test_config_from_json():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump({"frame_interval": 2, "output_dir": "custom_output"}, f)
        tmp_path = f.name
    try:
        cfg = Config.from_json(tmp_path)
        assert cfg.frame_interval == 2
        assert cfg.output_dir == "custom_output"
    finally:
        Path(tmp_path).unlink()


def test_config_from_file_yaml():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write("frame_interval: 5\n")
        tmp_path = f.name
    try:
        cfg = Config.from_file(tmp_path)
        assert cfg.frame_interval == 5
    finally:
        Path(tmp_path).unlink()


def test_config_from_file_json():
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        json.dump({"frame_interval": 2}, f)
        tmp_path = f.name
    try:
        cfg = Config.from_file(tmp_path)
        assert cfg.frame_interval == 2
    finally:
        Path(tmp_path).unlink()


def test_config_from_file_unsupported():
    try:
        Config.from_file("config.txt")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_config_from_args_defaults():
    cfg = Config.from_args([])
    assert cfg.frame_interval == 3
    assert cfg.video_path is None
    assert cfg.config_path is None
    assert cfg.output_dir == "output"


def test_config_from_args_video_override():
    cfg = Config.from_args(["--video", "/tmp/test.mp4"])
    assert cfg.video_path == "/tmp/test.mp4"
    assert cfg.frame_interval == 3


def test_config_from_args_output_dir_override():
    cfg = Config.from_args(["--output-dir", "custom_out"])
    assert cfg.output_dir == "custom_out"


def test_config_from_args_frame_interval_override():
    cfg = Config.from_args(["--frame-interval", "5"])
    assert cfg.frame_interval == 5


def test_config_resolve_path():
    cfg = Config()
    resolved = cfg.resolve_path("test.mp4")
    assert resolved.is_absolute()
    assert resolved.name == "test.mp4"
