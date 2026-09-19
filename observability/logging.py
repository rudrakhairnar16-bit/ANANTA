import json
import logging
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class LogContext:
    correlation_id: str = field(default_factory=lambda: str(uuid4())[:8])
    pipeline_id: str | None = None
    episode_id: str | None = None
    stage: str | None = None
    stage_index: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "pipeline_id": self.pipeline_id,
            "episode_id": self.episode_id,
            "stage": self.stage,
            "stage_index": self.stage_index,
            **self.extra,
        }


_thread_local = threading.local()


def get_current_context() -> LogContext | None:
    return getattr(_thread_local, "log_context", None)


def set_current_context(context: LogContext):
    _thread_local.log_context = context


@contextmanager
def log_context(**kwargs):
    current = get_current_context()
    if current:
        new_context = LogContext(
            correlation_id=current.correlation_id,
            pipeline_id=kwargs.get("pipeline_id", current.pipeline_id),
            episode_id=kwargs.get("episode_id", current.episode_id),
            stage=kwargs.get("stage", current.stage),
            stage_index=kwargs.get("stage_index", current.stage_index),
            extra={**current.extra, **{k: v for k, v in kwargs.items() if k not in ["stage", "stage_index", "pipeline_id", "episode_id"]}},
        )
    else:
        new_context = LogContext(**kwargs)
    set_current_context(new_context)
    try:
        yield new_context
    finally:
        if current:
            set_current_context(current)
        else:
            # Properly clear the context by deleting the attribute
            if hasattr(_thread_local, "log_context"):
                delattr(_thread_local, "log_context")


class StructuredLogger:
    def __init__(self, name: str = "ananta", level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.propagate = True
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JsonFormatter())
            handler.setLevel(level)
            self.logger.addHandler(handler)

    def _log(self, level: int, message: str, **kwargs):
        context = get_current_context()
        extra = {
            "context": context.to_dict() if context else {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        self.logger.log(level, message, extra=extra)

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)

    def stage_start(self, stage: str, stage_index: int, total_stages: int):
        with log_context(stage=stage, stage_index=stage_index):
            self.info(f"Starting stage {stage}", stage=stage, stage_index=stage_index, total_stages=total_stages)

    def stage_complete(self, stage: str, stage_index: int, duration_ms: float):
        with log_context(stage=stage, stage_index=stage_index):
            self.info(f"Completed stage {stage}", stage=stage, stage_index=stage_index, duration_ms=duration_ms)

    def stage_failed(self, stage: str, stage_index: int, error: str, duration_ms: float):
        with log_context(stage=stage, stage_index=stage_index):
            self.error(f"Stage {stage} failed", stage=stage, stage_index=stage_index, error=error, duration_ms=duration_ms)

    def pipeline_start(self, pipeline_id: str, episode_id: str, total_stages: int):
        with log_context(pipeline_id=pipeline_id, episode_id=episode_id, stage_index=0):
            self.info("Pipeline started", pipeline_id=pipeline_id, episode_id=episode_id, total_stages=total_stages)

    def pipeline_complete(self, pipeline_id: str, episode_id: str, duration_ms: float, completed: int, failed: int):
        with log_context(pipeline_id=pipeline_id, episode_id=episode_id):
            self.info(
                "Pipeline completed",
                pipeline_id=pipeline_id,
                episode_id=episode_id,
                duration_ms=duration_ms,
                completed_stages=completed,
                failed_stages=failed,
            )

    def pipeline_failed(self, pipeline_id: str, episode_id: str, error: str, completed: int):
        with log_context(pipeline_id=pipeline_id, episode_id=episode_id):
            self.error("Pipeline failed", pipeline_id=pipeline_id, episode_id=episode_id, error=error, completed_stages=completed)

    def provider_call(self, provider: str, stage: str, success: bool, latency_ms: float, **kwargs):
        with log_context(stage=stage):
            self.info(
                f"Provider call {provider}",
                provider=provider,
                stage=stage,
                success=success,
                latency_ms=latency_ms,
                **kwargs,
            )

    def artifact_written(self, stage: str, path: str, size_bytes: int):
        with log_context(stage=stage):
            self.info("Artifact written", stage=stage, path=path, size_bytes=size_bytes)

    def checkpoint_saved(self, episode_id: str, stage: str):
        with log_context(episode_id=episode_id, stage=stage):
            self.info("Checkpoint saved", episode_id=episode_id, stage=stage)

    def state_restored(self, episode_id: str, stage: str):
        with log_context(episode_id=episode_id, stage=stage):
            self.info("State restored", episode_id=episode_id, stage=stage)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": getattr(record, "timestamp", datetime.now(timezone.utc).isoformat()),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if hasattr(record, "context"):
            log_data["context"] = record.context

        for key, value in record.__dict__.items():
            if key not in ["name", "msg", "args", "created", "filename", "funcName", "levelname", "levelno", "lineno", "module", "msecs", "message", "name", "pathname", "process", "processName", "relativeCreated", "thread", "threadName", "timestamp", "context", "exc_info", "exc_text", "stack_info"]:
                log_data[key] = value

        return json.dumps(log_data, ensure_ascii=False)


def get_logger(name: str = "ananta") -> StructuredLogger:
    return StructuredLogger(name)


def configure_logging(level: int = logging.INFO, json_output: bool = True):
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root_logger.addHandler(handler)
