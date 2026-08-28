"""Real-time throughput (TPS) and latency percentiles telemetry metrics collector."""
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional


class StreamMetricsCollector:
    """Thread-safe rolling window metrics tracker for TPS and latency percentiles."""

    def __init__(self, window_seconds: float = 10.0):
        self.window_seconds = window_seconds
        self._lock = threading.Lock()

        # Rolling timestamp logs for rate calculations
        self._published_timestamps: deque = deque()
        self._processed_timestamps: deque = deque()

        # Latency samples (in milliseconds)
        self._latency_samples: deque = deque(maxlen=5000)

        # Lifetime counters
        self.total_published: int = 0
        self.total_processed: int = 0
        self.total_errors: int = 0
        self.peak_ingest_tps: float = 0.0
        self.peak_process_tps: float = 0.0
        self.start_time: float = time.time()

    def record_published(self, count: int = 1):
        """Record newly published transactions."""
        now = time.time()
        with self._lock:
            self.total_published += count
            for _ in range(count):
                self._published_timestamps.append(now)
            self._prune(now)

    def record_processed(self, count: int = 1, latencies_ms: Optional[List[float]] = None):
        """Record processed transactions and latency samples."""
        now = time.time()
        with self._lock:
            self.total_processed += count
            for _ in range(count):
                self._processed_timestamps.append(now)
            if latencies_ms:
                self._latency_samples.extend(latencies_ms)
            self._prune(now)

    def record_error(self, count: int = 1):
        """Record processing errors."""
        with self._lock:
            self.total_errors += count

    def _prune(self, now: float):
        """Prune timestamps older than window_seconds."""
        cutoff = now - self.window_seconds
        while self._published_timestamps and self._published_timestamps[0] < cutoff:
            self._published_timestamps.popleft()
        while self._processed_timestamps and self._processed_timestamps[0] < cutoff:
            self._processed_timestamps.popleft()

    def get_snapshot(self, backlog_size: int = 0) -> Dict[str, Any]:
        """Compute snapshot of current throughput, latency percentiles, and backlog."""
        now = time.time()
        with self._lock:
            self._prune(now)

            # Instantaneous TPS over the active rolling window
            dur = max(self.window_seconds, 1.0)
            current_ingest_tps = len(self._published_timestamps) / dur
            current_process_tps = len(self._processed_timestamps) / dur

            if current_ingest_tps > self.peak_ingest_tps:
                self.peak_ingest_tps = current_ingest_tps
            if current_process_tps > self.peak_process_tps:
                self.peak_process_tps = current_process_tps

            # Compute latency percentiles
            latencies = sorted(self._latency_samples)
            n = len(latencies)
            if n > 0:
                p50 = latencies[int(n * 0.50)]
                p95 = latencies[int(n * 0.95)]
                p99 = latencies[int(n * 0.99)]
                avg_latency = sum(latencies) / n
            else:
                p50 = 0.0
                p95 = 0.0
                p99 = 0.0
                avg_latency = 0.0

            uptime = max(now - self.start_time, 0.1)

            return {
                "current_ingest_tps": round(current_ingest_tps, 1),
                "peak_ingest_tps": round(self.peak_ingest_tps, 1),
                "current_process_tps": round(current_process_tps, 1),
                "peak_process_tps": round(self.peak_process_tps, 1),
                "total_published": self.total_published,
                "total_processed": self.total_processed,
                "total_errors": self.total_errors,
                "backlog_size": backlog_size,
                "latency_p50_ms": round(p50, 2),
                "latency_p95_ms": round(p95, 2),
                "latency_p99_ms": round(p99, 2),
                "latency_avg_ms": round(avg_latency, 2),
                "uptime_seconds": round(uptime, 1),
            }
