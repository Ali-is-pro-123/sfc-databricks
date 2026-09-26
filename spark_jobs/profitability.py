"""Build a cutoff-aware, multi-dimensional menu profitability snapshot."""

import argparse
import hashlib
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession, functions as F
from spark_jobs.integrate import persist_output, require, save_report, totals


def source_report(path, label):
    raw = Path(path).read_bytes()
    report = json.loads(raw)
    require(report.get("status") == "passed", f"{label} report must be passed")
    return report, hashlib.sha256(raw).hexdigest()


def period_totals(lines, as_of):
    cutoff = date.fromisoformat(as_of)
    prior_start = cutoff - timedelta(days=60)
    recent_start = cutoff - timedelta(days=30)
    filtered = lines.filter(
        (F.col("status") == "completed") &
        (F.col("date") >= F.lit(prior_start)) &
        (F.col("date") < F.lit(cutoff)))
    period = F.when(F.col("date") >= F.lit(recent_start), F.lit("recent")).otherwise("prior")
    grouped = (filtered.withColumn("period", period)
        .groupBy("restaurant_code", "item_code", "period")
        .agg(F.sum("quantity").alias("quantity"), F.sum("revenue").alias("revenue")))
    return (grouped.groupBy("restaurant_code", "item_code").agg(
        F.coalesce(F.sum(F.when(F.col("period") == "prior", F.col("quantity"))), F.lit(0)).alias("prior_30d_quantity"),
        F.coalesce(F.sum(F.when(F.col("period") == "recent", F.col("quantity"))), F.lit(0)).alias("recent_30d_quantity"),
        F.coalesce(F.sum(F.when(F.col("period") == "prior", F.col("revenue"))), F.lit(0)).alias("prior_30d_revenue"),
        F.coalesce(F.sum(F.when(F.col("period") == "recent", F.col("revenue"))), F.lit(0)).alias("recent_30d_revenue")))


def performance_frame(features, periods, as_of):
    cutoff = date.fromisoformat(as_of)
    prior_start = cutoff - timedelta(days=60)
    recent_start = cutoff - timedelta(days=30)
    joined = features.join(periods, ["restaurant_code", "item_code"], "left")
    for field in ["prior_30d_quantity", "recent_30d_quantity",
                  "prior_30d_revenue", "recent_30d_revenue"]:
        joined = joined.withColumn(field, F.coalesce(F.col(field), F.lit(0)))
    prior_days = F.greatest(F.lit(0), F.datediff(F.lit(recent_start),
                    F.greatest(F.col("introduced_on"), F.lit(prior_start))))
    recent_days = F.greatest(F.lit(0), F.datediff(F.lit(cutoff),
                     F.greatest(F.col("introduced_on"), F.lit(recent_start))))
    return (joined
        .withColumn("prior_30d_exposure_days", prior_days)
        .withColumn("recent_30d_exposure_days", recent_days)
        .withColumn("quantity_trend_percentage", F.when(
            (F.col("prior_30d_exposure_days") == 30) & (F.col("prior_30d_quantity") > 0),
            100.0 * (F.col("recent_30d_quantity") - F.col("prior_30d_quantity")) /
            F.col("prior_30d_quantity")))
        .withColumn("revenue_trend_percentage", F.when(
            (F.col("prior_30d_exposure_days") == 30) & (F.col("prior_30d_revenue") > 0),
            100.0 * (F.col("recent_30d_revenue") - F.col("prior_30d_revenue")) /
            F.col("prior_30d_revenue")))
        .withColumn("negative_contribution", F.col("contribution") < 0)
        .withColumn("rating_unobserved", F.col("rating_count") == 0)
        .withColumn("repeat_rate_unobserved", F.col("repeat_purchase_rate").isNull())
        .withColumn("trend_unobserved", F.col("quantity_trend_percentage").isNull())
        .withColumn("profitability_as_of", F.lit(cutoff).cast("date"))
        .drop("_month")
        .withColumn("_month", F.lit(as_of[:7])))


def build_profitability(spark, integration_path, integration_report, feature_path,
                        feature_report, output, report_dir):
    integration_path, feature_path, output, report_dir = (
        Path(p).resolve() for p in (integration_path, feature_path, output, report_dir))
    require(not output.exists() and not report_dir.exists(), "Choose unused output/report directories")
    for target in (output, report_dir):
        require(not target.is_relative_to(integration_path) and
                not target.is_relative_to(feature_path), "Outputs must be outside input directories")
    require(not output.is_relative_to(report_dir) and not report_dir.is_relative_to(output),
            "Keep output and report directories separate")
    integration, integration_hash = source_report(integration_report, "Integration")
    features, feature_hash = source_report(feature_report, "Feature")
    require(Path(features["source"]).resolve() == integration_path, "Feature integration path differs")
    require(features["integration_sha256"] == integration_hash, "Feature integration report changed")
    require(Path(features["integration_report"]).resolve() == Path(integration_report).resolve(),
            "Feature integration report path differs")
    require(features["window_days"] == 90, "Profitability needs the 90-day feature snapshot")
    as_of = features["as_of_exclusive_local_date"]
    require(date.fromisoformat(as_of).isoformat() == as_of, "Invalid feature cutoff")
    require(Path(integration["source"]).resolve() != output, "Invalid output path")
    require((integration_path / "order_lines" / "_SUCCESS").is_file(), "Missing integrated lines")
    require((feature_path / "item_location_features" / "_SUCCESS").is_file(), "Missing features")
    started = time.perf_counter()
    report_dir.mkdir(parents=True)
    report_path = report_dir / "profitability_report.json"
    report = {"status": "running", "as_of_exclusive_local_date": as_of, "window_days": 90,
              "integration_report_sha256": integration_hash, "feature_report_sha256": feature_hash,
              "job_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "application_id": spark.sparkContext.applicationId, "spark_version": spark.version,
              "outputs": {}}
    save_report(report_path, report)
    try:
        lines = spark.read.parquet(str(integration_path / "order_lines"))
        feature_items = spark.read.parquet(str(feature_path / "item_location_features"))
        require(lines.count() == integration["outputs"]["order_lines"]["rows"], "Integrated line count changed")
        require(feature_items.count() == features["outputs"]["item_location_features"]["rows"],
                "Feature item count changed")
        require(feature_items.filter((F.col("feature_as_of") != F.lit(as_of)) |
                                     (F.col("window_days") != 90)).count() == 0,
                "Mixed feature snapshots")
        periods = period_totals(lines, as_of)
        frame = performance_frame(feature_items, periods, as_of)
        result, meta = persist_output(spark, frame, output, "item_location_performance",
                                      ["restaurant_code", "item_code"])
        report["outputs"]["item_location_performance"] = meta
        require(meta["rows"] == features["outputs"]["item_location_features"]["rows"],
                "Item/location keys changed")
        metrics = ["quantity_sold", "revenue", "cost", "contribution"]
        require(totals(result, metrics) == totals(feature_items, metrics), "Feature totals changed")
        cutoff = date.fromisoformat(as_of)
        source_period = lines.filter((F.col("status") == "completed") &
            (F.col("date") >= F.lit(cutoff - timedelta(days=60))) &
            (F.col("date") < F.lit(cutoff)))
        require(totals(result, ["prior_30d_quantity", "recent_30d_quantity"])["prior_30d_quantity"] +
                totals(result, ["prior_30d_quantity", "recent_30d_quantity"])["recent_30d_quantity"] ==
                totals(source_period, ["quantity"])["quantity"], "Period quantity changed")
        period_revenue = totals(result, ["prior_30d_revenue", "recent_30d_revenue"])
        require(period_revenue["prior_30d_revenue"] + period_revenue["recent_30d_revenue"] ==
                totals(source_period, ["revenue"])["revenue"], "Period revenue changed")
        require(result.filter((F.col("prior_30d_exposure_days") < 30) &
                              F.col("quantity_trend_percentage").isNotNull()).count() == 0,
                "New-item trend is not suppressed")
        report["conservation"] = {"window_totals": totals(result, metrics),
                                   "period_totals": totals(source_period, ["quantity", "revenue"]),
                                   "negative_contribution_rows": result.filter("negative_contribution").count(),
                                   "trend_unobserved_rows": result.filter("trend_unobserved").count()}
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["seconds"] = round(time.perf_counter() - started, 3)
        save_report(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in ["integration", "integration-report", "features", "feature-report", "output", "reports"]:
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    spark = (SparkSession.builder.appName("DineIQ menu profitability")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.ansi.enabled", "true")
             .config("spark.sql.shuffle.partitions", "8").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        build_profitability(spark, args.integration, args.integration_report,
                            args.features, args.feature_report, args.output, args.reports)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
