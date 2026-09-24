"""Generate linked restaurant activity without holding transaction rows in memory."""

import bisect
import json
import math
import random
import time
from array import array
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from itertools import accumulate
from pathlib import Path

from .config import VERSION
from .schemas import SCHEMAS, REFERENCES, field_type
from .storage import Writer, write_json

CATEGORIES = ["Rice Meals", "Grill", "Burgers", "Pizza", "Pasta", "Salads", "Soups", "Sides", "Desserts", "Hot Drinks", "Cold Drinks", "Breakfast"]
ITEMS = ["Chicken Biryani", "Beef Kebab", "Classic Burger", "Margherita Pizza", "Creamy Pasta", "Garden Salad", "Lentil Soup", "Seasoned Fries", "Chocolate Cake", "Karak Chai", "Lemonade", "Omelette"]
SCENARIOS = {0: "high_sales_loss", 1: "hidden_opportunity", 2: "excess_wastage", 3: "high_rating_low_margin", 4: "low_rating_high_sales", 5: "promotion_dependency", 6: "location_difference", 7: "weekend_demand", 8: "seasonality", 9: "price_sensitivity", 10: "rating_spike", 11: "sales_spike"}
SEGMENTS = ["loyal", "frequent", "promotion_driven", "at_risk", "occasional", "new"]


def code(prefix, index):
    return f"{prefix}{index + 1:07d}"


def money(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def generate(config, output):
    root = Path(output).resolve()
    # Refuse even empty existing directories so retries cannot overwrite a prior run.
    root.mkdir(parents=True, exist_ok=False)
    (root / "evaluation").mkdir()
    write_json(root / "run_status.json", {"status": "running", "config": config.manifest()})
    started = time.perf_counter()
    writer = Writer(root, config)
    try:
        metrics = _generate(config, writer)
        manifest = config.manifest() | writer.finish() | {"schema_version": VERSION}
        write_json(root / "manifest.json", manifest)
        write_json(root / "schemas.json", {"fields": SCHEMAS, "references": REFERENCES,
                   "types": {table: {f: field_type(f) for f in fields} for table, fields in SCHEMAS.items()},
                   "currency": "PKR", "unit": "portion", "timezone": "Asia/Karachi"})
        write_json(root / "evaluation" / "business_metrics.json", metrics)
        write_json(root / "run_status.json", {"status": "generated_pending_validation", "seconds": round(time.perf_counter() - started, 3)})
        return manifest
    except Exception as error:
        writer.close()
        write_json(root / "run_status.json", {"status": "failed", "error": str(error)})
        raise


def _generate(config, out):
    rng = random.Random(config.seed)
    n = config.sizes
    start = date.fromisoformat(config.start)
    days = (date.fromisoformat(config.end) - start).days
    locations, items = n["locations"], n["items"]
    cells = days * locations * items
    sales = array("I", [0]) * cells
    dates = [start + timedelta(days=d) for d in range(days)]
    # Noon/dinner refer to restaurant local time; CSV timestamps are normalized UTC.
    local_zone = timezone(timedelta(hours=5))

    def stamp(day, hour=0, minute=0):
        return datetime.combine(dates[day], datetime.min.time(), local_zone).replace(hour=hour, minute=minute).astimezone(timezone.utc).isoformat()

    def position(day, location, item):
        return (day * locations + location) * items + item

    for i in range(locations):
        city = ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad", "Multan"][i % 6]
        out.emit("restaurants", dict(code=code("R", i), name=f"DineIQ {city} {i + 1}", city=city,
                                      address=f"Synthetic branch {i + 1}", timezone="Asia/Karachi", is_active=True))
    for i, name in enumerate(CATEGORIES[:n["categories"]]):
        out.emit("menu_categories", dict(code=code("C", i), name=name, description=f"{name} category"))
    for i in range(items):
        out.emit("menu_items", dict(code=code("M", i), category_code=code("C", i % n["categories"]),
                                   name=f"{ITEMS[i % len(ITEMS)]} {i // len(ITEMS) + 1}", description="Synthetic menu item",
                                   is_available=True, introduced_on=dates[days - 30 if i == items - 1 else 0]))
    for i, name in enumerate(["Dine-in", "Takeaway", "Website/App", "Third-party Delivery"]):
        out.emit("ordering_channels", dict(code=code("CH", i), name=name))

    joins, segments = [], []
    with (out.root / "evaluation" / "customer_scenarios.csv").open("w", encoding="utf-8", newline="") as stream:
        import csv
        labels = csv.writer(stream, lineterminator="\n")
        labels.writerow(["customer_code", "latent_segment"])
        for i in range(n["customers"]):
            segment = i % len(SEGMENTS)
            joined = days - 30 + rng.randrange(15) if segment == 5 else rng.randrange(30)
            joins.append(joined)
            segments.append(segment)
            out.emit("customers", dict(code=code("CU", i), joined_on=dates[joined], cohort="synthetic"))
            labels.writerow([code("CU", i), SEGMENTS[segment]])

    epochs = [0, days // 3, 2 * days // 3]
    prices, costs = {}, {}
    for location in range(locations):
        for item in range(items):
            base = 18000 + (item % 20) * 2700 + location * 150
            for epoch, day in enumerate(epochs):
                if item == items - 1:
                    if epoch:
                        continue
                    day = days - 30
                multiplier = 1 + epoch * (0.30 if item == 9 else 0.04)
                price = round(base * multiplier)
                ratio = 1.14 if item == 0 else 0.95 if item == 3 else 0.65 if item == 5 else 0.22 if item == 1 else 0.40 + (item % 5) * 0.07
                cost = round(base * ratio * (1 + 0.025 * epoch))
                prices[location, item, epoch], costs[location, item, epoch] = price, cost
                out.emit("pricing_history", dict(code=f"P{location:03d}-{item:03d}-{epoch}", restaurant_code=code("R", location), item_code=code("M", item), effective_at=stamp(day), unit_price=money(price), unit_cost=money(cost)))

    campaigns = []
    active = [[] for _ in range(days)]
    for i in range(n["promotions"]):
        day = 30 + i * (days - 65) // n["promotions"]
        end = min(days - 1, day + 14)
        discount = 45 if i % 3 == 0 else 15 + i % 3 * 5
        eligible = {5, 12, 13, 14 + i % (items - 15)}
        campaigns.append((day, end, discount, eligible))
        out.emit("promotions", dict(code=code("PR", i), name=f"Seasonal offer {i + 1}", coupon_code=f"DINE{i + 1}", starts_at=stamp(day), ends_at=stamp(end), discount_percent=f"{discount}.00"))
        for item in sorted(eligible):
            out.emit("promotion_items", dict(code=f"PM{i:03d}-{item:03d}", promotion_code=code("PR", i), item_code=code("M", item)))
        for d in range(day, end):
            active[d].append(i)

    # Latent causes remain in evaluation files, never in predictive input columns.
    write_json(out.root / "evaluation" / "item_scenarios.json", {
        "items": {code("M", i): name for i, name in SCENARIOS.items()} | {code("M", items - 1): "new_item"},
        "bundle": [code("M", 12), code("M", 13)], "trap_campaigns": [code("PR", i) for i in range(n["promotions"]) if i % 3 == 0],
    })

    @lru_cache(maxsize=days * locations)
    def weights(day, location):
        epoch = bisect.bisect_right(epochs, day) - 1
        result = []
        for item in range(items):
            weight = [8, .14, 7, 3, 6, .35, 2, 1, 2, 2, 2, 2][item] if item < 12 else 1.0
            weight *= 1.5 if item % 6 == location % 6 else 1
            if item == 5 and active[day]:
                weight *= 16
            if item == 6:
                weight *= 4 if location % 2 == 0 else .15
            if item == 7:
                weight *= 7 if dates[day].weekday() >= 5 else .25
            if item == 8:
                weight *= 5 if dates[day].month in (5, 6, 7, 8) else .25
            if item == 9:
                weight /= (1 + epoch * .30) ** 3
            if item == 11 and days // 2 <= day < days // 2 + 5:
                weight *= 18
            if item == items - 1 and day < days - 30:
                weight = 0
            result.append(weight)
        return list(accumulate(result))

    day_weights = [(1.6 if d.weekday() >= 5 else 1) * (1 + .15 * math.sin(j / 365 * 2 * math.pi)) for j, d in enumerate(dates)]
    day_cumulative = list(accumulate(day_weights))

    def choose_day(low, high):
        before = day_cumulative[low - 1] if low else 0
        return min(high, bisect.bisect_right(day_cumulative, rng.uniform(before, day_cumulative[high])))

    # The rotating 2/3/4 line basket gives exactly three lines per order on average.
    total_lines = 3 * n["orders"]
    rated = set(rng.sample(range(total_lines), n["ratings"]))
    line_id = rating_id = 0
    metrics = {code("M", i): Counter() for i in range(items)}
    period_counts, hour_counts = Counter(), Counter()
    for order_id in range(n["orders"]):
        if order_id < n["customers"]:
            customer = order_id
        elif rng.random() < .65:
            customer = 6 * rng.randrange(n["customers"] // 6) + rng.choice([0, 1, 2])
        else:
            customer = rng.randrange(n["customers"])
        segment = segments[customer]
        day = choose_day(joins[customer], int(days * .65) if segment == 3 else days - 1)
        if segment == 2 and rng.random() < .7:
            candidate = rng.choice(campaigns)
            if candidate[0] >= joins[customer]:
                day = rng.randrange(candidate[0], candidate[1])
        location = customer % locations if rng.random() < .82 else rng.randrange(locations)
        channel = rng.choices(range(4), weights=[4, 2, 2, 3])[0]
        hour = rng.choices([9, 12, 13, 14, 18, 19, 20, 21, 22], weights=[1, 2, 4, 2, 2, 4, 5, 3, 1])[0]
        ordered_at = stamp(day, hour, rng.randrange(60))
        month = ordered_at[:7]
        count = 2 + order_id % 3
        if order_id == n["orders"] - 1:
            count = total_lines - line_id
        # Larger baskets tend to arrive through delivery or loyal customers.
        if count == 4 and rng.random() < .6:
            channel = 3
        campaign = rng.choice(active[day]) if active[day] and rng.random() < (.9 if segment == 2 else .55) else None
        selected = set()
        if rng.random() < .22:
            selected.update([12, 13])
        cumulative = weights(day, location)
        while len(selected) < count:
            item = bisect.bisect_right(cumulative, rng.random() * cumulative[-1])
            # A weak category preference adds variation without making it a label.
            if item % n["categories"] != customer % n["categories"] and rng.random() < .08:
                continue
            selected.add(item)
        cancelled = rng.random() < .035 and not any(i in rated for i in range(line_id, line_id + count))
        out.emit("orders", dict(code=code("O", order_id), restaurant_code=code("R", location), customer_code=code("CU", customer), channel_code=code("CH", channel), promotion_code=code("PR", campaign) if campaign is not None else "", ordered_at=ordered_at, status="cancelled" if cancelled else "completed"))
        period_counts[month] += 1
        hour_counts[str(hour)] += 1
        for line_number, item in enumerate(sorted(selected), 1):
            epoch = 0 if item == items - 1 else bisect.bisect_right(epochs, day) - 1
            price, cost = prices[location, item, epoch], costs[location, item, epoch]
            quantity = 2 if rng.random() < (.32 if segment == 0 else .12) else 1
            attributed = campaign if campaign is not None and item in campaigns[campaign][3] else None
            discount = (price * quantity * campaigns[attributed][2] + 50) // 100 if attributed is not None else 0
            out.emit("order_items", dict(code=code("L", line_id), order_code=code("O", order_id), line_number=line_number, item_code=code("M", item), quantity=quantity, unit_price=money(price), unit_cost=money(cost), discount_amount=money(discount), promotion_code=code("PR", attributed) if attributed is not None else "", unit="portion"), month)
            if not cancelled:
                sales[position(day, location, item)] += quantity
                stat = metrics[code("M", item)]
                stat["quantity"] += quantity
                stat["revenue_cents"] += price * quantity - discount
                stat["contribution_cents"] += (price - cost) * quantity - discount
                stat["promoted_quantity" if attributed is not None else "regular_quantity"] += quantity
                stat["promoted_contribution_cents" if attributed is not None else "regular_contribution_cents"] += (price - cost) * quantity - discount
                stat["weekend_quantity" if dates[day].weekday() >= 5 else "weekday_quantity"] += quantity
                stat[f"location_{location}_quantity"] += quantity
            if line_id in rated:
                mean = 4.7 if item in (1, 3) else 2.1 if item == 4 else 3.9
                score = 5 if item == 10 and days // 2 <= day < days // 2 + 14 else max(1, min(5, round(rng.gauss(mean, .65))))
                rating_time = datetime.fromisoformat(ordered_at) + timedelta(minutes=rng.randint(20, 90))
                out.emit("ratings", dict(code=code("RT", rating_id), order_item_code=code("L", line_id), score=score, rated_at=rating_time.isoformat()))
                metrics[code("M", item)]["rating_sum"] += score
                metrics[code("M", item)]["rating_count"] += 1
                rating_id += 1
            line_id += 1
        if (order_id + 1) % 50000 == 0:
            print(f"Orders generated: {order_id + 1:,}", flush=True)

    # Select distinct daily batches; the newly launched item is excluded from sampling.
    waste_slots = set(rng.sample(range(days * locations * (items - 1)), n["wastage"]))
    closing = [0] * (locations * items)
    waste_id = inventory_id = 0
    for day in range(days):
        for location in range(locations):
            for item in range(items):
                if item == items - 1 and day < days - 30:
                    continue
                sold = sales[position(day, location, item)]
                previous = [sales[position(d, location, item)] for d in range(max(0, day - 7), day)]
                estimate = sum(previous) / max(1, len(previous))
                slot = (day * locations + location) * (items - 1) + item
                wasted = 0
                if item != items - 1 and slot in waste_slots:
                    prepared = max(sold + 1, round(estimate * (2.8 if item == 2 else 1.25) + rng.randint(1, 4)))
                    if item == 1:
                        prepared = sold  # Made to order: low visibility need not imply waste.
                    wasted = prepared - sold
                    epoch = bisect.bisect_right(epochs, day) - 1
                    out.emit("wastage", dict(code=code("W", waste_id), restaurant_code=code("R", location), item_code=code("M", item), recorded_at=stamp(day, 23), prepared_quantity=prepared, wasted_quantity=wasted, unit_cost=money(costs[location, item, epoch]), reason="Overproduction", unit="portion"))
                    metrics[code("M", item)]["wasted_quantity"] += wasted
                    waste_id += 1
                key = location * items + item
                opening = closing[key]
                consumed = sold + wasted
                replenished = max(0, consumed + round(estimate * .3) - opening)
                closing[key] = opening + replenished - consumed
                out.emit("inventory", dict(code=code("I", inventory_id), restaurant_code=code("R", location), item_code=code("M", item), date=dates[day], opening_quantity=opening, replenished_quantity=replenished, consumed_quantity=consumed, unit="portion"))
                inventory_id += 1
        if (day + 1) % 120 == 0:
            print(f"Inventory days generated: {day + 1}/{days}", flush=True)
    assert line_id == total_lines and rating_id == n["ratings"] and waste_id == n["wastage"]
    return {"items": metrics, "monthly_orders": period_counts, "local_hour_orders": hour_counts,
            "order_lines": line_id, "inventory_snapshots": inventory_id}
