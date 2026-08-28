"""Streaming and Real-Time Event Processing Module."""
import os
from typing import Optional

from streaming.base import BaseStreamEngine
from streaming.memory_stream import InMemoryStreamEngine
from streaming.metrics import StreamMetricsCollector
from streaming.worker import StreamingBatchWorker

_engine_instance: Optional[BaseStreamEngine] = None
_metrics_instance = StreamMetricsCollector()
_worker_instance: Optional[StreamingBatchWorker] = None


def get_stream_engine() -> BaseStreamEngine:
    """Return the active streaming engine (Redis if configured, else In-Memory)."""
    global _engine_instance
    if _engine_instance is None:
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                from streaming.redis_stream import RedisStreamEngine
                _engine_instance = RedisStreamEngine(redis_url=redis_url)
            except Exception:
                _engine_instance = InMemoryStreamEngine()
        else:
            _engine_instance = InMemoryStreamEngine()
    return _engine_instance


def get_metrics_collector() -> StreamMetricsCollector:
    """Return the singleton telemetry metrics collector."""
    return _metrics_instance


def get_stream_worker() -> StreamingBatchWorker:
    """Return the active background stream worker."""
    global _worker_instance
    if _worker_instance is None:
        engine = get_stream_engine()
        metrics = get_metrics_collector()
        _worker_instance = StreamingBatchWorker(
            engine=engine,
            metrics=metrics,
            topic="transactions.raw",
            batch_size=100,
        )
    return _worker_instance
