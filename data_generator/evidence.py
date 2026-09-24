"""Measure controlled scenarios from clean files, never from latent labels."""

import csv
import json
from array import array
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .storage import write_json


def read(root, table):
    for path in sorted((root / "clean_reference" / table).glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as stream:
            yield from csv.DictReader(stream)


def identifier(value, prefix):
    return int(value.removeprefix(prefix)) - 1


def evidence(output):
    root = Path(output)
    manifest = json.loads((root / "manifest.json").read_text())
    n = manifest["sizes"]
    start = date.fromisoformat(manifest["start"])
    days = (date.fromisoformat(manifest["end"]) - start).days
    orders = array("i", [0]) * (n["orders"] * 3)
    line_items = array("i", [0]) * (n["orders"] * 3)
    line_days = array("i", [0]) * (n["orders"] * 3)
    bundle_masks = bytearray(n["orders"])
    campaign_discount = {r["code"]: Decimal(r["discount_percent"]) for r in read(root, "promotions")}
    opportunity = Counter()
    for row in read(root, "orders"):
        index = identifier(row["code"], "O")
        local = (datetime.fromisoformat(row["ordered_at"]) + timedelta(hours=5)).date()
        day = (local - start).days
        orders[index * 3:index * 3 + 3] = array("i", [day, identifier(row["restaurant_code"], "R"), row["status"] == "completed"])
        if row["status"] == "completed":
            opportunity["early" if day < days // 3 else "late" if day >= 2 * days // 3 else "middle"] += 1
    stats = [Counter() for _ in range(n["items"])]
    for row in read(root, "order_items"):
        index = identifier(row["order_code"], "O")
        day, location, completed = orders[index * 3:index * 3 + 3]
        item = identifier(row["item_code"], "M")
        line = identifier(row["code"], "L")
        line_items[line], line_days[line] = item, day
        if not completed:
            continue
        stat = stats[item]
        quantity = int(row["quantity"])
        revenue = Decimal(row["unit_price"]) * quantity - Decimal(row["discount_amount"])
        margin = revenue - Decimal(row["unit_cost"]) * quantity
        stat["quantity"] += quantity
        stat["margin_cents"] += int(margin * 100)
        local = start + timedelta(days=day)
        stat["weekend" if local.weekday() >= 5 else "weekday"] += quantity
        stat["warm" if local.month in (5, 6, 7, 8) else "cool"] += quantity
        stat["even_locations" if location % 2 == 0 else "odd_locations"] += quantity
        stat["early" if day < days // 3 else "late" if day >= 2 * days // 3 else "middle"] += quantity
        stat["spike" if days // 2 <= day < days // 2 + 5 else "normal"] += quantity
        stat["first_day"] = min(stat.get("first_day", day), day)
        if row["promotion_code"] and campaign_discount[row["promotion_code"]] == 45:
            stat["trap_quantity"] += quantity
            stat["trap_margin_cents"] += int(margin * 100)
        if item in (12, 13):
            bundle_masks[index] |= 1 << (item - 12)
    for row in read(root, "wastage"):
        stats[identifier(row["item_code"], "M")]["waste"] += int(Decimal(row["wasted_quantity"]))
    for row in read(root, "ratings"):
        index = identifier(row["order_item_code"], "L")
        item, day = line_items[index], line_days[index]
        bucket = "spike_rating" if days // 2 <= day < days // 2 + 14 else "normal_rating"
        stats[item][bucket + "_sum"] += int(row["score"])
        stats[item][bucket + "_count"] += 1
    calendar = Counter()
    for day in range(days):
        current = start + timedelta(days=day)
        calendar["weekend" if current.weekday() >= 5 else "weekday"] += 1
        calendar["warm" if current.month in (5, 6, 7, 8) else "cool"] += 1
    ratio = lambda a, b: round(a / b, 4) if b else 0
    measures = {
        "loss_item_margin_pkr": stats[0]["margin_cents"] / 100,
        "loss_item_quantity": stats[0]["quantity"],
        "hidden_item_quantity": stats[1]["quantity"],
        "hidden_item_margin_pkr": stats[1]["margin_cents"] / 100,
        "hidden_item_waste": stats[1]["waste"],
        "waste_to_sales_high_waste_item": ratio(stats[2]["waste"], stats[2]["quantity"]),
        "waste_to_sales_reference_item": ratio(stats[0]["waste"], stats[0]["quantity"]),
        "trap_quantity": stats[5]["trap_quantity"],
        "trap_margin_pkr": stats[5]["trap_margin_cents"] / 100,
        "location_even_to_odd_sales": ratio(stats[6]["even_locations"], stats[6]["odd_locations"]),
        "weekend_to_weekday_daily_sales": ratio(stats[7]["weekend"] / calendar["weekend"], stats[7]["weekday"] / calendar["weekday"]),
        "warm_to_cool_daily_sales": ratio(stats[8]["warm"] / max(1, calendar["warm"]), stats[8]["cool"] / max(1, calendar["cool"])),
        "price_sensitive_early_per_order": ratio(stats[9]["early"], opportunity["early"]),
        "price_sensitive_late_per_order": ratio(stats[9]["late"], opportunity["late"]),
        "rating_spike_mean": ratio(stats[10]["spike_rating_sum"], stats[10]["spike_rating_count"]),
        "rating_normal_mean": ratio(stats[10]["normal_rating_sum"], stats[10]["normal_rating_count"]),
        "sales_spike_daily": stats[11]["spike"] / 5,
        "sales_normal_daily": stats[11]["normal"] / (days - 5),
        "bundle_orders": bundle_masks.count(3),
        "new_item_first_day": stats[-1].get("first_day"),
    }
    checks = {
        "loss_making_popular_item": stats[0]["margin_cents"] < 0 and stats[0]["quantity"] > stats[1]["quantity"] * 5,
        "low_volume_high_margin_item": stats[1]["margin_cents"] > 0 and stats[1]["waste"] == 0,
        "high_waste_popular_item": measures["waste_to_sales_high_waste_item"] > measures["waste_to_sales_reference_item"],
        "loss_making_discount_campaign": measures["trap_margin_pkr"] < 0 and measures["trap_quantity"] > 0,
        "location_difference": measures["location_even_to_odd_sales"] > 2,
        "weekend_pattern": measures["weekend_to_weekday_daily_sales"] > 2,
        "seasonal_pattern": measures["warm_to_cool_daily_sales"] > 2,
        "price_response": measures["price_sensitive_early_per_order"] > measures["price_sensitive_late_per_order"],
        "rating_spike": measures["rating_spike_mean"] > measures["rating_normal_mean"],
        "sales_spike": measures["sales_spike_daily"] > 2 * measures["sales_normal_daily"],
        "frequent_bundle": measures["bundle_orders"] > n["orders"] * .1,
        "new_item_history": measures["new_item_first_day"] is not None and measures["new_item_first_day"] >= days - 30,
    }
    report = {"measures": measures, "checks": checks, "all_passed": all(checks.values()),
              "note": "Generator scenario verification only; not model evaluation or production recommendations."}
    write_json(root / "evaluation" / "scenario_evidence.json", report)
    validation_path = root / "validation.json"
    if validation_path.exists() and json.loads(validation_path.read_text())["status"] == "passed":
        status_path = root / "run_status.json"
        status = json.loads(status_path.read_text())
        status["status"] = "validated" if report["all_passed"] or manifest["profile"] != "full" else "scenario_check_failed"
        status["scenario_checks_passed"] = report["all_passed"]
        write_json(status_path, status)
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    print(json.dumps(evidence(parser.parse_args().output), indent=2))
