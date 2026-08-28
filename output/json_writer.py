import json
import os


class JSONWriter:
    @staticmethod
    def write(transactions, path, indent=2):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(transactions, f, indent=indent, default=str)

    @staticmethod
    def write_jsonl(transactions, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for txn in transactions:
                f.write(json.dumps(txn, default=str) + "\n")
