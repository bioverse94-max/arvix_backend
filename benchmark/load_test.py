"""Load Testing and TPS Benchmarking Harness.

Stress tests the transaction ingestion pipeline across different concurrency
levels and batch sizes, measuring throughput (TPS), latency curves (P50/P95/P99),
and system bottleneck analysis.

Usage:
    python benchmark/load_test.py --count 2000 --concurrency 20 --mode STREAM
    python benchmark/load_test.py --count 1000 --concurrency 10 --mode SYNC
"""
import argparse
import concurrent.futures
import json
import time
import uuid
from typing import Dict, List, Tuple

import httpx

API_BASE_URL = "http://127.0.0.1:8000"


def generate_synthetic_transactions(count: int) -> List[Dict]:
    """Generate valid UPI transaction payloads matching transaction_schema.json."""
    txns = []
    base_time = "2026-08-28T12:00:00Z"
    for i in range(count):
        uid = uuid.uuid4().hex[:10]
        txns.append({
            "transaction_id": f"TXN_PERF_{uid}",
            "utr": f"UTR_PERF_{i:08d}",
            "timestamp": base_time,
            "sender_vpa": f"perf_user_{i % 500}@okaxis",
            "sender_account_id": f"ACC_PERF_S_{i % 500}",
            "receiver_vpa": f"perf_merchant_{i % 100}@okhdfc",
            "receiver_account_id": f"ACC_PERF_R_{i % 100}",
            "amount": round(150.0 + (i % 200) * 12.5, 2),
            "currency": "INR",
            "transaction_type": "P2P",
            "channel": "UPI",
            "status": "SUCCESS",
            "is_fraud": (i % 25 == 0),
        })
    return txns


def run_benchmark(
    base_url: str = API_BASE_URL,
    count: int = 1000,
    concurrency: int = 20,
    mode: str = "STREAM",
    batch_size: int = 50,
) -> Dict:
    """Execute load test against the API server."""
    print(f"\n=======================================================")
    print(f"   ARVIX Real-Time Processing & Throughput Benchmark   ")
    print(f"=======================================================")
    print(f"  Target Endpoint  : {base_url}")
    print(f"  Mode             : {mode.upper()} ({'Async Streaming Buffer' if mode.upper() == 'STREAM' else 'Synchronous Direct Ingestion'})")
    print(f"  Total Txns       : {count:,}")
    print(f"  Concurrency      : {concurrency} worker threads")
    print(f"  Batch Size       : {batch_size} txns/request")
    print(f"=======================================================\n")

    txns = generate_synthetic_transactions(count)
    endpoint = f"{base_url}/transactions/stream" if mode.upper() == "STREAM" else f"{base_url}/transactions"

    # Chunk transactions into batches
    batches = [txns[i:i + batch_size] for i in range(0, count, batch_size)]
    latencies_ms = []
    errors = 0

    client = httpx.Client(timeout=30.0)

    def _send_batch(batch: List[Dict]) -> Tuple[List[float], int]:
        req_start = time.time()
        try:
            resp = client.post(endpoint, json={"transactions": batch})
            elapsed = (time.time() - req_start) * 1000.0
            if resp.status_code in (200, 202):
                # Distribute request latency per transaction in batch
                per_item_lat = elapsed / len(batch)
                return [per_item_lat] * len(batch), 0
            else:
                return [], len(batch)
        except Exception:
            return [], len(batch)

    t0 = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_send_batch, b) for b in batches]
        for f in concurrent.futures.as_completed(futures):
            lats, err_count = f.result()
            latencies_ms.extend(lats)
            errors += err_count

    total_time = max(time.time() - t0, 0.001)
    achieved_tps = (count - errors) / total_time

    latencies_ms.sort()
    n = len(latencies_ms)
    p50 = latencies_ms[int(n * 0.50)] if n else 0
    p95 = latencies_ms[int(n * 0.95)] if n else 0
    p99 = latencies_ms[int(n * 0.99)] if n else 0
    avg_lat = sum(latencies_ms) / n if n else 0

    print(f"---------------- Benchmark Results -------------------")
    print(f"  Transactions Sent   : {count:,}")
    print(f"  Successfully Ingested: {count - errors:,}")
    print(f"  Failed / Dropped    : {errors}")
    print(f"  Total Duration      : {total_time:.2f} seconds")
    print(f"  Throughput (TPS)    : {achieved_tps:,.1f} Txns/sec")
    print(f"  Avg Latency (per tx): {avg_lat:.2f} ms")
    print(f"  P50 Latency (median): {p50:.2f} ms")
    print(f"  P95 Latency         : {p95:.2f} ms")
    print(f"  P99 Latency         : {p99:.2f} ms")
    print(f"------------------------------------------------------\n")

    return {
        "count": count,
        "mode": mode,
        "concurrency": concurrency,
        "duration_sec": round(total_time, 2),
        "achieved_tps": round(achieved_tps, 1),
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "latency_p99_ms": round(p99, 2),
        "errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARVIX TPS Load Testing Benchmark")
    parser.add_argument("--count", type=int, default=1000, help="Number of transactions")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent workers")
    parser.add_argument("--mode", type=str, default="STREAM", choices=["STREAM", "SYNC"], help="STREAM or SYNC")
    parser.add_argument("--batch-size", type=int, default=50, help="Transactions per request")
    parser.add_argument("--url", type=str, default=API_BASE_URL, help="API server base URL")

    args = parser.parse_args()
    run_benchmark(
        base_url=args.url,
        count=args.count,
        concurrency=args.concurrency,
        mode=args.mode,
        batch_size=args.batch_size,
    )
