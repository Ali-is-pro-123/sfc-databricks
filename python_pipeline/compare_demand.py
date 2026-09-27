"""Audit independent Spark and Python next-month demand results."""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from python_pipeline.demand import NUMERIC, metrics, require, sql_path


KEY = ("restaurant_code", "item_code", "cutoff")
FLOAT_FEATURES = (*NUMERIC, "baseline")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def match_tolerance(actual):
    return max(2.0, 0.20 * actual)


def classify_difference(actual, spark, python, baseline, history, feature_changed):
    difference = python - spark
    if abs(difference) <= match_tolerance(actual) + 1e-9:
        return "match", "within_tolerance", "Predictions agree within the disclosed quantity tolerance."
    if feature_changed:
        return "mismatch", "feature_divergence", "Historical input features differ between pipelines; inspect the feature audit."
    if actual >= 50:
        return "mismatch", "high_volume_model_sensitivity", "Independent model families diverge on a high-volume record."
    if abs(actual - baseline) > max(5.0, 0.5 * baseline):
        return "mismatch", "demand_shift_model_sensitivity", "Observed monthly sales differ sharply from the recent-demand baseline; model responses diverge."
    if history < 5:
        return "mismatch", "sparse_history_model_sensitivity", "Fewer than five sales days occur in the prior 90 days; independent model responses diverge."
    return "mismatch", "model_sensitivity", "Independent algorithms produce different estimates from comparable historical inputs."


def unique_rows(rows, source):
    seen = set()
    for row in rows:
        key = tuple(row[field] for field in KEY)
        require(all(value is not None and value != "" for value in key),
                f"Null/blank {source} record key")
        require(key not in seen, f"Duplicate {source} record key: {key}")
        seen.add(key)
    return seen


def read_reports(spark_report, python_report):
    require(spark_report.is_file() and python_report.is_file(), "Missing model report")
    spark = json.loads(spark_report.read_text(encoding="utf-8"))
    python = json.loads(python_report.read_text(encoding="utf-8"))
    require(spark.get("status") == python.get("status") == "passed", "Model report did not pass")
    require(spark["split_rows"] == python["checks"]["split_rows"], "Reported split populations differ")
    require(spark["cutoffs"]["start"] == python["cutoffs"][0], "Start cutoffs differ")
    require(spark["cutoffs"]["test_end_exclusive"] == "2026-07-01", "Unexpected Spark horizon")
    require(spark["cutoffs"]["train_end_exclusive"] == python["train_end"], "Train boundaries differ")
    require(spark["cutoffs"]["validation_end_exclusive"] == python["validation_end"],
            "Validation boundaries differ")
    require(spark["target_quantity"] == python["checks"]["target_quantity"],
            "Reported target totals differ")
    return spark, python


def load_views(con, spark_root, python_root, python_csv):
    for name in ("supervised_snapshots", "heldout_predictions"):
        folder = spark_root / name
        require((folder / "_SUCCESS").is_file(), f"Missing Spark success marker: {name}")
        require(any(folder.rglob("*.parquet")), f"Missing Spark Parquet: {name}")
        con.execute(f"CREATE VIEW spark_{name} AS SELECT * FROM read_parquet('{sql_path(folder)}/**/*.parquet')")
    snapshot = python_root / "supervised_snapshots.parquet"
    require(snapshot.is_file() and python_csv.is_file(), "Missing Python output")
    con.execute(f"CREATE VIEW python_supervised_snapshots AS SELECT * FROM read_parquet('{sql_path(snapshot)}')")
    con.execute(f"""CREATE VIEW python_predictions AS
        SELECT restaurant_code, item_code, CAST(cutoff AS DATE) AS cutoff,
               CAST(label AS DOUBLE) AS label, CAST(prediction AS DOUBLE) AS prediction,
               CAST(baseline AS DOUBLE) AS baseline, model
        FROM read_csv_auto('{sql_path(python_csv)}', header=true, all_varchar=true)""")


def assert_unique_table(con, table):
    query = f"""SELECT COUNT(*) FROM (SELECT restaurant_code,item_code,cutoff
        FROM {table} GROUP BY 1,2,3 HAVING COUNT(*)>1)"""
    require(con.execute(query).fetchone()[0] == 0, f"Duplicate keys in {table}")
    require(con.execute(f"SELECT COUNT(*) FROM {table} WHERE restaurant_code IS NULL OR item_code IS NULL OR cutoff IS NULL").fetchone()[0] == 0,
            f"Null keys in {table}")


def audit_snapshots(con, spark_report, python_report):
    for table in ("spark_supervised_snapshots", "python_supervised_snapshots"):
        assert_unique_table(con, table)
    counts = [con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("spark_supervised_snapshots", "python_supervised_snapshots")]
    require(counts[0] == spark_report["outputs"]["supervised_snapshots"]["rows"],
            "Spark snapshot count disagrees with report")
    require(counts[1] == python_report["checks"]["snapshot_rows"],
            "Python snapshot count disagrees with report")
    join = "USING (restaurant_code,item_code,cutoff)"
    con.execute(f"""CREATE TEMP VIEW snapshot_pair AS
        SELECT s.restaurant_code AS spark_restaurant, p.restaurant_code AS python_restaurant,
               COALESCE(s.restaurant_code,p.restaurant_code) AS restaurant_code,
               COALESCE(s.item_code,p.item_code) AS item_code,
               COALESCE(s.cutoff,p.cutoff) AS cutoff,
               s.label AS spark_label, p.label AS python_label,
               s.category_code AS spark_category, p.category_code AS python_category,
               s.split AS spark_split, p.split AS python_split,
               {', '.join(f's.{field} AS spark_{field}, p.{field} AS python_{field}' for field in FLOAT_FEATURES)}
        FROM spark_supervised_snapshots s FULL OUTER JOIN python_supervised_snapshots p {join}""")
    missing = con.execute("""SELECT COUNT(*) FROM snapshot_pair
        WHERE spark_restaurant IS NULL OR python_restaurant IS NULL""").fetchone()[0]
    require(missing == 0, f"Snapshot key population differs: {missing} unmatched")
    actual_mismatch = con.execute("""SELECT COUNT(*) FROM snapshot_pair WHERE
        spark_label IS DISTINCT FROM python_label OR spark_split IS DISTINCT FROM python_split""").fetchone()[0]
    require(actual_mismatch == 0, f"Snapshot labels/splits differ: {actual_mismatch}")
    feature_expr = ["spark_category IS DISTINCT FROM python_category"]
    feature_expr += [f"ABS(spark_{field}-python_{field})>0.000001" for field in FLOAT_FEATURES]
    feature_test = " OR ".join(feature_expr)
    count = con.execute(f"SELECT COUNT(*) FROM snapshot_pair WHERE {feature_test}").fetchone()[0]
    by_field = {field: con.execute(f"SELECT COUNT(*) FROM snapshot_pair WHERE ABS(spark_{field}-python_{field})>0.000001").fetchone()[0]
                for field in FLOAT_FEATURES}
    by_field["category_code"] = con.execute("SELECT COUNT(*) FROM snapshot_pair WHERE spark_category IS DISTINCT FROM python_category").fetchone()[0]
    return {"spark_rows": counts[0], "python_rows": counts[1], "unmatched_keys": missing,
            "actual_or_split_mismatches": actual_mismatch, "rows_with_feature_difference": count,
            "feature_difference_counts": by_field}, feature_test


def audit_predictions(con, spark_report, python_report, feature_test):
    for table in ("spark_heldout_predictions", "python_predictions"):
        assert_unique_table(con, table)
    spark_count = con.execute("SELECT COUNT(*) FROM spark_heldout_predictions").fetchone()[0]
    python_count = con.execute("SELECT COUNT(*) FROM python_predictions").fetchone()[0]
    expected = spark_report["outputs"]["heldout_predictions"]["rows"]
    require(spark_count == python_count == expected == python_report["checks"]["split_rows"]["test"],
            "Held-out row counts differ")
    missing = con.execute("""SELECT COUNT(*) FROM spark_heldout_predictions s
        FULL OUTER JOIN python_predictions p USING (restaurant_code,item_code,cutoff)
        WHERE s.restaurant_code IS NULL OR p.restaurant_code IS NULL""").fetchone()[0]
    require(missing == 0, f"Held-out key populations differ: {missing} unmatched")
    mismatch = con.execute("""SELECT COUNT(*) FROM spark_heldout_predictions s
        JOIN python_predictions p USING (restaurant_code,item_code,cutoff)
        WHERE s.label IS DISTINCT FROM p.label OR ABS(s.baseline-p.baseline)>0.000001""").fetchone()[0]
    require(mismatch == 0, f"Held-out actual/baseline values differ: {mismatch}")
    con.execute(f"""CREATE TEMP VIEW compared AS
        SELECT s.restaurant_code, s.item_code, s.cutoff, s.label AS actual,
               s.prediction_nonnegative AS spark_result, p.prediction AS python_result,
               s.baseline, s.model_name AS spark_model, p.model AS python_model,
               q.spark_sales_days_last_90 AS sales_days_last_90,
               ({feature_test}) AS feature_changed
        FROM spark_heldout_predictions s
        JOIN python_predictions p USING (restaurant_code,item_code,cutoff)
        JOIN snapshot_pair q USING (restaurant_code,item_code,cutoff)""")
    require(con.execute("SELECT COUNT(*) FROM compared").fetchone()[0] == expected,
            "Compared row count changed after snapshot join")
    rows = con.execute("SELECT * FROM compared ORDER BY cutoff,restaurant_code,item_code").fetchall()
    names = [column[0] for column in con.description]
    records = [dict(zip(names, row)) for row in rows]
    for record in records:
        require(record["spark_model"] == spark_report["selected_model"] and
                record["python_model"] == python_report["training"]["selected_model"],
                "Reported selected model name differs from prediction file")
        require(all(math.isfinite(record[field]) and record[field] >= 0
                    for field in ("actual", "spark_result", "python_result", "baseline")),
                "Invalid prediction or actual value")
    return records


def summarize(records, spark_report, python_report):
    output = []
    reasons = Counter()
    months = defaultdict(list)
    for row in records:
        actual, spark, python = row["actual"], row["spark_result"], row["python_result"]
        status, reason, explanation = classify_difference(
            actual, spark, python, row["baseline"], row["sales_days_last_90"],
            row["feature_changed"])
        difference = python - spark
        item = {"record_id": f"{row['restaurant_code']}|{row['item_code']}|{row['cutoff'].isoformat()}",
                "restaurant_code": row["restaurant_code"], "item_code": row["item_code"],
                "cutoff": row["cutoff"].isoformat(), "actual_value": actual,
                "spark_result": spark, "python_result": python, "baseline": row["baseline"],
                "numerical_difference_python_minus_spark": difference,
                "absolute_difference": abs(difference), "agreement_tolerance": match_tolerance(actual),
                "match_or_mismatch": status, "disagreement_code": reason,
                "explanation_of_disagreement": explanation,
                "spark_absolute_error": abs(spark-actual), "python_absolute_error": abs(python-actual),
                "historical_feature_difference": bool(row["feature_changed"])}
        output.append(item)
        reasons[reason] += 1
        months[item["cutoff"][:7]].append(item)
    def score(rows):
        total = len(rows)
        return {"rows": total, "matched": sum(row["match_or_mismatch"] == "match" for row in rows),
                "agreement_percent": 100 * sum(row["match_or_mismatch"] == "match" for row in rows) / total,
                "exact_equal": sum(abs(row["numerical_difference_python_minus_spark"]) <= 1e-9 for row in rows),
                "mean_absolute_prediction_difference": sum(row["absolute_difference"] for row in rows) / total,
                "spark_mae": sum(row["spark_absolute_error"] for row in rows) / total,
                "python_mae": sum(row["python_absolute_error"] for row in rows) / total}
    actual = [row["actual_value"] for row in output]
    spark_values = [row["spark_result"] for row in output]
    python_values = [row["python_result"] for row in output]
    spark_metrics, python_metrics = metrics(actual, spark_values), metrics(actual, python_values)
    for name, computed, reported in (
        ("Spark", spark_metrics, spark_report["selected_test_metrics"]),
        ("Python", python_metrics, python_report["training"]["test_model"]),
    ):
        for field in ("rows", "mae", "rmse", "wape", "actual_quantity"):
            require(abs(computed[field]-reported[field]) < 1e-6,
                    f"Recomputed {name} {field} differs from report")
    summary = {"overall": score(output), "by_month": {month: score(rows) for month, rows in months.items()},
               "reason_counts": dict(reasons), "spark_metrics": spark_metrics,
               "python_metrics": python_metrics,
               "largest_disagreements": sorted(output, key=lambda row: row["absolute_difference"], reverse=True)[:20]}
    return output, summary


def run(args):
    require(not args.output.exists(), f"Refusing to overwrite output: {args.output}")
    for source in (args.spark, args.python, args.spark_report, args.python_report, args.python_csv):
        require(not args.output.resolve().is_relative_to(source.resolve()),
                f"Output cannot be inside an input: {source}")
    spark_report, python_report = read_reports(args.spark_report, args.python_report)
    con = duckdb.connect()
    con.execute("SET threads=4")
    load_views(con, args.spark, args.python, args.python_csv)
    feature_audit, feature_test = audit_snapshots(con, spark_report, python_report)
    records = audit_predictions(con, spark_report, python_report, feature_test)
    rows, result = summarize(records, spark_report, python_report)
    result.update({"status": "passed", "task": "next_calendar_month_accepted_sold_portions",
                   "match_rule": "absolute Python-Spark difference <= max(2 portions, 20% of actual)",
                   "snapshot_audit": feature_audit,
                   "lineage": {"spark_report": str(args.spark_report.resolve()),
                               "spark_report_sha256": digest(args.spark_report),
                               "python_report": str(args.python_report.resolve()),
                               "python_report_sha256": digest(args.python_report),
                               "python_prediction_sha256": digest(args.python_csv),
                               "spark_selected_model": spark_report["selected_model"],
                               "python_selected_model": python_report["training"]["selected_model"]}})
    args.output.mkdir(parents=True)
    csv_file = args.output / "record_comparison.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report_file = args.output / "comparison_report.json"
    report_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_file), "snapshot_audit": feature_audit,
                      "overall": result["overall"], "reason_counts": result["reason_counts"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spark", type=Path, required=True)
    parser.add_argument("--spark-report", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--python-csv", type=Path, required=True)
    parser.add_argument("--python-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
