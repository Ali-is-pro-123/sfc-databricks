"""Compare completed-order behavior across verified ordering channels."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


EXPECTED_CHANNELS = {"Dine-in", "Takeaway", "Website/App", "Third-party Delivery"}


def load_inputs(con, args):
    quality = json.loads(args.quality_report.read_text(encoding="utf-8"))
    features = json.loads(args.feature_report.read_text(encoding="utf-8"))
    locations = json.loads(args.location_report.read_text(encoding="utf-8"))
    promotions = json.loads(args.promotion_report.read_text(encoding="utf-8"))
    require(all(r.get("status") == "passed" for r in (quality, features, locations, promotions)),
            "An upstream report did not pass")
    require(features.get("as_of_exclusive_local_date") == locations.get("as_of_exclusive") ==
            promotions.get("as_of_exclusive") == args.as_of.isoformat(),
            "Upstream cutoff differs")
    require(features.get("window_days") == locations.get("window_days") == 90,
            "Upstream window differs")
    sources = {
        "order_features": args.features / "order_features",
        "clean_order_items": args.clean / "order_items",
        "clean_ordering_channels": args.clean / "ordering_channels",
        "clean_menu_items": args.clean / "menu_items",
        "campaign_orders": args.promotions / "campaign_order_facts.parquet",
    }
    for name, path in sources.items():
        if path.is_dir():
            require((path / "_SUCCESS").is_file(), f"Missing source success marker: {name}")
            pattern = f"{sql_path(path)}/**/*.parquet"
        else:
            require(path.is_file(), f"Missing source Parquet: {name}")
            pattern = sql_path(path)
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern}')")
    for table, key in (("order_items", "clean_order_items"),
                       ("ordering_channels", "clean_ordering_channels"),
                       ("menu_items", "clean_menu_items")):
        require(con.execute(f"SELECT COUNT(*) FROM {key}").fetchone()[0] ==
                quality["tables"][table]["accepted_rows"],
                f"Accepted source count differs: {table}")
    require(con.execute("SELECT COUNT(*) FROM order_features").fetchone()[0] ==
            features["outputs"]["order_features"]["rows"],
            "Order feature count differs")
    require(con.execute("SELECT COUNT(*) FROM campaign_orders").fetchone()[0] ==
            promotions["outputs"]["campaign_order_facts"]["rows"],
            "Campaign source count differs")
    return {"features": features, "locations": locations}


def validate(con, reports, as_of):
    require(con.execute("SELECT COUNT(*) FROM channel_orders").fetchone()[0] ==
            reports["features"]["outputs"]["order_features"]["rows"],
            "Channel orders dropped completed headers")
    channel_names = {r[0] for r in con.execute("SELECT channel_name FROM channel_summary").fetchall()}
    require(EXPECTED_CHANNELS.issubset(channel_names), "Missing an SRS core channel")
    require(con.execute("""SELECT COUNT(*) FROM channel_orders o JOIN basket_lines b USING (order_code)
        WHERE o.accepted_line_count <> b.line_count
           OR o.accepted_quantity <> b.quantity
           OR ABS(o.accepted_basket_revenue::DOUBLE - b.revenue::DOUBLE) > 0.01""").fetchone()[0] == 0,
            "Step 7 baskets differ from accepted lines")
    require(con.execute("""SELECT COUNT(*) FROM order_features WHERE
        feature_as_of <> ? OR window_days <> 90""", [as_of]).fetchone()[0] == 0,
            "Mixed feature windows")
    require(con.execute("SELECT COUNT(*) FROM (SELECT order_code FROM campaign_orders GROUP BY 1 HAVING COUNT(*)>1)").fetchone()[0] == 0,
            "Duplicate campaign order keys")
    totals = con.execute("""SELECT SUM(completed_orders), SUM(revenue), SUM(direct_cost),
        SUM(direct_contribution), SUM(campaign_tagged_orders), SUM(sold_quantity)
        FROM channel_summary""").fetchone()
    step7 = reports["features"]["accepted_completed_window_totals"]
    for actual, key in zip(totals[1:4], ("revenue", "cost", "contribution")):
        require(abs(float(actual) - float(step7[key])) < 0.01, f"Step 7 {key} differs")
    require(totals[0] == reports["locations"]["checks"]["completed_orders"],
            "Step 33 order total differs")
    require(totals[4] == reports["locations"]["checks"]["tagged_promo_orders"],
            "Step 33 campaign total differs")
    require(con.execute("""SELECT COUNT(*) FROM (
        SELECT restaurant_code, SUM(revenue) AS revenue FROM location_channel_summary GROUP BY 1
        ) x JOIN read_parquet(?) l USING (restaurant_code)
        WHERE ABS(x.revenue::DOUBLE-l.revenue::DOUBLE)>0.01""",
        [reports["locations"]["output"]["path"]]).fetchone()[0] == 0,
        "Location revenue differs from Step 33")
    require(con.execute("""SELECT COUNT(*) FROM channel_summary WHERE
        campaign_share_of_nonempty_orders NOT BETWEEN 0 AND 1
        OR completed_orders < nonempty_orders OR discount < 0""").fetchone()[0] == 0,
        "Invalid channel ratios or counts")
    return {"channels": len(channel_names), "completed_orders": int(totals[0]),
            "revenue": str(totals[1]), "direct_cost": str(totals[2]),
            "direct_contribution": str(totals[3]),
            "campaign_tagged_orders": int(totals[4]), "sold_quantity": int(totals[5]),
            "location_channel_rows": con.execute("SELECT COUNT(*) FROM location_channel_summary").fetchone()[0],
            "channel_item_rows": con.execute("SELECT COUNT(*) FROM channel_menu_preferences").fetchone()[0]}


def execute(args):
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    for target in (args.output, args.reports):
        for source in (args.clean, args.features, args.promotions, args.quality_report,
                       args.feature_report, args.location_report, args.promotion_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside a source")
    con = duckdb.connect()
    con.execute("SET threads=4")
    reports = load_inputs(con, args)
    sql_file = Path(__file__).parent / "sql" / "ordering_channels.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks = validate(con, reports, args.as_of)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs = {}
    for name in ("channel_summary", "location_channel_summary", "channel_menu_preferences", "channel_peak_hours"):
        path = args.output / f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        rows = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
        require(rows == con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"Saved {name} count differs")
        outputs[name] = {"path": str(path.resolve()), "rows": rows}
    report = {"status": "passed", "as_of_exclusive": args.as_of.isoformat(),
              "window_days": 90, "checks": checks, "outputs": outputs,
              "lineage": {name + "_report_sha256": digest(path) for name, path in (
                  ("quality", args.quality_report), ("features", args.feature_report),
                  ("locations", args.location_report), ("promotions", args.promotion_report))}
                  | {"analysis_sql_sha256": digest(sql_file)},
              "limits": "Completed accepted baskets may be partial or empty. Average order value and basket sizes include empty completed headers. Campaign tags are active-campaign orders, not causal promotion lift; discounts include all accepted line discounts. Direct contribution excludes overhead and delivery-platform fees. Peaks are local-hour observed counts, not exposure-adjusted rates."}
    path = args.reports / "ordering_channels_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path.resolve()), "checks": checks}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("clean", "quality-report", "features", "feature-report", "promotions",
                 "promotion-report", "location-report", "output", "reports"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
