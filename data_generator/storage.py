"""Streaming CSV output with separately recorded, deterministic corruption."""

import csv
import hashlib
import json
import random
from collections import Counter

from .schemas import SCHEMAS, TRANSACTIONS

ISSUES = {
    "orders": [("customer_code", "", "missing_customer"), ("restaurant_code", "UNKNOWN", "unknown_location"), ("ordered_at", "not-a-date", "invalid_date"), (None, None, "duplicate_order")],
    "order_items": [("quantity", "-2", "negative_quantity"), ("unit_price", "-20", "invalid_price"), ("item_code", "UNKNOWN", "unknown_item"), ("discount_amount", "999999999.00", "excess_discount"), ("unit", "kg", "inconsistent_unit"), ("item_code", "", "missing_item"), (None, None, "duplicate_line")],
    "ratings": [("score", "9", "invalid_rating")],
    "wastage": [("wasted_quantity", "9999999", "impossible_wastage")],
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Writer:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.random = random.Random(config.seed + 7919)
        self.handles, self.writers = {}, {}
        self.keys = {}
        self.counts, self.file_rows, self.issues = Counter(), Counter(), Counter()
        self.samples = {}
        self.ledger = (root / "evaluation" / "corruption.jsonl").open("w", encoding="utf-8")

    def _write(self, layer, table, row, month):
        bucket = (layer, table, month if table in TRANSACTIONS else None)
        key = self.keys.get(bucket)
        if key is None:
            part = f"{month}.csv" if table in TRANSACTIONS else "part-000.csv"
            path = self.root / layer / table / part
            key = path.relative_to(self.root).as_posix()
            self.keys[bucket] = key
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("w", newline="", encoding="utf-8")
            writer = csv.DictWriter(handle, fieldnames=SCHEMAS[table], lineterminator="\n")
            writer.writeheader()
            self.handles[key], self.writers[key] = handle, writer
        self.writers[key].writerow(row)
        self.file_rows[key] += 1
        self.counts[f"{layer}/{table}"] += 1
        return key, self.file_rows[key]

    def emit(self, table, row, month=None):
        row = {key: str(row.get(key, "")) for key in SCHEMAS[table]}
        if not month and table in TRANSACTIONS:
            month = row[TRANSACTIONS[table]][:7]
        self._write("clean_reference", table, row, month)
        if table not in self.samples:
            self.samples[table] = []
        if len(self.samples[table]) < 3:
            self.samples[table].append(row)
        altered = row.copy()
        issue = None
        if table in ISSUES and self.random.random() < self.config.corruption_rate:
            field, value, kind = self.random.choice(ISSUES[table])
            issue = {"table": table, "code": row["code"], "field": field, "kind": kind,
                     "before": row.get(field), "after": value}
            if field:
                altered[field] = value
            else:
                self._write("raw", table, row, month)
        key, number = self._write("raw", table, altered, month)
        if issue:
            issue.update(file=key, row_number=number)
            self.ledger.write(json.dumps(issue, sort_keys=True) + "\n")
            self.issues[issue["kind"]] += 1

    def close(self):
        for handle in self.handles.values():
            handle.close()
        self.ledger.close()

    def finish(self):
        self.close()
        write_json(self.root / "samples.json", self.samples)
        return {"counts": dict(self.counts), "issues": dict(self.issues),
                "files": {p.relative_to(self.root).as_posix(): {"sha256": checksum(p), "bytes": p.stat().st_size}
                          for p in sorted(self.root.rglob("*.csv"))}}
