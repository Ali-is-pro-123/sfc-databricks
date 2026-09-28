"""Build verified item/location menu intelligence within a user's location scope."""

from collections import Counter
from decimal import Decimal
from pathlib import Path

import duckdb
from django.conf import settings

from .dashboard_data import DashboardUnavailable, _read_report


MENU_CLASSES = ("Profit Driver", "Volume Driver", "Hidden Opportunity", "Low Performer")
MOVEMENT_CLASSES = ("slow_moving", "watchlist", "not_slow_moving", "insufficient_evidence")
SORTS = ("revenue", "quantity", "direct_margin", "rating", "wastage", "name")


def build_menu_dashboard(allowed_codes, filters=None, root=None):
    """Keep summary denominators stable while filters narrow only the item table."""
    codes = sorted(set(allowed_codes))
    if not codes:
        return {"empty": True, "pair_count": 0}
    root = Path(root or settings.PROJECT_ROOT)
    filters = filters or {}
    menu_report = _read_report(root / "processed_data" / "step34-full" /
                               "location_menu_performance_report.json", "as_of_exclusive", "2026-07-01")
    slow_report = _read_report(root / "processed_data" / "step32-full" /
                               "slow_moving_report.json", "as_of_exclusive", "2026-07-01")
    if menu_report.get("window_days") != 90 or slow_report.get("window_days") != 90:
        raise DashboardUnavailable("Menu source windows differ")
    menu_path = root / "parquet_data" / "step34-full" / "location_menu_items.parquet"
    slow_path = root / "parquet_data" / "step32-full" / "slow_moving_pairs.parquet"
    if not menu_path.is_file() or not slow_path.is_file():
        raise DashboardUnavailable("Verified menu source is missing")
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        for name, path in (("menu", menu_path), ("movement", slow_path)):
            safe_path = str(path).replace("'", "''")
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{safe_path}')")
        expected = menu_report["outputs"]["location_menu_items"]["rows"]
        if (con.execute("SELECT COUNT(*) FROM menu").fetchone()[0] != expected or
                con.execute("SELECT COUNT(*) FROM movement").fetchone()[0] !=
                slow_report["outputs"]["slow_moving_pairs"]["rows"]):
            raise DashboardUnavailable("Menu source counts differ")
        joined = con.execute("""SELECT COUNT(*) FROM menu m JOIN movement s
            USING (restaurant_code,item_code)""").fetchone()[0]
        if joined != expected:
            raise DashboardUnavailable("Menu and movement pairs do not reconcile")
        con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in codes])
        cursor = con.execute("""SELECT m.restaurant_code,m.restaurant_name,m.category_code,
            m.category_name,m.item_code,m.item_name,m.location_menu_class,
            m.item_wide_menu_class,m.provisional_evidence,m.quantity_sold,
            m.order_frequency,m.revenue,m.contribution,m.direct_margin_percentage,
            m.rating_count,m.average_rating,m.wasted_quantity,
            m.accounted_wastage_percentage,s.movement_class,
            m.varies_across_locations
            FROM menu m JOIN movement s USING (restaurant_code,item_code)
            JOIN allowed_locations a USING (restaurant_code)""")
        names = [column[0] for column in cursor.description]
        rows = [dict(zip(names, values)) for values in cursor.fetchall()]
    finally:
        con.close()
    if not rows:
        return {"empty": True, "pair_count": 0}
    keys = {(row["restaurant_code"], row["item_code"]) for row in rows}
    if len(keys) != len(rows):
        raise DashboardUnavailable("Duplicate scoped item/location pairs")
    class_counts = Counter(row["location_menu_class"] for row in rows)
    if set(class_counts) - set(MENU_CLASSES):
        raise DashboardUnavailable("Unexpected menu classification")
    movement_counts = Counter(row["movement_class"] for row in rows)
    if set(movement_counts) - set(MOVEMENT_CLASSES):
        raise DashboardUnavailable("Unexpected movement classification")
    revenue = sum((row["revenue"] for row in rows), Decimal(0))
    contribution = sum((row["contribution"] for row in rows), Decimal(0))
    sold = sum((Decimal(str(row["quantity_sold"])) for row in rows), Decimal(0))
    wasted = sum((Decimal(str(row["wasted_quantity"])) for row in rows), Decimal(0))
    rating_count = sum(row["rating_count"] for row in rows)
    rating_sum = sum((Decimal(str(row["average_rating"])) * row["rating_count"]
                      for row in rows if row["rating_count"] and row["average_rating"] is not None),
                     Decimal(0))
    if len(rows) == expected:
        checks = menu_report["checks"]
        if (abs(revenue - Decimal(checks["revenue"])) > Decimal("0.01") or
                abs(contribution - Decimal(checks["direct_contribution"])) > Decimal("0.01") or
                int(sold) != checks["quantity_sold"] or
                movement_counts["slow_moving"] != slow_report["checks"]["pair_classes"]["slow_moving"]):
            raise DashboardUnavailable("Full menu financial or movement totals differ")
    location_options = sorted({(row["restaurant_code"], row["restaurant_name"]) for row in rows})
    category_options = sorted({(row["category_code"], row["category_name"]) for row in rows})
    selected_location = filters.get("location", "")
    selected_class = filters.get("class", "")
    selected_category = filters.get("category", "")
    selected_movement = filters.get("movement", "")
    query = str(filters.get("q", ""))[:80].strip()
    sort = filters.get("sort", "revenue")
    if selected_location not in {code for code, _ in location_options}:
        selected_location = ""
    if selected_class not in MENU_CLASSES:
        selected_class = ""
    if selected_category not in {code for code, _ in category_options}:
        selected_category = ""
    if selected_movement not in MOVEMENT_CLASSES:
        selected_movement = ""
    if sort not in SORTS:
        sort = "revenue"
    filtered = [row for row in rows
                if (not selected_location or row["restaurant_code"] == selected_location)
                and (not selected_class or row["location_menu_class"] == selected_class)
                and (not selected_category or row["category_code"] == selected_category)
                and (not selected_movement or row["movement_class"] == selected_movement)
                and (not query or query.casefold() in row["item_name"].casefold()
                     or query.casefold() in row["item_code"].casefold())]
    if sort == "name":
        filtered.sort(key=lambda row: (row["item_name"], row["restaurant_code"], row["item_code"]))
    else:
        field = {"revenue": "revenue", "quantity": "quantity_sold",
                 "direct_margin": "direct_margin_percentage", "rating": "average_rating",
                 "wastage": "accounted_wastage_percentage"}[sort]
        filtered.sort(key=lambda row: (row[field] is not None,
                                       float(row[field] or 0), row["item_code"]), reverse=True)
    return {
        "empty": False, "as_of_exclusive": "2026-07-01", "window_start": "2026-04-02",
        "pair_count": len(rows), "item_count": len({row["item_code"] for row in rows}),
        "location_count": len(location_options), "class_counts": class_counts,
        "class_cards": [{"label": label,
                         "plural": {"Profit Driver": "Profit Drivers",
                                    "Volume Driver": "Volume Drivers",
                                    "Hidden Opportunity": "Hidden Opportunities",
                                    "Low Performer": "Low Performers"}[label],
                         "count": class_counts[label],
                         "percentage": 100 * class_counts[label] / len(rows)}
                        for label in MENU_CLASSES],
        "movement_counts": movement_counts, "slow_moving_count": movement_counts["slow_moving"],
        "provisional_count": sum(bool(row["provisional_evidence"]) for row in rows),
        "revenue": revenue, "direct_contribution": contribution,
        "direct_margin_percentage": 100 * contribution / revenue if revenue else None,
        "sold_quantity": sold, "wasted_quantity": wasted,
        "accounted_waste_percentage": 100 * wasted / (sold + wasted) if sold + wasted else None,
        "rating_count": rating_count,
        "average_rating": rating_sum / rating_count if rating_count else None,
        "location_options": location_options, "category_options": category_options,
        "menu_classes": MENU_CLASSES, "movement_classes": MOVEMENT_CLASSES,
        "selected_location": selected_location, "selected_class": selected_class,
        "selected_category": selected_category, "selected_movement": selected_movement,
        "query": query, "sort": sort, "filtered_count": len(filtered), "items": filtered,
    }
