"""Independent streaming verification using a temporary, disk-backed index."""

import csv
import hashlib
import json
import sqlite3
import tempfile
import time
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .schemas import INTEGERS, MONEY, OPTIONAL, QUANTITIES, REFERENCES, SCHEMAS
from .storage import checksum, write_json


def fingerprint(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def rows(root, layer, table):
    paths = sorted((root / layer / table).glob("*.csv"))
    require(bool(paths), f"Missing {layer}/{table}")
    for path in paths:
        relative = path.relative_to(root).as_posix()
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            require(reader.fieldnames == SCHEMAS[table], f"Invalid schema: {path}")
            for number, row in enumerate(reader, 1):
                require(None not in row and None not in row.values(), f"Malformed CSV row: {path}:{number}")
                yield relative, number, row


def validate(output):
    root = Path(output).resolve()
    require(root.is_dir(), "Dataset directory does not exist")
    write_json(root / "validation.json", {"status": "running"})
    try:
        return _validate_run(root)
    except Exception as error:
        write_json(root / "validation.json", {"status": "failed", "error": str(error)})
        raise


def _validate_run(output):
    root = Path(output).resolve()
    started = time.perf_counter()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for relative, info in manifest["files"].items():
        path = (root / relative).resolve()
        require(path.is_relative_to(root), "Manifest file escapes dataset directory")
        require(path.is_file() and checksum(path) == info["sha256"], f"Checksum mismatch: {relative}")
    with tempfile.TemporaryDirectory(prefix="dineiq-validation-") as temp:
        connection = sqlite3.connect(str(Path(temp) / "index.sqlite3"))
        try:
            result = _validate(root, manifest, connection)
        finally:
            connection.close()
    result["seconds"] = round(time.perf_counter() - started, 3)
    write_json(root / "validation.json", result)
    return result


def _validate(root, manifest, db):
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("PRAGMA cache_size=-32768")
    counts = {}
    for table, fields in SCHEMAS.items():
        columns = ",".join(f'"{f}" TEXT' + (" PRIMARY KEY" if f == "code" else "") for f in fields)
        db.execute(f'CREATE TABLE "{table}" ({columns}, _hash TEXT, _seen INTEGER DEFAULT 0)')
        batch, count = [], 0
        statement = f'INSERT INTO "{table}" ({",".join(fields)},_hash) VALUES ({",".join("?" for _ in range(len(fields) + 1))})'
        for _, _, row in rows(root, "clean_reference", table):
            for field, value in row.items():
                if field in MONEY | QUANTITIES | INTEGERS | {"discount_percent"}:
                    try:
                        number = Decimal(value)
                        places = 0 if field in INTEGERS else 3 if field in QUANTITIES else 2
                        require(number.is_finite() and number >= 0 and number == number.quantize(Decimal(10) ** -places), f"Invalid numeric value: {table}.{field}")
                    except InvalidOperation as error:
                        raise ValueError(f"Invalid numeric value: {table}.{field}") from error
                if field.endswith("_at"):
                    require(datetime.fromisoformat(value).utcoffset() is not None, "Timestamp must have timezone")
                elif field in ("date", "joined_on", "introduced_on"):
                    date.fromisoformat(value)
                elif field == "code" or field.endswith("_code"):
                    if (table, field) not in OPTIONAL and field != "coupon_code":
                        require(bool(value), f"Missing {table}.{field}")
            values = [row[f] for f in fields]
            batch.append(values + [fingerprint(values)])
            count += 1
            if len(batch) == 2000:
                db.executemany(statement, batch)
                batch.clear()
        if batch:
            db.executemany(statement, batch)
        require(count == manifest["counts"][f"clean_reference/{table}"], f"Count mismatch: {table}")
        counts[table] = count
        db.commit()
        print(f"Indexed clean {table}: {count:,}", flush=True)

    def no_rows(sql, label):
        check_started = time.perf_counter()
        require(db.execute(sql + " LIMIT 1").fetchone() is None, label)
        if time.perf_counter() - check_started > 1:
            print(f"Check passed: {label} ({time.perf_counter() - check_started:.1f}s)", flush=True)

    for table, references in REFERENCES.items():
        for field, target in references.items():
            optional = f"s.{field} != '' AND " if (table, field) in OPTIONAL else ""
            no_rows(f"SELECT s.code FROM {table} s LEFT JOIN {target} t ON s.{field}=t.code WHERE {optional}t.code IS NULL", f"Broken FK {table}.{field}")

    for table in ("pricing_history", "order_items", "wastage"):
        no_rows(f"SELECT code FROM {table} WHERE CAST(unit_cost AS REAL)<0", f"Negative cost: {table}")
    for table in ("pricing_history", "order_items"):
        no_rows(f"SELECT code FROM {table} WHERE CAST(unit_price AS REAL)<0", f"Negative price: {table}")
    no_rows("SELECT code FROM order_items WHERE CAST(quantity AS INTEGER)<=0 OR CAST(line_number AS INTEGER)<=0 OR CAST(discount_amount AS REAL)<0 OR CAST(discount_amount AS REAL)>CAST(quantity AS REAL)*CAST(unit_price AS REAL)", "Invalid line amounts")
    no_rows("SELECT order_code FROM order_items GROUP BY order_code,line_number HAVING COUNT(*)>1", "Duplicate order line")
    no_rows("SELECT code FROM promotions WHERE ends_at<=starts_at OR CAST(discount_percent AS REAL)<0 OR CAST(discount_percent AS REAL)>100", "Invalid campaign")
    no_rows("SELECT code FROM orders WHERE status NOT IN ('completed','cancelled')", "Invalid status")
    no_rows("SELECT o.code FROM orders o JOIN customers c ON c.code=o.customer_code WHERE substr(o.ordered_at,1,10)<c.joined_on", "Order predates customer")
    no_rows("SELECT o.code FROM orders o JOIN promotions p ON o.promotion_code=p.code WHERE o.ordered_at<p.starts_at OR o.ordered_at>=p.ends_at", "Inactive campaign")
    no_rows("SELECT r.code FROM ratings r JOIN order_items l ON l.code=r.order_item_code JOIN orders o ON o.code=l.order_code WHERE CAST(r.score AS INTEGER) NOT BETWEEN 1 AND 5 OR r.rated_at<o.ordered_at OR o.status!='completed'", "Invalid purchase rating")
    no_rows("SELECT order_item_code FROM ratings GROUP BY order_item_code HAVING COUNT(*)>1", "Duplicate rating")
    no_rows("SELECT restaurant_code FROM pricing_history GROUP BY restaurant_code,item_code,effective_at HAVING COUNT(*)>1", "Duplicate price event")
    db.execute("CREATE INDEX price_lookup ON pricing_history(restaurant_code,item_code,effective_at)")
    no_rows("SELECT l.code FROM order_items l JOIN orders o ON o.code=l.order_code JOIN menu_items m ON m.code=l.item_code WHERE substr(datetime(o.ordered_at,'+5 hours'),1,10)<m.introduced_on", "Sale before launch")
    no_rows("SELECT l.code FROM order_items l JOIN orders o ON o.code=l.order_code LEFT JOIN pricing_history p ON p.code=(SELECT code FROM pricing_history h WHERE h.restaurant_code=o.restaurant_code AND h.item_code=l.item_code AND h.effective_at<=o.ordered_at ORDER BY h.effective_at DESC LIMIT 1) WHERE p.code IS NULL OR p.unit_price!=l.unit_price OR p.unit_cost!=l.unit_cost", "Price snapshot does not match effective history")
    no_rows("SELECT l.code FROM order_items l JOIN orders o ON o.code=l.order_code LEFT JOIN promotions p ON l.promotion_code=p.code WHERE (l.promotion_code!='' AND (l.promotion_code!=o.promotion_code OR NOT EXISTS(SELECT 1 FROM promotion_items pi WHERE pi.promotion_code=l.promotion_code AND pi.item_code=l.item_code) OR round(CAST(l.discount_amount AS REAL)*100)!=CAST((round(CAST(l.unit_price AS REAL)*100)*CAST(l.quantity AS INTEGER)*round(CAST(p.discount_percent AS REAL)*100)+5000)/10000 AS INTEGER))) OR (l.promotion_code='' AND CAST(l.discount_amount AS REAL)!=0)", "Incorrect campaign attribution")
    for table in ("order_items", "inventory", "wastage"):
        no_rows(f"SELECT code FROM {table} WHERE unit!='portion'", f"Invalid clean unit: {table}")
    no_rows("SELECT code FROM wastage WHERE CAST(wasted_quantity AS REAL)<0 OR CAST(prepared_quantity AS REAL)<CAST(wasted_quantity AS REAL)", "Impossible waste")
    no_rows("SELECT code FROM inventory WHERE CAST(opening_quantity AS REAL)<0 OR CAST(replenished_quantity AS REAL)<0 OR CAST(consumed_quantity AS REAL)<0 OR CAST(consumed_quantity AS REAL)>CAST(opening_quantity AS REAL)+CAST(replenished_quantity AS REAL)", "Impossible inventory")
    no_rows("SELECT restaurant_code FROM inventory GROUP BY restaurant_code,item_code,date HAVING COUNT(*)>1", "Duplicate inventory")
    db.execute("CREATE TABLE daily_sales AS SELECT o.restaurant_code,l.item_code,substr(datetime(o.ordered_at,'+5 hours'),1,10) date,SUM(CAST(l.quantity AS REAL)) quantity FROM order_items l JOIN orders o ON o.code=l.order_code WHERE o.status='completed' GROUP BY o.restaurant_code,l.item_code,date")
    db.execute("CREATE UNIQUE INDEX sales_lookup ON daily_sales(restaurant_code,item_code,date)")
    db.execute("CREATE TABLE daily_waste AS SELECT restaurant_code,item_code,substr(datetime(recorded_at,'+5 hours'),1,10) date,SUM(CAST(wasted_quantity AS REAL)) quantity FROM wastage GROUP BY restaurant_code,item_code,date")
    db.execute("CREATE UNIQUE INDEX waste_lookup ON daily_waste(restaurant_code,item_code,date)")
    no_rows("SELECT i.code FROM inventory i LEFT JOIN daily_sales s ON s.restaurant_code=i.restaurant_code AND s.item_code=i.item_code AND s.date=i.date LEFT JOIN daily_waste w ON w.restaurant_code=i.restaurant_code AND w.item_code=i.item_code AND w.date=i.date WHERE abs(CAST(i.consumed_quantity AS REAL)-coalesce(s.quantity,0)-coalesce(w.quantity,0))>0.0001", "Inventory does not reconcile with completed sales and waste")
    no_rows("SELECT code FROM (SELECT code,CAST(opening_quantity AS REAL) opening,lag(CAST(opening_quantity AS REAL)+CAST(replenished_quantity AS REAL)-CAST(consumed_quantity AS REAL)) OVER (PARTITION BY restaurant_code,item_code ORDER BY date) previous FROM inventory) WHERE previous IS NOT NULL AND abs(opening-previous)>0.0001", "Broken inventory continuity")

    # Every raw difference must be explained by an exact file/row entry in the ledger.
    ledger = {}
    issue_counts = Counter()
    with (root / "evaluation" / "corruption.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            entry = json.loads(line)
            key = (entry["file"], entry["row_number"])
            require(key not in ledger, "Duplicate ledger address")
            ledger[key] = entry
            issue_counts[entry["kind"]] += 1
    require(dict(issue_counts) == manifest["issues"], "Issue totals differ")
    duplicates = Counter()
    for table, fields in SCHEMAS.items():
        raw_count = 0
        for path, number, row in rows(root, "raw", table):
            raw_count += 1
            issue = ledger.pop((path, number), None)
            if issue:
                require(issue["table"] == table and row["code"] == issue["code"], "Incorrect ledger target")
                if issue["field"]:
                    require(row[issue["field"]] == issue["after"], "Incorrect ledger change")
                    row[issue["field"]] = issue["before"]
                else:
                    duplicates[table, row["code"]] += 1
            digest = fingerprint([row[f] for f in fields])
            affected = db.execute(f"UPDATE {table} SET _seen=_seen+1 WHERE code=? AND _hash=?", (row["code"], digest)).rowcount
            require(affected == 1, f"Unexplained raw difference: {path}:{number}")
        require(raw_count == manifest["counts"][f"raw/{table}"], f"Raw count mismatch: {table}")
        for (target, identifier), amount in duplicates.items():
            if target == table:
                require(db.execute(f"SELECT _seen FROM {table} WHERE code=?", (identifier,)).fetchone()[0] == 1 + amount, "Wrong duplicate multiplicity")
                db.execute(f"UPDATE {table} SET _seen=1 WHERE code=?", (identifier,))
        no_rows(f"SELECT code FROM {table} WHERE _seen!=1", f"Missing or unexplained duplicate in {table}")
        db.commit()
        print(f"Verified raw {table}: {raw_count:,}", flush=True)
    require(not ledger, "Ledger references missing raw rows")

    targets = manifest["sizes"]
    mapping = {"customers": "customers", "orders": "orders", "order_items": None, "menu_items": "items", "menu_categories": "categories", "restaurants": "locations", "ratings": "ratings", "wastage": "wastage", "promotions": "promotions"}
    for table, key in mapping.items():
        require(counts[table] == (targets[key] if key else targets["orders"] * 3), f"Profile target not met: {table}")
    full = manifest["profile"] == "full"
    actual_start, actual_end = db.execute("SELECT MIN(ordered_at),MAX(ordered_at) FROM orders").fetchone()
    actual_days = (datetime.fromisoformat(actual_end).date() - datetime.fromisoformat(actual_start).date()).days
    if full:
        require((date.fromisoformat(manifest["end"]) - date.fromisoformat(manifest["start"])).days >= 365, "Full data needs 12 months")
        require(actual_days >= 364, "Actual transactions do not cover 12 months")
    summary = {"status": "passed", "srs_scale_met": full, "counts": counts, "corruption_issues": dict(issue_counts),
               "actual_order_range": {"first": actual_start, "last": actual_end}}
    print("All schema, relationship, accounting and corruption checks passed.", flush=True)
    return summary
