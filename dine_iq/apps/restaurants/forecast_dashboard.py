"""Access-scoped forecast comparison with honest backtest boundaries."""

import hashlib
from pathlib import Path

import duckdb
from django.conf import settings

from .dashboard_data import DashboardUnavailable, _read_report


def _verified_file(con, name, path, expected_rows):
    if not path.is_file():
        raise DashboardUnavailable(f"Forecast source is missing: {name}")
    safe = path.as_posix().replace("'", "''")
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{safe}')")
    if con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] != expected_rows:
        raise DashboardUnavailable(f"Forecast source count differs: {name}")


def build_forecast_dashboard(allowed_codes, root=None):
    """Keep future inference separate from evaluated historical predictions."""
    codes = sorted(set(allowed_codes))
    if not codes:
        return {"empty": True}
    root = Path(root or settings.PROJECT_ROOT)
    report_paths = {
        "forecast": root / "processed_data/step20-full/forecast_report.json",
        "time": root / "processed_data/step21-full/time_validation_report.json",
        "accuracy": root / "processed_data/step22-full/forecast_accuracy_report.json",
    }
    forecast = _read_report(report_paths["forecast"], "origin", "2026-07-01")
    time_audit = _read_report(report_paths["time"], "forecast_origin", "2026-07-01")
    accuracy = _read_report(report_paths["accuracy"], "forecast_origin", "2026-07-01")
    historical = _read_report(root / "processed_data/step23-accepted-full/wastage_report.json",
                              "status", "passed")
    digest = hashlib.sha256(report_paths["forecast"].read_bytes()).hexdigest()
    time_digest = hashlib.sha256(report_paths["time"].read_bytes()).hexdigest()
    if (time_audit.get("forecast_report_sha256") != digest or
            accuracy.get("forecast_report_sha256") != digest or
            accuracy.get("time_validation_report_sha256") != time_digest or
            forecast.get("publication_status") != "review_only_not_inventory_or_staffing_approved" or
            accuracy.get("publication_status") != "review_only_not_inventory_or_staffing_approved"):
        raise DashboardUnavailable("Forecast lineage or publication status differs")
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        _verified_file(con, "predictions", root / "parquet_data/step20-full/item_location_forecast.parquet",
                       forecast["forecast_rows"])
        _verified_file(con, "historical", root / "parquet_data/step23-accepted-full/wastage_by_category_location_month.parquet",
                       historical["outputs"]["wastage_by_category_location_month"]["rows"])
        source_codes = {row[0] for row in con.execute("SELECT DISTINCT restaurant_code FROM predictions").fetchall()}
        scoped_codes = sorted(set(codes).intersection(source_codes))
        if not scoped_codes:
            return {"empty": True}
        full_network = set(scoped_codes) == source_codes
        if full_network:
            all_historical = con.execute("SELECT SUM(sold_quantity) FROM historical").fetchone()[0]
            if abs(all_historical - historical["totals"]["sold_quantity"]) > .01:
                raise DashboardUnavailable("Accepted historical demand does not reconcile")
        con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in scoped_codes])
        history_rows = con.execute("""SELECT h.year_month,SUM(h.sold_quantity)
            FROM historical h JOIN allowed_locations a USING (restaurant_code)
            WHERE h.year_month BETWEEN '2026-01' AND '2026-06'
            GROUP BY 1 ORDER BY 1""").fetchall()
        forecast_rows = con.execute("""SELECT p.target_month,SUM(p.forecast_quantity),
            COUNT(*) FROM predictions p JOIN allowed_locations a USING (restaurant_code)
            GROUP BY 1 ORDER BY 1""").fetchall()
        if len(history_rows) != 6 or len(forecast_rows) != 3:
            raise DashboardUnavailable("Forecast and historical periods are incomplete")
        for month, quantity, count in forecast_rows:
            month_key = month.isoformat()
            if month_key not in forecast["forecast_months"] or count != forecast["origin_checks"]["known_pairs"] * len(scoped_codes) // len(source_codes):
                raise DashboardUnavailable("Forecast period or pair coverage differs")
            if full_network and abs(quantity - forecast["rollup_totals"]["item_location_forecast"][month_key]) > .01:
                raise DashboardUnavailable("Network forecast total differs")
        if full_network:
            # Historical totals cover all accepted sales; the backtest scores only eligible pairs.
            monthly_actuals = accuracy["horizons"]["1"]["by_target_month"]
            if any(month not in monthly_actuals for month in accuracy["evaluated_target_months"]):
                raise DashboardUnavailable("Held-out backtest months are incomplete")
        history = [{"month": month, "quantity": quantity} for month, quantity in history_rows]
        future = [{"month": month.strftime("%Y-%m"), "quantity": quantity, "pairs": count}
                  for month, quantity, count in forecast_rows]
        recent_mean = sum(row["quantity"] for row in history[-3:]) / 3
        for row in future:
            row["planning_review"] = (abs(row["quantity"] / recent_mean - 1) > .25
                                      if recent_mean else row["quantity"] > 0)
        backtest = []
        errors = []
        if full_network:
            by_month = accuracy["horizons"]["1"]["by_target_month"]
            backtest = [{"month": month[:7], "actual": values["selected"]["actual_quantity"],
                         "predicted": values["selected"]["predicted_quantity"],
                         "wape": 100 * values["selected"]["wape"],
                         "review": values["selected"]["wape"] > .5}
                        for month, values in sorted(by_month.items())]
            errors = [{"horizon": int(horizon), "mae": values["heldout"]["mae"],
                       "rmse": values["heldout"]["rmse"],
                       "mape": values["heldout"]["mape_percent_nonzero_actual"],
                       "wape": 100 * values["heldout"]["wape"],
                       "r2": values["heldout"]["r2"]}
                      for horizon, values in sorted(accuracy["horizons"].items())]
        return {"empty": False, "location_count": len(scoped_codes),
                "full_network": full_network, "history": history, "future": future,
                "recent_mean": recent_mean, "backtest": backtest, "errors": errors,
                "review_months": [row for row in future if row["planning_review"]]}
    finally:
        con.close()
