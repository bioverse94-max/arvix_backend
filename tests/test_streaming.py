"""Automated tests for Real-Time Processing, Streaming Ingestion, and TPS Telemetry (Stage 10).

Covers:
- In-Memory Stream Engine publishing & micro-batch consumption
- Stream Metrics Collector TPS & latency percentiles
- Background Streaming Worker DB persistence & alert generation
- POST /transactions/stream async ingestion endpoint
- GET /stream/metrics telemetry endpoint
- POST /stream/benchmark in-API load test execution
"""
import time
import uuid
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.database import SessionLocal
from api.models import Transaction, Alert, Account, FraudCase, CaseEvent, FraudResult, User, AuditLog
import streaming
from streaming.memory_stream import InMemoryStreamEngine
from streaming.metrics import StreamMetricsCollector
from streaming.worker import StreamingBatchWorker

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    """Clean all tables before each test."""
    db = SessionLocal()
    db.query(AuditLog).delete()
    db.query(User).delete()
    db.query(CaseEvent).delete()
    db.query(FraudCase).delete()
    db.query(FraudResult).delete()
    db.query(Alert).delete()
    db.query(Transaction).delete()
    db.query(Account).delete()
    db.commit()
    db.close()
    yield


# ── 1. In-Memory Streaming Engine Unit Tests ───────────────────────────

class TestInMemoryStreamEngine:

    def test_publish_and_consume_single(self):
        engine = InMemoryStreamEngine()
        msg_id = engine.publish("test.topic", {"amount": 500, "txn_id": "TXN_1"})
        assert msg_id.startswith("mem-")
        assert engine.get_backlog_size("test.topic") == 1

        batch = engine.consume_batch("test.topic", batch_size=10, timeout_ms=50)
        assert len(batch) == 1
        assert batch[0]["data"]["amount"] == 500
        assert engine.get_backlog_size("test.topic") == 0

    def test_publish_batch_and_consume_micro_batches(self):
        engine = InMemoryStreamEngine()
        messages = [{"txn_id": f"TXN_{i}", "val": i} for i in range(25)]
        msg_ids = engine.publish_batch("test.batch", messages)

        assert len(msg_ids) == 25
        assert engine.get_backlog_size("test.batch") == 25

        # Consume first micro-batch of 10
        batch1 = engine.consume_batch("test.batch", batch_size=10, timeout_ms=50)
        assert len(batch1) == 10
        assert engine.get_backlog_size("test.batch") == 15

        # Consume second micro-batch of 10
        batch2 = engine.consume_batch("test.batch", batch_size=10, timeout_ms=50)
        assert len(batch2) == 10
        assert engine.get_backlog_size("test.batch") == 5

        # Consume remaining 5
        batch3 = engine.consume_batch("test.batch", batch_size=10, timeout_ms=50)
        assert len(batch3) == 5
        assert engine.get_backlog_size("test.batch") == 0


# ── 2. Stream Metrics Collector Tests ──────────────────────────────────

class TestStreamMetricsCollector:

    def test_metrics_calculation(self):
        metrics = StreamMetricsCollector(window_seconds=2.0)
        metrics.record_published(count=50)
        metrics.record_processed(count=40, latencies_ms=[5.0, 10.0, 15.0, 20.0, 25.0])

        snapshot = metrics.get_snapshot(backlog_size=10)
        assert snapshot["total_published"] == 50
        assert snapshot["total_processed"] == 40
        assert snapshot["backlog_size"] == 10
        assert snapshot["latency_p50_ms"] == 15.0
        assert snapshot["latency_avg_ms"] == 15.0
        assert snapshot["current_ingest_tps"] > 0


# ── 3. Streaming Worker DB Integration Tests ───────────────────────────

class TestStreamingWorker:

    def test_worker_processes_and_saves_transactions(self):
        engine = InMemoryStreamEngine()
        metrics = StreamMetricsCollector()
        processed_txns = []

        def callback(txns):
            processed_txns.extend(txns)

        worker = StreamingBatchWorker(
            engine=engine,
            metrics=metrics,
            topic="test.worker",
            batch_size=50,
            poll_interval_ms=10,
            on_processed_callback=callback,
        )
        worker.start()

        try:
            # Publish 5 transactions
            txns = [
                {
                    "transaction_id": f"TXN_WORKER_{i}_{uuid.uuid4().hex[:6]}",
                    "sender_account_id": f"ACC_S_{i}",
                    "receiver_account_id": f"ACC_R_{i}",
                    "amount": 1000.0 * (i + 1),
                    "timestamp": "2026-08-28T12:00:00Z",
                    "status": "SUCCESS",
                    "is_fraud": (i == 0),
                }
                for i in range(5)
            ]
            engine.publish_batch("test.worker", txns)

            # Wait for worker to drain
            time.sleep(0.3)

            # Check DB
            db = SessionLocal()
            saved_count = db.query(Transaction).count()
            db.close()
            assert saved_count == 5
            assert len(processed_txns) == 5

        finally:
            worker.stop()


# ── 4. Streaming API Endpoints ─────────────────────────────────────────

class TestStreamingAPIEndpoints:

    def test_post_transactions_stream_endpoint(self):
        txn = {
            "transaction_id": f"TXN_STREAM_{uuid.uuid4().hex[:8]}",
            "utr": "UTR_STREAM_001",
            "timestamp": "2026-08-28T12:00:00Z",
            "sender_vpa": "stream_user@okaxis",
            "sender_account_id": "ACC_STR_S",
            "receiver_vpa": "stream_recv@okhdfc",
            "receiver_account_id": "ACC_STR_R",
            "amount": 7500.0,
            "currency": "INR",
            "transaction_type": "P2P",
            "channel": "UPI",
            "status": "SUCCESS",
            "is_fraud": False,
        }
        resp = client.post("/transactions/stream", json=txn)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["accepted_count"] == 1
        assert len(data["stream_message_ids"]) >= 1

    def test_get_stream_metrics_endpoint(self):
        resp = client.get("/stream/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "current_ingest_tps" in data
        assert "latency_p50_ms" in data
        assert "engine_type" in data

    def test_post_stream_benchmark_endpoint(self):
        req = {
            "transaction_count": 50,
            "concurrency": 5,
            "mode": "STREAM",
        }
        resp = client.post("/stream/benchmark", json=req)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_transactions"] == 50
        assert data["achieved_tps"] > 0
        assert data["status"] == "SUCCESS"
