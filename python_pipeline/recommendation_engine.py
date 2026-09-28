"""Generate review-only recommendations from verified analytical outputs."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


SOURCES = {
    "location_menu_items": ("step34-full/location_menu_items.parquet", "step34-full/location_menu_performance_report.json", "location_menu_items"),
    "slow_pairs": ("step32-full/slow_moving_pairs.parquet", "step32-full/slow_moving_report.json", "slow_moving_pairs"),
    "price_sensitivity": ("step26-full/pair_sensitivity.parquet", "step26-full/price_sensitivity_report.json", "pair_sensitivity"),
    "bundle_candidates": ("step18-full/recommendation_candidates.parquet", "step18-full/recommendation_report.json", None),
    "churn_risk": ("step36-full/churn_risk.parquet", "step36-full/churn_risk_report.json", None),
    "promotion_traps": ("step28-verified-full/promotion_traps.parquet", "step28-verified-full/promotion_traps_report.json", "promotion_traps"),
    "location_day_anomalies": ("step31-full/location_day_anomalies.parquet", "step31-full/sales_anomalies_report.json", "location_day_anomalies"),
}
TYPES = {"promote_hidden_opportunity", "review_preparation_quantity", "review_price_sensitivity",
         "review_bundle", "review_low_performer", "review_segment_outreach",
         "review_promotion", "investigate_location_anomaly"}


def load_inputs(con, parquet_root, report_root, as_of):
    reports = {}
    paths = {}
    for name, (data_rel, report_rel, output_key) in SOURCES.items():
        data_path, report_path = parquet_root / data_rel, report_root / report_rel
        require(data_path.is_file() and report_path.is_file(), f"Missing verified source: {name}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        require(report.get("status") == "passed", f"Source did not pass: {name}")
        cutoff = report.get("as_of_exclusive", report.get("as_of_exclusive_local_date",
                     report.get("cutoff_exclusive")))
        require(cutoff == as_of.isoformat(), f"Source cutoff differs: {name}")
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{sql_path(data_path)}')")
        actual = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        output_info = report.get("outputs", {}).get(output_key) if output_key else None
        expected = output_info.get("rows") if isinstance(output_info, dict) else None
        if expected is None:
            expected = {
                "price_sensitivity": lambda: report["checks"]["rows"]["pair_sensitivity"],
                "bundle_candidates": lambda: report["candidate_count"],
                "churn_risk": lambda: report["checks"]["customers"],
                "location_day_anomalies": lambda: report["checks"]["location_day_rows"],
            }.get(name, lambda: None)()
        require(expected is not None and actual == expected,
                f"Source row count differs: {name}")
        reports[name] = report
        paths[name] = report_path
    return reports, paths


def validate(con):
    counts = dict(con.execute("SELECT recommendation_type,COUNT(*) FROM recommendation_candidates GROUP BY 1").fetchall())
    require(set(counts).issubset(TYPES), "Unknown recommendation type")
    require(con.execute("""SELECT COUNT(*) FROM recommendation_candidates WHERE
        subject_code IS NULL OR recommended_action IS NULL OR evidence_json IS NULL
        OR source_steps IS NULL OR try_cast(evidence_json AS JSON) IS NULL""").fetchone()[0] == 0,
        "Untraceable recommendation")
    require(con.execute("""SELECT COUNT(*) FROM (
        SELECT recommendation_type,scope,restaurant_code,subject_code,related_code
        FROM recommendation_candidates GROUP BY 1,2,3,4,5 HAVING COUNT(*)>1)""").fetchone()[0] == 0,
        "Duplicate candidate keys")
    require(con.execute("""SELECT COUNT(*) FROM recommendation_candidates
        WHERE recommendation_type='promote_hidden_opportunity'
          AND NOT EXISTS (SELECT 1 FROM location_menu_items m
              WHERE m.restaurant_code=recommendation_candidates.restaurant_code
                AND m.item_code=recommendation_candidates.subject_code
                AND m.location_menu_class='Hidden Opportunity'
                AND NOT m.provisional_evidence)""").fetchone()[0] == 0,
        "Hidden-opportunity policy differs")
    require(con.execute("""SELECT COUNT(*) FROM recommendation_candidates
        WHERE recommendation_type='review_low_performer'
          AND NOT EXISTS (SELECT 1 FROM slow_pairs s
              WHERE s.restaurant_code=recommendation_candidates.restaurant_code
                AND s.item_code=recommendation_candidates.subject_code
                AND s.movement_class='slow_moving')""").fetchone()[0] == 0,
        "Low-performer policy differs")
    return {"candidates": sum(counts.values()), "by_type": counts,
            "abstained_actions": ["increase_stock_before_predicted_hourly_peak",
                                   "automatic_price_change", "automatic_campaign_cancellation",
                                   "automatic_item_removal"]}


def execute(args):
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    for target in (args.output, args.reports):
        for data_rel, report_rel, _ in SOURCES.values():
            require(not target.resolve().is_relative_to((args.parquet_root / data_rel).resolve()) and
                    not target.resolve().is_relative_to((args.report_root / report_rel).resolve()),
                    "Output cannot be inside a source")
    con = duckdb.connect()
    con.execute("SET threads=4")
    reports, paths = load_inputs(con, args.parquet_root, args.report_root, args.as_of)
    con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT ?::DATE AS as_of, ?::DATE AS window_start",
                [args.as_of, date.fromordinal(args.as_of.toordinal() - 90)])
    sql_file = Path(__file__).parent / "sql" / "recommendation_engine.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks = validate(con)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    output = args.output / "recommendation_candidates.parquet"
    con.execute(f"COPY recommendation_candidates TO '{sql_path(output)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(output)]).fetchone()[0] == checks["candidates"],
            "Saved recommendation count differs")
    report = {"status": "passed", "as_of_exclusive": args.as_of.isoformat(),
              "checks": checks, "output": str(output.resolve()),
              "lineage": {name + "_report_sha256": digest(path) for name, path in paths.items()}
              | {"analysis_sql_sha256": digest(sql_file)},
              "limits": "Review candidates only. Rules are transparent analytic screens, not validated causal effects, optimization, inventory instructions or an automatic priority. Detailed evidence presentation and priority are Steps 38-39. Synthetic shifts and accepted-data gaps remain."}
    report_path = args.reports / "recommendation_engine_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path.resolve()), "checks": checks}, indent=2))


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
