"""Redis Streams Distributed Streaming Engine.

Uses Redis Streams (`XADD`, `XREADGROUP`, `XACK`) for multi-instance deployments.
Gracefully handles missing Redis instances with fallback.
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from streaming.base import BaseStreamEngine

logger = logging.getLogger("streaming.redis")


class RedisStreamEngine(BaseStreamEngine):
    """Distributed Redis Streams engine."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        group_name: str = "arvix_processors",
        consumer_name: str = "worker_1",
    ):
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._client = None
        self._initialized_groups = set()

    def _get_client(self):
        if self._client is None:
            import redis
            self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def _ensure_group(self, topic: str):
        if topic not in self._initialized_groups:
            client = self._get_client()
            try:
                client.xgroup_create(name=topic, groupname=self.group_name, id="0", mkstream=True)
            except Exception as e:
                # Group already exists
                if "BUSYGROUP" not in str(e):
                    logger.debug(f"Redis xgroup_create: {e}")
            self._initialized_groups.add(topic)

    def publish(self, topic: str, message: Dict[str, Any]) -> str:
        client = self._get_client()
        msg_json = json.dumps(message)
        msg_id = client.xadd(topic, {"payload": msg_json, "_published_at": time.time()})
        return str(msg_id)

    def publish_batch(self, topic: str, messages: List[Dict[str, Any]]) -> List[str]:
        if not messages:
            return []
        client = self._get_client()
        pipe = client.pipeline()
        now = time.time()
        for msg in messages:
            msg_json = json.dumps(msg)
            pipe.xadd(topic, {"payload": msg_json, "_published_at": now})
        results = pipe.execute()
        return [str(r) for r in results]

    def consume_batch(
        self,
        topic: str,
        batch_size: int = 100,
        timeout_ms: int = 50,
    ) -> List[Dict[str, Any]]:
        self._ensure_group(topic)
        client = self._get_client()

        entries = client.xreadgroup(
            groupname=self.group_name,
            consumername=self.consumer_name,
            streams={topic: ">"},
            count=batch_size,
            block=timeout_ms,
        )

        if not entries:
            return []

        messages = []
        ack_ids = []

        for stream_name, stream_entries in entries:
            for msg_id, data in stream_entries:
                ack_ids.append(msg_id)
                payload_str = data.get("payload", "{}")
                try:
                    payload = json.loads(payload_str)
                except Exception:
                    payload = data
                messages.append({
                    "_id": str(msg_id),
                    "_published_at": float(data.get("_published_at", time.time())),
                    "data": payload,
                })

        if ack_ids:
            client.xack(topic, self.group_name, *ack_ids)

        return messages

    def get_backlog_size(self, topic: str) -> int:
        client = self._get_client()
        try:
            return client.xlen(topic)
        except Exception:
            return 0

    def clear(self, topic: Optional[str] = None) -> None:
        client = self._get_client()
        if topic:
            client.delete(topic)
        else:
            self._initialized_groups.clear()
