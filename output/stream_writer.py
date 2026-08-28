import json
import time


class StreamWriter:
    """Simulates a streaming feed of transactions -- useful for exercising
    a downstream consumer, or as a drop-in point to wire up a real
    producer (Kafka, Kinesis, a websocket, etc.) by passing a custom sink."""

    def __init__(self, sink=None):
        # sink: callable(record: dict) -> None. Defaults to printing JSON lines.
        self.sink = sink or self._print_sink

    @staticmethod
    def _print_sink(record):
        print(json.dumps(record, default=str))

    def stream(self, transactions, delay_seconds=0.0, sorted_by_time=True):
        records = sorted(transactions, key=lambda t: t["timestamp"]) if sorted_by_time else transactions
        for record in records:
            self.sink(record)
            if delay_seconds:
                time.sleep(delay_seconds)

    def stream_to_file(self, transactions, path, sorted_by_time=True):
        records = sorted(transactions, key=lambda t: t["timestamp"]) if sorted_by_time else transactions
        with open(path, "w", encoding="utf-8") as f:
            old_sink, self.sink = self.sink, lambda record: f.write(json.dumps(record, default=str) + "\n")
            try:
                self.stream(records, delay_seconds=0.0, sorted_by_time=False)
            finally:
                self.sink = old_sink
