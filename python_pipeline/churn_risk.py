"""Flag reduced customer engagement from two comparable 90-day periods."""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


def load_sources(con, args):
    report_paths = {"integration": args.integration_report,
                    "segments": args.segment_report, "rfm": args.rfm_report}
    reports = {}
    for name, path in report_paths.items():
        require(path.is_file(), f"Missing source report: {name}")
        report = json.loads(path.read_text(encoding="utf-8"))
        require(report.get("status") == "passed", f"Source report did not pass: {name}")
        reports[name] = report
    require(reports["segments"]["as_of_exclusive"] ==
            reports["rfm"]["as_of_exclusive"] == args.as_of.isoformat(),
            "Source cutoffs differ")
    sources = {"order_coverage": args.integration / "order_coverage",
               "order_lines": args.integration / "order_lines",
               "customer_segments": args.segments,
               "rfm_scores": args.rfm}
    for name, path in sources.items():
        if path.is_dir():
            require((path / "_SUCCESS").is_file(), f"Missing source marker: {name}")
            pattern = f"{sql_path(path)}/**/*.parquet"
        else:
            require(path.is_file(), f"Missing source snapshot: {name}")
            pattern = sql_path(path)
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern}')")
    require(con.execute("SELECT COUNT(*) FROM order_coverage").fetchone()[0] ==
            reports["integration"]["outputs"]["order_coverage"]["rows"],
            "Coverage count differs")
    require(con.execute("SELECT COUNT(*) FROM order_lines").fetchone()[0] ==
            reports["integration"]["outputs"]["order_lines"]["rows"],
            "Line count differs")
    require(con.execute("SELECT COUNT(*) FROM customer_segments").fetchone()[0] ==
            reports["segments"]["included_customers"], "Segment count differs")
    require(con.execute("SELECT COUNT(*) FROM rfm_scores").fetchone()[0] ==
            reports["rfm"]["population"], "RFM count differs")
    require(args.segments.resolve() == Path(reports["segments"]["output"]).resolve() and
            args.rfm.resolve() == Path(reports["rfm"]["output"]).resolve(),
            "Source reports do not identify these snapshots")
    return reports, report_paths


def validate(con, reports, as_of):
    population = reports["segments"]["included_customers"]
    require(con.execute("SELECT COUNT(*) FROM churn_risk").fetchone()[0] == population,
            "Customer population differs")
    require(con.execute("SELECT COUNT(DISTINCT customer_code) FROM churn_risk").fetchone()[0] == population,
            "Duplicate customer keys")
    require(con.execute("SELECT COUNT(*) FROM churn_risk WHERE as_of_exclusive <> ?", [as_of]).fetchone()[0] == 0,
            "Mixed churn cutoff")
    require(con.execute("""SELECT COUNT(*) FROM churn_risk WHERE
        prior_90_visits + recent_90_visits <> (SELECT visits_180 FROM customer_segments s WHERE s.customer_code=churn_risk.customer_code)
        OR ABS((prior_90_spend+recent_90_spend)::DOUBLE -
            (SELECT monetary_180 FROM customer_segments s WHERE s.customer_code=churn_risk.customer_code)) > 0.01
        OR (lifetime_visits=0 AND churn_review_band <> 'No Purchase History')
        OR (NOT sufficient_history AND lifetime_visits>0 AND churn_review_band <> 'Insufficient History')
        OR (churn_review_band='High Review Priority' AND NOT sufficient_history)
        OR decline_signal_count NOT BETWEEN 0 AND 4""").fetchone()[0] == 0,
        "Window conservation or risk policy differs")
    require(con.execute("""SELECT COUNT(*) FROM eligible_orders e JOIN (
        SELECT order_code, COUNT(*) AS lines, SUM(revenue) AS revenue
        FROM order_lines GROUP BY 1) l USING (order_code)
        WHERE e.accepted_line_count <> l.lines
           OR ABS(e.accepted_basket_revenue::DOUBLE-l.revenue::DOUBLE)>0.01""").fetchone()[0] == 0,
        "Eligible order lines differ from coverage")
    counts = dict(con.execute("SELECT churn_review_band, COUNT(*) FROM churn_risk GROUP BY 1").fetchall())
    require(sum(counts.values()) == population, "Risk bands do not cover all customers")
    return {"customers": population, "window_eligible_visits": con.execute("SELECT COUNT(*) FROM eligible_orders").fetchone()[0],
            "review_band_counts": counts,
            "declining_frequency": con.execute("SELECT COUNT(*) FROM churn_risk WHERE declining_frequency").fetchone()[0],
            "declining_monetary": con.execute("SELECT COUNT(*) FROM churn_risk WHERE declining_monetary").fetchone()[0],
            "declining_category_diversity": con.execute("SELECT COUNT(*) FROM churn_risk WHERE declining_category_diversity").fetchone()[0]}


def execute(args):
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    for target in (args.output, args.reports):
        for source in (args.integration, args.segments, args.rfm,
                       args.integration_report, args.segment_report, args.rfm_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside a source")
    con = duckdb.connect()
    con.execute("SET threads=4")
    reports, report_paths = load_sources(con, args)
    con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT ?::DATE AS as_of, ?::DATE AS recent_start, ?::DATE AS prior_start",
                [args.as_of, args.as_of - timedelta(days=90), args.as_of - timedelta(days=180)])
    sql_file = Path(__file__).parent / "sql" / "churn_risk.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks = validate(con, reports, args.as_of)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    output = args.output / "churn_risk.parquet"
    con.execute(f"COPY churn_risk TO '{sql_path(output)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(output)]).fetchone()[0] == checks["customers"],
            "Saved customer count differs")
    report = {"status": "passed", "as_of_exclusive": args.as_of.isoformat(),
              "prior_window": [(args.as_of-timedelta(days=180)).isoformat(),
                               (args.as_of-timedelta(days=90)).isoformat()],
              "recent_window": [(args.as_of-timedelta(days=90)).isoformat(), args.as_of.isoformat()],
              "checks": checks, "output": str(output.resolve()),
              "lineage": {name + "_report_sha256": digest(path) for name, path in report_paths.items()}
              | {"analysis_sql_sha256": digest(sql_file)},
              "limits": "Heuristic review bands, not observed churn labels or calibrated probabilities. Equal 90-day periods reduce exposure bias but seasonal effects and synthetic-data shifts remain. Only identified, known-complete accepted baskets count. No-purchase and insufficient-history customers abstain; no intervention is automated."}
    report_path = args.reports / "churn_risk_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path.resolve()), "checks": checks}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "integration-report", "segments", "segment-report",
                 "rfm", "rfm-report", "output", "reports"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
