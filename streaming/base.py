"""Abstract base class for streaming engines (Kafka, Redis Streams, In-Memory)."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseStreamEngine(ABC):
    """Abstract interface for high-throughput transaction streaming backends."""

    @abstractmethod
    def publish(self, topic: str, message: Dict[str, Any]) -> str:
        """Publish a single transaction message to the specified topic.
        Returns a unique message/offset ID.
        """
        pass

    @abstractmethod
    def publish_batch(self, topic: str, messages: List[Dict[str, Any]]) -> List[str]:
        """Publish a batch of transaction messages to the specified topic.
        Returns a list of unique message/offset IDs.
        """
        pass

    @abstractmethod
    def consume_batch(
        self,
        topic: str,
        batch_size: int = 100,
        timeout_ms: int = 50,
    ) -> List[Dict[str, Any]]:
        """Consume a micro-batch of messages from the topic.
        Blocks for up to timeout_ms if the queue is empty.
        """
        pass

    @abstractmethod
    def get_backlog_size(self, topic: str) -> int:
        """Return the number of unconsumed messages in the topic backlog."""
        pass

    @abstractmethod
    def clear(self, topic: Optional[str] = None) -> None:
        """Purge all messages from topic (or all topics). Primarily for testing."""
        pass
