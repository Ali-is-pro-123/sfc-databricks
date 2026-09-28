"""Verified historical wastage and separately labelled review-only risk scores."""

from pathlib import Path

import duckdb
from django.conf import settings

from .dashboard_data import DashboardUnavailable, _read_report


def _register(con, name, path, expected_rows):
    if not path.is_file():
        raise DashboardUnavailable(f"Wastage source is missing: {name}")
    safe_path = path.as_posix().replace("'", "''")
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{safe_path}')")
    if con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] != expected_rows:
        raise DashboardUnavailable(f"Wastage source count differs: {name}")


def build_wastage_dashboard(allowed_codes, root=None):
    """Aggregate additive item/location facts before ranking within the user's scope."""
    codes = sorted(set(allowed_codes))
    if not codes:
        return {"empty": True}
    root = Path(root or settings.PROJECT_ROOT)
    historical = _read_report(root / "processed_data/step23-accepted-full/wastage_report.json",
                              "status", "passed")
    risk = _read_report(root / "processed_data/step24-verified-full/wastage_risk_report.json",
                        "target_month", "2026-07-01")
    if risk.get("publication_status") != "review_only_not_inventory_or_preparation_approved":
        raise DashboardUnavailable("Wastage risk publication status differs")
    folder = root / "parquet_data/step23-accepted-full"
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        for name, file in (("pairs", "wastage_by_item_location"),
                           ("months", "wastage_by_category_location_month"),
                           ("locations", "wastage_by_location")):
            _register(con, name, folder / f"{file}.parquet", historical["outputs"][file]["rows"])
        _register(con, "risk", root / "parquet_data/step24-verified-full/next_month_wastage_risk.parquet",
                  risk["future_rows"])
        con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in codes])
        scoped_locations = [row[0] for row in con.execute(
            "SELECT l.restaurant_code FROM locations l JOIN allowed_locations a USING (restaurant_code)").fetchall()]
        if not scoped_locations:
            return {"empty": True}
        totals = con.execute("""SELECT SUM(p.wasted_quantity),SUM(p.waste_cost),SUM(p.sold_quantity),
            SUM(p.consumed_quantity) FROM pairs p JOIN allowed_locations a USING (restaurant_code)""").fetchone()
        if set(scoped_locations) == {row[0] for row in con.execute("SELECT restaurant_code FROM locations").fetchall()}:
            checks = historical["totals"]
            if (abs(totals[0] - checks["wasted_quantity"]) > .001 or
                    abs(totals[1] - checks["waste_cost"]) > .02 or
                    abs(totals[2] - checks["sold_quantity"]) > .001):
                raise DashboardUnavailable("Full-network wastage totals do not reconcile")
        item_rows = con.execute("""SELECT p.item_code,SUM(p.wasted_quantity) AS quantity,
            SUM(p.waste_cost) AS cost FROM pairs p JOIN allowed_locations a USING (restaurant_code)
            GROUP BY p.item_code HAVING SUM(p.wasted_quantity)>0
            ORDER BY cost DESC,p.item_code LIMIT 10""").fetchall()
        location_rows = con.execute("""SELECT l.restaurant_code,l.wasted_quantity,l.waste_cost,
            l.sold_quantity FROM locations l JOIN allowed_locations a USING (restaurant_code)
            ORDER BY l.waste_cost DESC,l.restaurant_code LIMIT 10""").fetchall()
        trend_rows = con.execute("""SELECT m.year_month,SUM(m.wasted_quantity),SUM(m.waste_cost),
            SUM(m.sold_quantity) FROM months m JOIN allowed_locations a USING (restaurant_code)
            WHERE m.year_month BETWEEN '2026-01' AND '2026-06'
            GROUP BY m.year_month ORDER BY m.year_month""").fetchall()
        scored_count = con.execute("SELECT COUNT(*) FROM risk r JOIN allowed_locations a USING (restaurant_code)").fetchone()[0]
        pair_count = con.execute("SELECT COUNT(*) FROM pairs p JOIN allowed_locations a USING (restaurant_code)").fetchone()[0]
        risk_rows = con.execute("""SELECT r.restaurant_code,r.item_code,r.risk_probability
            FROM risk r JOIN allowed_locations a USING (restaurant_code)
            WHERE r.month_start=DATE '2026-07-01'
            ORDER BY r.risk_probability DESC,r.restaurant_code,r.item_code LIMIT 10""").fetchall()
        if scored_count > pair_count or (len(scoped_locations) == historical["source_counts"]["restaurants"]
                                         and pair_count - scored_count != risk["unscored_insufficient_history_pairs"]):
            raise DashboardUnavailable("Risk coverage does not reconcile")
        return {
            "empty": False, "location_count": len(scoped_locations),
            "wasted_quantity": totals[0], "waste_cost": totals[1], "sold_quantity": totals[2],
            "waste_share": 100 * totals[0] / (totals[0] + totals[2]) if totals[0] + totals[2] else None,
            "items": [{"code": code, "quantity": quantity, "cost": cost} for code, quantity, cost in item_rows],
            "locations": [{"code": code, "quantity": quantity, "cost": cost, "sold": sold}
                          for code, quantity, cost, sold in location_rows],
            "trends": [{"month": month, "quantity": quantity, "cost": cost, "sold": sold}
                       for month, quantity, cost, sold in trend_rows],
            "risk_pairs": [{"restaurant_code": code, "item_code": item, "probability": score}
                           for code, item, score in risk_rows],
            "scored_pairs": scored_count,
            "unscored_pairs": pair_count - scored_count,
            "heldout_auc": risk["heldout"]["selected"]["roc_auc"],
            "heldout_average_precision": risk["heldout"]["selected"]["average_precision"],
        }
    finally:
        con.close()
