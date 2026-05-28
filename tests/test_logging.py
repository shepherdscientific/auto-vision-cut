"""Tests for the logging setup module."""

import logging
import tempfile
from pathlib import Path

from autovideo.logging_setup import LOG_FORMAT, get_module_logger, setup_logging


def test_setup_logging_console_handler() -> None:
    setup_logging(level=logging.DEBUG)
    root = logging.getLogger()
    assert len(root.handlers) == 1
    handler = root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.level == logging.DEBUG


def test_setup_logging_file_handler() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "pipeline.log"
        setup_logging(log_file=str(log_file), level=logging.INFO, console=False)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert isinstance(handler, logging.FileHandler)

        logger = get_module_logger("test.module")
        logger.info("test message")
        for h in root.handlers:
            h.flush()

        content = log_file.read_text()
        assert "test.module" in content
        assert "[INFO]" in content
        assert "test message" in content


def test_setup_logging_both_handlers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "pipeline.log"
        setup_logging(log_file=str(log_file), level=logging.INFO)
        root = logging.getLogger()
        assert len(root.handlers) == 2
        types = {type(h) for h in root.handlers}
        assert logging.StreamHandler in types
        assert logging.FileHandler in types


def test_get_module_logger() -> None:
    logger = get_module_logger("autovideo.extract")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "autovideo.extract"


def test_log_format_contains_required_fields() -> None:
    assert "%(asctime)s" in LOG_FORMAT
    assert "%(levelname)s" in LOG_FORMAT
    assert "%(name)s" in LOG_FORMAT
    assert "%(message)s" in LOG_FORMAT


def test_handlers_cleared_on_reconfigure() -> None:
    setup_logging(level=logging.INFO)
    root = logging.getLogger()
    initial_count = len(root.handlers)
    setup_logging(level=logging.DEBUG)
    assert len(root.handlers) == initial_count
