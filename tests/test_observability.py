import logging

import pytest

from observability.logging import (
    JsonFormatter,
    LogContext,
    StructuredLogger,
    _thread_local,
    configure_logging,
    get_current_context,
    get_logger,
    log_context,
    set_current_context,
)


@pytest.fixture(autouse=True)
def clear_log_context():
    """Clear the logging context before each test."""
    if hasattr(_thread_local, "log_context"):
        delattr(_thread_local, "log_context")
    yield
    if hasattr(_thread_local, "log_context"):
        delattr(_thread_local, "log_context")


def test_log_context_creation():
    context = LogContext(correlation_id="test-123", episode_id="TEST-E01", stage="story")
    assert context.correlation_id == "test-123"
    assert context.episode_id == "TEST-E01"
    assert context.stage == "story"


def test_log_context_creation():
    context = LogContext(correlation_id="test-123", episode_id="TEST-E01", stage="story")
    assert context.correlation_id == "test-123"
    assert context.episode_id == "TEST-E01"
    assert context.stage == "story"


def test_log_context_to_dict():
    context = LogContext(correlation_id="test-123", episode_id="TEST-E01", stage="story", stage_index=1)
    d = context.to_dict()
    assert d["correlation_id"] == "test-123"
    assert d["episode_id"] == "TEST-E01"
    assert d["stage"] == "story"
    assert d["stage_index"] == 1


def test_get_current_context_none():
    context = get_current_context()
    assert context is None


def test_set_current_context():
    context = LogContext(correlation_id="test-123")
    set_current_context(context)
    retrieved = get_current_context()
    assert retrieved is context


def test_log_context_manager():
    with log_context(correlation_id="test-123", stage="story") as ctx:
        assert ctx.correlation_id == "test-123"
        assert ctx.stage == "story"
        current = get_current_context()
        assert current is ctx

    assert get_current_context() is None


def test_log_context_manager_nested():
    outer = LogContext(correlation_id="outer", episode_id="TEST-E01")
    set_current_context(outer)

    with log_context(stage="story") as ctx:
        assert ctx.correlation_id == "outer"
        assert ctx.episode_id == "TEST-E01"
        assert ctx.stage == "story"

    current = get_current_context()
    assert current is outer


def test_structured_logger_creation():
    logger = StructuredLogger("test.logger")
    assert logger.logger.name == "test.logger"


def _check_caplog(caplog, *keywords):
    """Check if any keyword appears in caplog records (message or extra fields)."""
    for record in caplog.records:
        msg = record.getMessage()
        extra_str = str(record.__dict__)
        if all(kw in msg or kw in extra_str for kw in keywords):
            return True
    return False


def test_structured_logger_info(caplog):
    logger = StructuredLogger("test.logger", level=logging.INFO)
    logger.info("Test message")

    assert _check_caplog(caplog, "Test message")


def test_structured_logger_with_context(caplog):
    logger = StructuredLogger("test.logger", level=logging.INFO)
    with log_context(correlation_id="test-123", stage="story"):
        logger.info("Test message")

    assert _check_caplog(caplog, "test-123", "story")


def test_structured_logger_stage_start(caplog):
    logger = StructuredLogger("test.logger", level=logging.INFO)
    logger.stage_start("story", 0, 19)

    assert _check_caplog(caplog, "story")


def test_structured_logger_stage_complete(caplog):
    logger = StructuredLogger("test.logger", level=logging.INFO)
    logger.stage_complete("story", 0, 100.5)

    assert _check_caplog(caplog, "story")


def test_structured_logger_stage_failed(caplog):
    logger = StructuredLogger("test.logger", level=logging.INFO)
    logger.stage_failed("story", 0, "Test error", 100.5)

    assert _check_caplog(caplog, "story", "Test error")


def test_structured_logger_pipeline_start(caplog):
    logger = StructuredLogger("test.logger", level=logging.INFO)
    logger.pipeline_start("pipeline-123", "TEST-E01", 19)

    assert _check_caplog(caplog, "pipeline-123", "TEST-E01")


def test_structured_logger_pipeline_complete(caplog):
    logger = StructuredLogger("test.logger", level=logging.INFO)
    logger.pipeline_complete("pipeline-123", "TEST-E01", 5000.0, 19, 0)

    assert _check_caplog(caplog, "pipeline-123", "TEST-E01")


def test_json_formatter():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    record.timestamp = "2024-01-01T00:00:00+00:00"
    record.context = {"correlation_id": "test-123"}

    formatted = formatter.format(record)
    assert "Test message" in formatted
    assert "test-123" in formatted


def test_get_logger():
    logger = get_logger("test.logger")
    assert isinstance(logger, StructuredLogger)


def test_configure_logging():
    configure_logging(level=logging.DEBUG, json_output=False)
    logger = logging.getLogger()
    assert logger.level == logging.DEBUG
