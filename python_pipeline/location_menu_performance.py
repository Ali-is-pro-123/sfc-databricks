"""Expose verified location-specific menu classes and cross-location differences."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


CLASSES = ("Profit Driver", "Volume Driver", "Hidden Opportunity", "Low Performer")


def load_inputs(con, args):
    class_report_path = args.class_report / "classification_report.json"
    location_report_path = args.location_report / "location_intelligence_report.json"
    require(class_report_path.is_file() and location_report_path.is_file(), "Missing verified source report")
    class_report = json.loads(class_report_path.read_text(encoding="utf-8"))
    location_report = json.loads(location_report_path.read_text(encoding="utf-8"))
    require(class_report.get("status") == location_report.get("status") == "passed",
            "Source report did not pass")
    require(class_report.get("as_of_exclusive_local_date") == args.as_of.isoformat() and
            location_report.get("as_of_exclusive") == args.as_of.isoformat() and
            location_report.get("window_days") == 90,
            "Source windows differ")
    paths = {
        "local_classes": args.classes / "item_location_classification",
        "global_classes": args.classes / "item_classification",
        "location_intelligence": args.locations / "location_intelligence.parquet",
    }
    for name, path in paths.items():
        if path.is_dir():
            require((path / "_SUCCESS").is_file(), f"Missing source success marker: {name}")
            pattern = f"{sql_path(path)}/**/*.parquet"
        else:
            require(path.is_file(), f"Missing source Parquet: {name}")
            pattern = sql_path(path)
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern}')")
    require(con.execute("SELECT COUNT(*) FROM local_classes").fetchone()[0] ==
            class_report["outputs"]["item_location_classification"]["rows"],
            "Local classification count differs")
    require(con.execute("SELECT COUNT(*) FROM global_classes").fetchone()[0] ==
            class_report["outputs"]["item_classification"]["rows"],
            "Item-wide classification count differs")
    require(con.execute("SELECT COUNT(*) FROM location_intelligence").fetchone()[0] ==
            location_report["output"]["rows"], "Location intelligence count differs")
    return {"classification": (class_report, class_report_path),
            "location_intelligence": (location_report, location_report_path)}


def validate(con, reports, as_of):
    require(con.execute("SELECT COUNT(*) FROM location_menu_items").fetchone()[0] == 4320,
            "Item-location coverage differs")
    require(con.execute("SELECT COUNT(*) FROM cross_location_item_variation").fetchone()[0] == 180,
            "Item coverage differs")
    require(con.execute("SELECT COUNT(*) FROM location_menu_summary").fetchone()[0] == 24,
            "Location coverage differs")
    for table, keys in (("local_classes", "restaurant_code,item_code"),
                        ("global_classes", "item_code"),
                        ("location_menu_items", "restaurant_code,item_code")):
        require(con.execute(f"SELECT COUNT(*) FROM (SELECT {keys} FROM {table} GROUP BY {keys} HAVING COUNT(*)>1)").fetchone()[0] == 0,
                f"Duplicate keys in {table}")
    require(con.execute("""SELECT COUNT(*) FROM location_menu_items WHERE
        location_menu_class NOT IN (?, ?, ?, ?) OR item_wide_menu_class NOT IN (?, ?, ?, ?)
        OR as_of_exclusive <> ? OR window_days <> 90
        OR (contribution < 0 AND location_menu_class <> 'Low Performer')""",
        [*CLASSES, *CLASSES, as_of]).fetchone()[0] == 0,
        "Invalid class, cutoff or loss-making classification")
    require(con.execute("""SELECT COUNT(*) FROM local_classes l
        LEFT JOIN location_menu_items m USING (restaurant_code,item_code)
        WHERE m.item_code IS NULL""").fetchone()[0] == 0,
        "A source pair was dropped")
    mismatch = con.execute("""SELECT COUNT(*) FROM location_menu_summary s
        JOIN location_intelligence i USING (restaurant_code)
        WHERE s.menu_items <> i.menu_pairs
           OR ABS(s.revenue::DOUBLE - i.revenue::DOUBLE) > 0.01
           OR ABS(s.cost::DOUBLE - i.cost::DOUBLE) > 0.01
           OR ABS(s.direct_contribution::DOUBLE - i.contribution::DOUBLE) > 0.01
           OR ABS(s.quantity_sold::DOUBLE - i.quantity_sold::DOUBLE) > 0.001
           OR s.profit_drivers+s.volume_drivers+s.hidden_opportunities+s.low_performers <> s.menu_items""").fetchone()[0]
    require(mismatch == 0, "Location class totals do not reconcile")
    totals = con.execute("""SELECT SUM(revenue), SUM(cost), SUM(contribution),
        SUM(quantity_sold), COUNT(*) FILTER (WHERE differs_from_item_wide),
        COUNT(*) FILTER (WHERE varies_across_locations)
        FROM location_menu_items""").fetchone()
    upstream = reports["classification"][0]["conservation"]
    for actual, key in zip(totals[:4], ("revenue", "cost", "contribution", "quantity_sold")):
        require(abs(float(actual) - float(upstream[key])) < 0.01,
                f"Step 10 {key} total differs")
    variable_items = con.execute("SELECT COUNT(*) FROM cross_location_item_variation WHERE distinct_location_classes > 1").fetchone()[0]
    return {"locations": 24, "item_location_pairs": 4320, "items": 180,
            "revenue": str(totals[0]), "cost": str(totals[1]),
            "direct_contribution": str(totals[2]), "quantity_sold": int(totals[3]),
            "pairs_differing_from_item_wide": int(totals[4]),
            "pairs_in_variable_items": int(totals[5]), "items_varying_across_locations": int(variable_items)}


def execute(args):
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    for target in (args.output, args.reports):
        for source in (args.classes, args.class_report, args.locations, args.location_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside a source")
    con = duckdb.connect()
    con.execute("SET threads=4")
    reports = load_inputs(con, args)
    sql_file = Path(__file__).parent / "sql" / "location_menu_performance.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks = validate(con, reports, args.as_of)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs = {}
    for name in ("location_menu_items", "location_menu_summary", "cross_location_item_variation"):
        path = args.output / f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        rows = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
        require(rows == con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"Saved {name} count differs")
        outputs[name] = {"path": str(path.resolve()), "rows": rows}
    report = {"status": "passed", "as_of_exclusive": args.as_of.isoformat(),
              "window_days": 90, "checks": checks, "outputs": outputs,
              "lineage": {name + "_report_sha256": digest(path) for name, (_, path) in reports.items()}
              | {"analysis_sql_sha256": digest(sql_file)},
              "limits": "These are Step 10 peer-relative rule classifications, not causal outcomes. Item-wide and local classes use different peer groups. Provisional evidence, accepted-data gaps and direct-margin exclusions remain. No automatic menu action is prescribed."}
    report_path = args.reports / "location_menu_performance_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path.resolve()), "checks": checks}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("classes", "class-report", "locations", "location-report", "output", "reports"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
