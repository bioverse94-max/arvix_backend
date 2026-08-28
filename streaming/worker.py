"""Background Streaming Consumer Worker.

Drains micro-batches from the streaming queue, validates schemas,
bulk writes to SQLite/PostgreSQL database, triggers alert evaluation,
and notifies connected WebSocket clients.
"""
import logging
import threading
import time
from typing import Callable, List, Optional

from api import alert_service
from api.database import SessionLocal
from api.models import Account, Transaction
from streaming.base import BaseStreamEngine
from streaming.metrics import StreamMetricsCollector

logger = logging.getLogger("streaming.worker")


class StreamingBatchWorker:
    """Consumes micro-batches of transactions from the stream engine and processes them."""

    def __init__(
        self,
        engine: BaseStreamEngine,
        metrics: StreamMetricsCollector,
        topic: str = "transactions.raw",
        batch_size: int = 100,
        poll_interval_ms: int = 20,
        on_processed_callback: Optional[Callable] = None,
    ):
        self.engine = engine
        self.metrics = metrics
        self.topic = topic
        self.batch_size = batch_size
        self.poll_interval_ms = poll_interval_ms
        self.on_processed_callback = on_processed_callback

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the background consumer thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ArvixStreamWorker")
        self._thread.start()
        logger.info(f"Stream consumer worker started on topic '{self.topic}'.")

    def stop(self):
        """Signal the worker to stop and wait for shutdown."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Stream consumer worker stopped.")

    def _run_loop(self):
        while self._running:
            try:
                batch = self.engine.consume_batch(
                    topic=self.topic,
                    batch_size=self.batch_size,
                    timeout_ms=self.poll_interval_ms,
                )
                if batch:
                    self._process_batch(batch)
            except Exception as e:
                logger.error(f"Error in stream consumer loop: {e}", exc_info=True)
                self.metrics.record_error(1)
                time.sleep(0.05)

    def _process_batch(self, raw_messages: List[dict]):
        now = time.time()
        latencies = []
        transactions_to_save = []
        alerts_to_evaluate = []

        db = SessionLocal()
        try:
            for msg in raw_messages:
                published_at = msg.get("_published_at", now)
                latencies.append(max((now - published_at) * 1000.0, 0.0))

                txn_dict = msg.get("data", {})
                if not txn_dict or "transaction_id" not in txn_dict:
                    continue

                transactions_to_save.append(txn_dict)
                if txn_dict.get("is_fraud"):
                    alerts_to_evaluate.append(txn_dict)

            # Bulk process DB writes
            for txn_dict in transactions_to_save:
                sender_id = txn_dict.get("sender_account_id")
                receiver_id = txn_dict.get("receiver_account_id")

                # Ensure sender stub exists
                if sender_id and not db.query(Account).filter_by(account_id=sender_id).first():
                    db.add(Account(account_id=sender_id, is_stub=True))

                # Ensure receiver stub exists
                if receiver_id and receiver_id != sender_id and not db.query(Account).filter_by(account_id=receiver_id).first():
                    db.add(Account(account_id=receiver_id, is_stub=True))

                from datetime import datetime
                try:
                    ts = datetime.fromisoformat(txn_dict["timestamp"].replace("Z", "+00:00"))
                except Exception:
                    ts = datetime.utcnow()

                # Check existing to prevent duplicate crash
                if not db.query(Transaction).filter_by(transaction_id=txn_dict["transaction_id"]).first():
                    db_txn = Transaction(
                        transaction_id=txn_dict["transaction_id"],
                        sender_account_id=sender_id,
                        receiver_account_id=receiver_id,
                        amount=txn_dict["amount"],
                        timestamp=ts,
                        status=txn_dict.get("status", "SUCCESS"),
                    )
                    db.add(db_txn)

                # Alert generation
                if alert_service.evaluate_transaction(txn_dict):
                    alert_service.create_alert(txn_dict, db)

            db.commit()

            # Record telemetry metrics
            self.metrics.record_processed(count=len(transactions_to_save), latencies_ms=latencies)

            # Broadcast to WebSocket listener if registered
            if self.on_processed_callback and transactions_to_save:
                try:
                    self.on_processed_callback(transactions_to_save)
                except Exception as cb_err:
                    logger.debug(f"Callback error: {cb_err}")

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to commit transaction batch: {e}", exc_info=True)
            self.metrics.record_error(len(raw_messages))
        finally:
            db.close()
