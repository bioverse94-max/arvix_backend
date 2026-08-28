"""In-Memory High-Throughput Streaming Engine.

Zero external dependencies required. Provides lock-safe ring buffer
and micro-batching queues capable of 10,000+ TPS in memory.
"""
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

from streaming.base import BaseStreamEngine


class InMemoryStreamEngine(BaseStreamEngine):
    """Ultra-fast in-memory streaming queue with thread-safe micro-batching."""

    def __init__(self, max_queue_size: int = 500_000):
        self.max_queue_size = max_queue_size
        self._queues: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_queue_size))
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._message_counter = 0

    def publish(self, topic: str, message: Dict[str, Any]) -> str:
        with self._not_empty:
            self._message_counter += 1
            msg_id = f"mem-{self._message_counter}-{uuid.uuid4().hex[:6]}"
            payload = {
                "_id": msg_id,
                "_published_at": time.time(),
                "data": message,
            }
            self._queues[topic].append(payload)
            self._not_empty.notify()
            return msg_id

    def publish_batch(self, topic: str, messages: List[Dict[str, Any]]) -> List[str]:
        if not messages:
            return []

        ids = []
        now = time.time()
        with self._not_empty:
            for msg in messages:
                self._message_counter += 1
                msg_id = f"mem-{self._message_counter}-{uuid.uuid4().hex[:6]}"
                payload = {
                    "_id": msg_id,
                    "_published_at": now,
                    "data": msg,
                }
                self._queues[topic].append(payload)
                ids.append(msg_id)
            self._not_empty.notify_all()
        return ids

    def consume_batch(
        self,
        topic: str,
        batch_size: int = 100,
        timeout_ms: int = 50,
    ) -> List[Dict[str, Any]]:
        deadline = time.time() + (timeout_ms / 1000.0)
        items = []

        with self._not_empty:
            q = self._queues[topic]
            while not q:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._not_empty.wait(timeout=remaining)

            count = min(len(q), batch_size)
            for _ in range(count):
                items.append(q.popleft())

        return items

    def get_backlog_size(self, topic: str) -> int:
        with self._lock:
            return len(self._queues.get(topic, []))

    def clear(self, topic: Optional[str] = None) -> None:
        with self._not_empty:
            if topic:
                if topic in self._queues:
                    self._queues[topic].clear()
            else:
                self._queues.clear()
            self._not_empty.notify_all()
