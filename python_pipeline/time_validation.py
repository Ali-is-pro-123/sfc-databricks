"""Audit the chronological provenance of Step 20 demand forecasts."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import FEATURES, TRAIN_END, VALIDATION_END, require
from python_pipeline.forecast import add_months, digest, load_sources, make_origin


AUDIT_CUTOFFS = (date(2025, 12, 1), date(2026, 2, 1), date(2026, 6, 1))


def audit_horizon(con, horizon, origin, reported):
    """Check every supervised join, including its feature and target dates."""
    require(1 <= horizon <= 3, "Unsupported audit horizon")
    rows = con.execute("""SELECT a.cutoff, b.cutoff, a.first_sale_date,
        a.restaurant_code, a.item_code
        FROM historic_snapshots a JOIN historic_snapshots b
          ON a.restaurant_code=b.restaurant_code AND a.item_code=b.item_code
         AND b.cutoff=a.cutoff+(? * INTERVAL 1 MONTH)
        WHERE b.cutoff < ?""", [horizon - 1, origin]).fetchall()
    counts = {"training_rows": 0, "validation_rows": 0, "test_rows": 0}
    keys = set()
    for feature_month, target_month, first_sale, restaurant, item in rows:
        require(first_sale < feature_month <= target_month < origin,
                "Feature or target crosses the forecast origin")
        require(add_months(feature_month, horizon - 1) == target_month,
                "Direct-horizon target is misaligned")
        key = (target_month, restaurant, item)
        require(key not in keys, "Duplicate direct-horizon target key")
        keys.add(key)
        split = ("training_rows" if target_month < TRAIN_END else
                 "validation_rows" if target_month < VALIDATION_END else "test_rows")
        counts[split] += 1
    require(all(counts.values()), "Chronological partition is empty")
    require(all(counts[name] == reported[name] for name in counts),
            "Step 20 chronological row counts differ")
    require(reported["target_month_train_end_exclusive"] == TRAIN_END.isoformat()
            and reported["target_month_validation_end_exclusive"] == VALIDATION_END.isoformat(),
            "Step 20 split boundaries differ")
    return {"horizon_months": horizon, **counts,
            "feature_month_min": min(row[0] for row in rows).isoformat(),
            "feature_month_max": max(row[0] for row in rows).isoformat(),
            "target_month_min": min(row[1] for row in rows).isoformat(),
            "target_month_max": max(row[1] for row in rows).isoformat()}


def audit_as_of(con, cutoff):
    """Rebuild features with later daily observations physically unavailable."""
    con.execute("CREATE OR REPLACE TEMP TABLE cutoffs(cutoff DATE)")
    con.execute("INSERT INTO cutoffs VALUES (?)", [cutoff])
    con.execute("CREATE OR REPLACE TEMP TABLE daily_as_of AS SELECT * FROM daily WHERE local_date < ?", [cutoff])
    con.execute("ALTER TABLE daily RENAME TO daily_full")
    try:
        con.execute("ALTER TABLE daily_as_of RENAME TO daily")
        sql = (Path(__file__).parent / "sql" / "snapshots.sql").read_text(encoding="utf-8")
        con.execute(sql, [TRAIN_END, VALIDATION_END])
        comparisons = ["a.category_code IS DISTINCT FROM h.category_code"]
        comparisons.extend(f"a.{field} IS DISTINCT FROM h.{field}" for field in FEATURES if field not in ("restaurant_code", "category_code"))
        mismatch = " OR ".join(comparisons)
        actual, missing, future_labels = con.execute(f"""SELECT COUNT(*),
            COUNT(*) FILTER (WHERE h.restaurant_code IS NULL OR {mismatch}),
            COUNT(*) FILTER (WHERE a.label != 0)
            FROM supervised_snapshots a LEFT JOIN historic_snapshots h
              ON a.restaurant_code=h.restaurant_code AND a.item_code=h.item_code
             AND a.cutoff=h.cutoff""").fetchone()
        expected = con.execute("SELECT COUNT(*) FROM historic_snapshots WHERE cutoff=?", [cutoff]).fetchone()[0]
        require(actual == expected and missing == 0 and future_labels == 0,
                f"As-of feature parity or future-label check failed: {cutoff}")
        return {"cutoff": cutoff.isoformat(), "compared_rows": actual,
                "future_observations_excluded": con.execute(
                    "SELECT COUNT(*) FROM daily_full WHERE local_date >= ?", [cutoff]).fetchone()[0]}
    finally:
        con.execute("DROP TABLE IF EXISTS supervised_snapshots")
        con.execute("DROP TABLE IF EXISTS daily")
        con.execute("ALTER TABLE daily_full RENAME TO daily")


def execute(args):
    require(not args.output.exists(), "Refusing to overwrite audit output")
    for source in (args.clean, args.quality_report, args.python_report,
                   args.snapshot, args.forecast_report):
        require(not args.output.resolve().is_relative_to(source.resolve()),
                "Audit output cannot be inside an input source")
    report = json.loads(args.forecast_report.read_text(encoding="utf-8"))
    require(report["status"] == "passed", "Step 20 forecast report did not pass")
    require(report["lineage"]["quality_report_sha256"] == digest(args.quality_report)
            and report["lineage"]["python_report_sha256"] == digest(args.python_report)
            and report["lineage"]["python_snapshot_sha256"] == digest(args.snapshot),
            "Step 20 source lineage differs")
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts, _ = load_sources(con, args)
    require(counts == report["source_counts"], "Step 20 source counts differ")
    origin = date.fromisoformat(report["origin"])
    origin_check = make_origin(con, origin)
    require(origin_check == report["origin_checks"], "Step 20 origin checks differ")
    horizons = {str(h): audit_horizon(con, h, origin, detail)
                for h, detail in ((int(k), v) for k, v in report["horizon_models"].items())}
    require(horizons, "No forecast horizons to audit")
    as_of = [audit_as_of(con, cutoff) for cutoff in AUDIT_CUTOFFS if cutoff < origin]
    result = {"status": "passed", "forecast_origin": origin.isoformat(),
              "forecast_report_sha256": digest(args.forecast_report),
              "horizons": horizons, "as_of_checks": as_of,
              "conclusion": "Chronological split and selected cutoff feature parity passed; forecast accuracy and operational approval remain separate."}
    args.output.mkdir(parents=True)
    path = args.output / "time_validation_report.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path.resolve()), "status": result["status"],
                      "horizons": horizons, "as_of_checks": as_of}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--python-report", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--forecast-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
