"""Tests for the retry module."""

from unittest.mock import Mock, patch

import pytest

from autovideo.retry import retry_with_backoff


def test_retry_succeeds_on_first_attempt() -> None:
    func = Mock(return_value="success")

    wrapped = retry_with_backoff(max_retries=2)(func)
    result = wrapped()

    assert result == "success"
    assert func.call_count == 1


def test_retry_succeeds_after_failures() -> None:
    func = Mock(side_effect=[ValueError("fail1"), ValueError("fail2"), "success"])

    wrapped = retry_with_backoff(max_retries=3, initial_delay=0.0)(func)
    result = wrapped()

    assert result == "success"
    assert func.call_count == 3


def test_retry_exhausts_retries() -> None:
    func = Mock(side_effect=ValueError("always fails"))

    wrapped = retry_with_backoff(max_retries=3, initial_delay=0.0)(func)

    with pytest.raises(ValueError, match="always fails"):
        wrapped()

    assert func.call_count == 4


def test_retry_default_max_retries_is_three() -> None:
    func = Mock(side_effect=ValueError("repeated failure"))

    wrapped = retry_with_backoff(initial_delay=0.0)(func)

    with pytest.raises(ValueError):
        wrapped()

    assert func.call_count == 4


def test_retry_with_zero_max_retries() -> None:
    func = Mock(side_effect=ValueError("fail fast"))

    wrapped = retry_with_backoff(max_retries=0, initial_delay=0.0)(func)

    with pytest.raises(ValueError):
        wrapped()

    assert func.call_count == 1


def test_retry_sleeps_between_attempts() -> None:
    func = Mock(side_effect=[ValueError("fail1"), "success"])

    with patch("time.sleep") as mock_sleep:
        wrapped = retry_with_backoff(
            max_retries=2, initial_delay=0.5, backoff_factor=3.0
        )(func)
        result = wrapped()

    assert result == "success"
    assert mock_sleep.call_count == 1
    mock_sleep.assert_called_with(0.5)


def test_retry_exponential_backoff_delay() -> None:
    func = Mock(side_effect=[ValueError("fail1"), ValueError("fail2"), "success"])

    with patch("time.sleep") as mock_sleep:
        wrapped = retry_with_backoff(
            max_retries=3, initial_delay=1.0, backoff_factor=2.0
        )(func)
        result = wrapped()

    assert result == "success"
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)


def test_retry_passes_arguments_correctly() -> None:
    func = Mock(return_value="ok")

    wrapped = retry_with_backoff(max_retries=2)(func)
    result = wrapped("arg1", key="value")

    assert result == "ok"
    func.assert_called_with("arg1", key="value")


def test_retry_preserves_function_name() -> None:
    def my_func(x: int) -> int:
        return x

    wrapped = retry_with_backoff(max_retries=2)(my_func)
    assert wrapped.__name__ == "my_func"


def test_retry_logs_warning_on_retry() -> None:
    func = Mock(side_effect=[ValueError("transient"), "success"])

    with patch("autovideo.retry.logger.warning") as mock_warn:
        wrapped = retry_with_backoff(
            max_retries=2, initial_delay=0.0
        )(func)
        wrapped()

    assert mock_warn.call_count == 1
    call_args = mock_warn.call_args[0]
    assert "Attempt" in call_args[0]
    assert call_args[1] == 1
    assert call_args[2] == 3
    assert "transient" in str(call_args[4])
