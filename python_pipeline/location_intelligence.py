"""Build a reconciled 90-day comparison of restaurant locations."""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


SOURCES = {
    "location_features": "step07-full/location_features",
    "order_features": "step07-full/order_features",
    "performance": "step09-full/item_location_performance",
    "slow_pairs": "step32-full/slow_moving_pairs.parquet",
    "wastage_daily": "step23-accepted-full/wastage_daily.parquet",
    "rating_events": "step29-verified-full/rating_events.parquet",
    "campaign_orders": "step27-full/campaign_order_facts.parquet",
}
REPORTS = {
    "features": "step07-full/feature_report.json",
    "performance": "step09-full/profitability_report.json",
    "slow": "step32-full/slow_moving_report.json",
    "waste": "step23-accepted-full/wastage_report.json",
    "ratings": "step29-verified-full/rating_satisfaction_report.json",
    "promotions": "step27-full/promotion_effectiveness_report.json",
}


def load_reports(report_root, as_of):
    reports = {}
    for name, relative in REPORTS.items():
        path = report_root / relative
        require(path.is_file(), f"Missing source report: {path}")
        report = json.loads(path.read_text(encoding="utf-8"))
        require(report.get("status") == "passed", f"Source report did not pass: {name}")
        cutoff = report.get("as_of_exclusive_local_date", report.get("as_of_exclusive"))
        if cutoff is not None:
            require(cutoff == as_of.isoformat(), f"Source cutoff differs: {name}")
        if name in ("features", "performance", "slow"):
            require(report.get("window_days") == 90, f"Source window differs: {name}")
        reports[name] = (report, path)
    return reports


def load_sources(con, parquet_root, reports):
    counts = {}
    for name, relative in SOURCES.items():
        path = parquet_root / relative
        if path.is_dir():
            require((path / "_SUCCESS").is_file(), f"Missing source success marker: {name}")
            pattern = f"{sql_path(path)}/**/*.parquet"
        else:
            require(path.is_file(), f"Missing source Parquet: {name}")
            pattern = sql_path(path)
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern}')")
        counts[name] = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    expected = {
        "location_features": reports["features"][0]["outputs"]["location_features"]["rows"],
        "order_features": reports["features"][0]["outputs"]["order_features"]["rows"],
        "performance": reports["performance"][0]["outputs"]["item_location_performance"]["rows"],
        "slow_pairs": reports["slow"][0]["outputs"]["slow_moving_pairs"]["rows"],
        "wastage_daily": reports["waste"][0]["outputs"]["wastage_daily"]["rows"],
        "rating_events": reports["ratings"][0]["outputs"]["rating_events"]["rows"],
        "campaign_orders": reports["promotions"][0]["outputs"]["campaign_order_facts"]["rows"],
    }
    require(counts == expected, "Source Parquet counts differ from verified reports")
    return counts


def validate(con, reports):
    count = con.execute("SELECT COUNT(*) FROM location_intelligence").fetchone()[0]
    require(count == 24, "Location comparison must contain all 24 restaurants")
    require(con.execute("SELECT COUNT(DISTINCT restaurant_code) FROM location_intelligence").fetchone()[0] == count,
            "Location keys are not unique")
    require(con.execute("SELECT COUNT(*) FROM location_features WHERE feature_as_of <> (SELECT as_of FROM analysis_parameters) OR window_days <> 90").fetchone()[0] == 0,
            "Location feature window differs")
    require(con.execute("SELECT COUNT(*) FROM order_features WHERE feature_as_of <> (SELECT as_of FROM analysis_parameters) OR window_days <> 90").fetchone()[0] == 0,
            "Order feature window differs")
    require(con.execute("SELECT COUNT(*) FROM performance WHERE feature_as_of <> (SELECT as_of FROM analysis_parameters) OR window_days <> 90").fetchone()[0] == 0,
            "Menu performance window differs")
    require(con.execute("SELECT COUNT(*) FROM (SELECT restaurant_code, item_code FROM slow_pairs GROUP BY 1,2 HAVING COUNT(*) > 1)").fetchone()[0] == 0,
            "Slow-moving pair keys are not unique")
    mismatch = con.execute("""SELECT COUNT(*) FROM location_features l
        JOIN order_location o USING (restaurant_code)
        JOIN menu_location m USING (restaurant_code)
        WHERE l.order_frequency <> o.completed_orders
           OR ABS(l.revenue::DOUBLE-o.order_revenue::DOUBLE) > 0.01
           OR ABS(l.revenue::DOUBLE-m.menu_revenue::DOUBLE) > 0.01
           OR ABS(l.cost::DOUBLE-m.menu_cost::DOUBLE) > 0.01
           OR ABS(l.quantity_sold::DOUBLE-m.menu_quantity::DOUBLE) > 0.001
           OR m.menu_pairs <> (SELECT COUNT(*) FROM performance p WHERE p.restaurant_code=l.restaurant_code)""").fetchone()[0]
    require(mismatch == 0, "Order, location and menu totals do not reconcile")
    totals = con.execute("""SELECT SUM(revenue), SUM(cost), SUM(contribution),
        SUM(completed_orders), SUM(eligible_customer_orders), SUM(ratings_submitted),
        SUM(tagged_promo_orders), SUM(slow_moving_items)
        FROM location_intelligence""").fetchone()
    feature_totals = reports["features"][0]["accepted_completed_window_totals"]
    for actual, key in zip(totals[:3], ("revenue", "cost", "contribution")):
        require(abs(float(actual) - float(feature_totals[key])) < 0.01,
                f"Step 7 {key} total differs")
    require(totals[4] == reports["features"][0]["customer_metric_eligible_orders"],
            "Eligible customer visits differ")
    require(totals[7] == reports["slow"][0]["checks"]["pair_classes"]["slow_moving"],
            "Slow-moving count differs")
    require(totals[5] == con.execute("SELECT COUNT(*) FROM rating_events WHERE rating_local_date >= (SELECT window_start FROM analysis_parameters) AND rating_local_date < (SELECT as_of FROM analysis_parameters)").fetchone()[0],
            "Window rating count differs")
    require(totals[6] == con.execute("SELECT COUNT(*) FROM campaign_orders c JOIN order_features o USING (order_code, restaurant_code)").fetchone()[0],
            "Window campaign order count differs")
    require(con.execute("SELECT SUM(wasted_quantity) FROM location_intelligence").fetchone()[0] ==
            con.execute("SELECT SUM(wasted_quantity) FROM wastage_daily WHERE business_date >= (SELECT window_start FROM analysis_parameters) AND business_date < (SELECT as_of FROM analysis_parameters)").fetchone()[0],
            "Window wastage quantity differs")
    require(con.execute("""SELECT COUNT(*) FROM location_intelligence WHERE
        repeat_customer_rate NOT BETWEEN 0 AND 1 OR promo_order_share NOT BETWEEN 0 AND 1
        OR accounted_waste_share NOT BETWEEN 0 AND 1 OR slow_moving_items > menu_pairs
        OR tagged_promo_orders > nonempty_orders""").fetchone()[0] == 0,
            "Invalid comparison ratio or count")
    return {"locations": count, "revenue": str(totals[0]), "cost": str(totals[1]),
            "direct_contribution": str(totals[2]), "completed_orders": int(totals[3]),
            "eligible_customer_orders": int(totals[4]), "ratings_submitted": int(totals[5]),
            "tagged_promo_orders": int(totals[6]), "slow_moving_pairs": int(totals[7])}


def execute(args):
    require(not args.output.exists() and not args.reports.exists(), "Refusing to overwrite existing output")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    for target in (args.output, args.reports):
        for relative in SOURCES.values():
            require(not target.resolve().is_relative_to((args.parquet_root / relative).resolve()),
                    "Output cannot be inside a Parquet source")
        for relative in REPORTS.values():
            require(not target.resolve().is_relative_to((args.report_root / relative).resolve()),
                    "Output cannot be inside a report source")
    reports = load_reports(args.report_root, args.as_of)
    con = duckdb.connect()
    con.execute("SET threads=4")
    source_counts = load_sources(con, args.parquet_root, reports)
    con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT ?::DATE AS as_of, ?::DATE AS window_start",
                [args.as_of, args.as_of - timedelta(days=90)])
    sql_file = Path(__file__).parent / "sql" / "location_intelligence.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks = validate(con, reports)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    output_file = args.output / "location_intelligence.parquet"
    con.execute(f"COPY (SELECT * FROM location_intelligence ORDER BY revenue_rank, restaurant_code) TO '{sql_path(output_file)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(output_file)]).fetchone()[0] == checks["locations"],
            "Saved output count differs")
    result = {"status": "passed", "as_of_exclusive": args.as_of.isoformat(), "window_days": 90,
              "window_start": (args.as_of - timedelta(days=90)).isoformat(),
              "source_counts": source_counts, "checks": checks,
              "output": {"path": str(output_file.resolve()), "rows": checks["locations"]},
              "lineage": {name + "_report_sha256": digest(path) for name, (_, path) in reports.items()}
              | {"analysis_sql_sha256": digest(sql_file)},
              "limits": "Direct contribution excludes overhead. Customer repeat uses only eligible, identified completed baskets within this location and window. Ratings use submission dates, not purchase dates. Promotion tagging is descriptive, not causal. Accounted waste share excludes inventory reconciliation gaps; do not rank locations as a single composite score."}
    report_file = args.reports / "location_intelligence_report.json"
    report_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_file.resolve()), "checks": checks}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet-root", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
