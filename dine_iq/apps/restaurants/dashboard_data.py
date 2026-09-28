"""Verified, access-scoped executive dashboard measures."""

import json
from datetime import date
from pathlib import Path

import duckdb
from django.conf import settings


class DashboardUnavailable(ValueError):
    """A required analytical snapshot is missing or inconsistent."""


def _read_report(path, cutoff_field, cutoff):
    if not path.is_file():
        raise DashboardUnavailable(f"Missing verified report: {path.name}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get(cutoff_field) != cutoff:
        raise DashboardUnavailable(f"Report status or cutoff differs: {path.name}")
    return report


def _paths(root):
    return {
        "locations": root / "parquet_data" / "step33-verified-full" / "location_intelligence.parquet",
        "orders": root / "parquet_data" / "step07-full" / "order_features",
        "forecast": root / "parquet_data" / "step20-full" / "item_location_forecast.parquet",
        "recommendations": root / "parquet_data" / "step39-full" / "prioritized_recommendations.parquet",
        "anomalies": root / "parquet_data" / "step31-full" / "location_day_anomalies.parquet",
        "channels": root / "parquet_data" / "step35-verified-full" / "location_channel_summary.parquet",
    }


def build_executive_dashboard(allowed_codes, global_access=False, root=None):
    """Aggregate only accessible restaurants; never sum location-level unique customers."""
    root = Path(root or settings.PROJECT_ROOT)
    codes = sorted(set(allowed_codes))
    if not codes:
        return {"empty": True, "location_count": 0}
    reports = {
        "locations": _read_report(root / "processed_data" / "step33-verified-full" /
                                  "location_intelligence_report.json", "as_of_exclusive", "2026-07-01"),
        "orders": _read_report(root / "processed_data" / "step07-full" /
                               "feature_report.json", "as_of_exclusive_local_date", "2026-07-01"),
        "forecast": _read_report(root / "processed_data" / "step20-full" /
                                 "forecast_report.json", "origin", "2026-07-01"),
        "recommendations": _read_report(root / "processed_data" / "step39-full" /
                                        "recommendation_priority_report.json", "as_of_exclusive", "2026-07-01"),
        "anomalies": _read_report(root / "processed_data" / "step31-full" /
                                  "sales_anomalies_report.json", "as_of_exclusive", "2026-07-01"),
        "channels": _read_report(root / "processed_data" / "step35-verified-full" /
                                 "ordering_channels_report.json", "as_of_exclusive", "2026-07-01"),
    }
    paths = _paths(root)
    if not (paths["orders"] / "_SUCCESS").is_file():
        raise DashboardUnavailable("Verified order-feature marker is missing")
    for name, path in paths.items():
        if name != "orders" and not path.is_file():
            raise DashboardUnavailable(f"Verified dashboard source is missing: {name}")
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        for name, path in paths.items():
            pattern = str(path.as_posix()) + "/**/*.parquet" if name == "orders" else str(path)
            safe_pattern = pattern.replace("'", "''")
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{safe_pattern}')")
        expected = {
            "locations": reports["locations"]["output"]["rows"],
            "orders": reports["orders"]["outputs"]["order_features"]["rows"],
            "forecast": reports["forecast"]["forecast_rows"],
            "recommendations": reports["recommendations"]["candidates_prioritized"],
            "anomalies": reports["anomalies"]["checks"]["location_day_rows"],
            "channels": reports["channels"]["outputs"]["location_channel_summary"]["rows"],
        }
        for name, count in expected.items():
            if con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] != count:
                raise DashboardUnavailable(f"Verified source row count differs: {name}")
        con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in codes])
        location_rows = con.execute("""SELECT l.restaurant_code,l.restaurant_name,l.city,
            l.completed_orders,l.revenue,l.contribution,l.wasted_quantity,l.waste_cost,
            l.average_rating FROM locations l JOIN allowed_locations a USING (restaurant_code)
            ORDER BY l.revenue DESC,l.restaurant_code""").fetchall()
        if not location_rows:
            return {"empty": True, "location_count": 0}
        revenue = sum((row[4] for row in location_rows), start=0)
        contribution = sum((row[5] for row in location_rows), start=0)
        orders = sum(row[3] for row in location_rows)
        wasted = sum((row[6] for row in location_rows), start=0)
        waste_cost = sum((row[7] for row in location_rows), start=0)
        sold = con.execute("""SELECT SUM(l.quantity_sold) FROM locations l
            JOIN allowed_locations a USING (restaurant_code)""").fetchone()[0]
        order_count = con.execute("""SELECT COUNT(*) FROM orders o
            JOIN allowed_locations a USING (restaurant_code)""").fetchone()[0]
        if order_count != orders:
            raise DashboardUnavailable("Scoped order count differs from location totals")
        active, repeat = con.execute("""WITH customer_visits AS (
            SELECT o.customer_code,COUNT(*) AS visits
            FROM orders o JOIN allowed_locations a USING (restaurant_code)
            WHERE o.customer_metric_eligible AND o.customer_code IS NOT NULL
            GROUP BY 1)
            SELECT COUNT(*),COUNT(*) FILTER (WHERE visits>=2) FROM customer_visits""").fetchone()
        forecast = con.execute("""SELECT SUM(forecast_quantity) FROM forecast f
            JOIN allowed_locations a USING (restaurant_code)
            WHERE target_month=DATE '2026-07-01' AND horizon_months=1""").fetchone()[0]
        if forecast is None:
            raise DashboardUnavailable("No July forecast for accessible locations")
        critical_scoped = con.execute("""SELECT COUNT(*) FROM recommendations r
            JOIN allowed_locations a USING (restaurant_code)
            WHERE priority='Critical'""").fetchone()[0]
        critical_global = (con.execute("""SELECT COUNT(*) FROM recommendations
            WHERE priority='Critical' AND restaurant_code IS NULL""").fetchone()[0]
                           if global_access else 0)
        anomaly_days = con.execute("""SELECT COUNT(*) FROM anomalies x
            JOIN allowed_locations a USING (restaurant_code)
            WHERE local_date>=DATE '2026-04-02' AND local_date<DATE '2026-07-01'
              AND (sudden_sales_spike OR sudden_sales_drop)""").fetchone()[0]
        channel_rows = con.execute("""SELECT c.channel_name,SUM(c.completed_orders) AS orders,
            SUM(c.revenue) AS revenue FROM channels c
            JOIN allowed_locations a USING (restaurant_code)
            GROUP BY 1 ORDER BY orders DESC,c.channel_name""").fetchall()
        weekly_rows = con.execute("""SELECT CAST(FLOOR(date_diff('day', DATE '2026-04-02', o.date) / 7) AS INTEGER) AS week,
            MIN(o.date) AS week_start, COUNT(*) AS orders, SUM(o.accepted_basket_revenue) AS revenue
            FROM orders o JOIN allowed_locations a USING (restaurant_code)
            WHERE o.date >= DATE '2026-04-02' AND o.date < DATE '2026-07-01'
            GROUP BY 1 ORDER BY 1""").fetchall()
        if sum(row[2] for row in weekly_rows) != orders or sum((row[3] for row in weekly_rows), start=0) != revenue:
            raise DashboardUnavailable("Scoped weekly trend differs from dashboard totals")
        if (sum(row[1] for row in channel_rows) != orders or
                abs(float(sum((row[2] for row in channel_rows), start=0) - revenue)) > 0.01):
            raise DashboardUnavailable("Scoped channel and location totals differ")
        if len(location_rows) == expected["locations"]:
            checks = reports["locations"]["checks"]
            if orders != checks["completed_orders"] or abs(float(revenue) - float(checks["revenue"])) > 0.01:
                raise DashboardUnavailable("Full dashboard totals differ from Step 33")
        peak_weekly_revenue = max((row[3] for row in weekly_rows), default=0)
        peak_location_revenue = location_rows[0][4] if location_rows else 0
        return {
            "empty": False, "as_of_exclusive": date(2026, 7, 1),
            "window_start": date(2026, 4, 2), "forecast_month": date(2026, 7, 1),
            "location_count": len(location_rows), "revenue": revenue,
            "direct_contribution": contribution, "completed_orders": orders,
            "average_order_value": revenue / orders if orders else None,
            "active_customers": active, "repeat_customers": repeat,
            "repeat_rate": repeat / active if active else None,
            "wasted_quantity": wasted, "waste_cost": waste_cost,
            "accounted_waste_share": wasted / (sold + wasted) if sold + wasted else None,
            "forecast_demand": forecast, "critical_recommendations": critical_scoped + critical_global,
            "scoped_critical_recommendations": critical_scoped,
            "global_critical_recommendations": critical_global,
            "anomaly_days": anomaly_days,
            "weekly_trend": [{"week_start": row[1], "orders": row[2], "revenue": row[3],
                              "height_percent": round(100 * row[3] / peak_weekly_revenue, 1)
                              if peak_weekly_revenue else 0} for row in weekly_rows],
            "locations": [{"code": row[0], "name": row[1], "city": row[2],
                           "orders": row[3], "revenue": row[4], "direct_contribution": row[5],
                           "wasted_quantity": row[6], "waste_cost": row[7],
                           "average_rating": row[8],
                           "revenue_share_of_top": round(100 * row[4] / peak_location_revenue, 1)
                           if peak_location_revenue else 0} for row in location_rows],
            "channels": [{"name": name, "orders": count, "revenue": amount,
                          "order_share_percent": 100 * count / orders if orders else 0}
                         for name, count, amount in channel_rows],
        }
    finally:
        con.close()
