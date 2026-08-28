import csv
import os


class CSVWriter:
    @staticmethod
    def write(transactions, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not transactions:
            return
        fieldnames = list(transactions[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(transactions)
