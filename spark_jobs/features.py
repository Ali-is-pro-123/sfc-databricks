"""Create cutoff-aware descriptive snapshots, not trained model predictions."""

import argparse
import hashlib
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession, Window, functions as F
from spark_jobs.integrate import SQL_ROOT, load_sources, persist_output, require, save_report, totals


def prepare_views(spark, sources, fact, coverage, daily, as_of, window_days):
    cutoff = date.fromisoformat(as_of)
    require(1 <= window_days <= 3650, "window-days must be between 1 and 3650")
    start = cutoff - timedelta(days=window_days)
    split = start + timedelta(days=window_days // 2)
    before = fact.filter((F.col("date") < F.lit(cutoff)) & (F.col("status") == "completed"))
    lines = before.filter(F.col("date") >= F.lit(start))
    lines.createOrReplaceTempView("feature_lines")
    ratings = (before.filter("rating_code IS NOT NULL")
        .withColumn("rating_date", F.to_date(F.from_utc_timestamp("rated_at", F.col("restaurant_timezone"))))
        .filter((F.col("rating_date") >= F.lit(start)) & (F.col("rating_date") < F.lit(cutoff))))
    ratings.withColumn("split_date", F.lit(split)).createOrReplaceTempView("feature_ratings")
    daily.filter((F.col("date") >= F.lit(start)) & (F.col("date") < F.lit(cutoff))).createOrReplaceTempView("feature_daily")
    history = (coverage.withColumn("date", F.to_date(F.from_utc_timestamp("ordered_at", F.col("timezone"))))
               .filter((F.col("date") < F.lit(cutoff)) & (F.col("status") == "completed")))
    valid_history = history.filter("coverage_status = 'no_known_rejections' AND accepted_line_count > 0")
    valid_history.createOrReplaceTempView("historical_visits")
    channels = sources["orders"].select(F.col("code").alias("order_code"), "channel_code")
    sizes = lines.groupBy("order_code").agg(F.countDistinct("item_code").alias("distinct_items"))
    baskets = (history.filter(F.col("date") >= F.lit(start)).join(channels, "order_code", "left")
               .join(sizes, "order_code", "left").fillna(0, ["distinct_items"])
               .withColumn("customer_metric_eligible", (F.col("coverage_status") == "no_known_rejections") &
                           (F.col("accepted_line_count") > 0) & F.col("customer_code").isNotNull()))
    baskets.createOrReplaceTempView("feature_baskets")
    baskets.filter("coverage_status = 'no_known_rejections' AND accepted_line_count > 0").createOrReplaceTempView("eligible_orders")
    sources["customers"].filter(F.col("joined_on") < F.lit(cutoff)).createOrReplaceTempView("feature_customers")
    locations = sources["restaurants"].select(F.col("code").alias("restaurant_code"), "timezone")
    priced = sources["pricing_history"].join(locations, "restaurant_code")
    priced = priced.filter(F.col("effective_at") < F.to_utc_timestamp(F.lit(as_of).cast("timestamp"), F.col("timezone")))
    rank = Window.partitionBy("restaurant_code", "item_code").orderBy(F.col("effective_at").desc())
    prices = (priced.withColumn("rank", F.row_number().over(rank)).filter("rank <= 2")
        .groupBy("restaurant_code", "item_code").agg(
            F.max(F.when(F.col("rank") == 1, F.col("unit_price"))).alias("latest_unit_price"),
            F.max(F.when(F.col("rank") == 2, F.col("unit_price"))).alias("previous_unit_price")))
    prices.createOrReplaceTempView("feature_prices")
    known_items = sources["menu_items"].filter(F.col("introduced_on") < F.lit(cutoff)).select(F.col("code").alias("item_code"))
    keys = (daily.filter(F.col("date") < F.lit(cutoff)).select("restaurant_code", "item_code")
            .union(prices.select("restaurant_code", "item_code"))
            .union(lines.select("restaurant_code", "item_code")).distinct().join(known_items, "item_code"))
    keys.createOrReplaceTempView("feature_keys")
    locations_seen = keys.select("restaurant_code").union(history.select("restaurant_code")).distinct()
    (sources["restaurants"].join(locations_seen,
        sources["restaurants"].code == locations_seen.restaurant_code)
        .select(*[sources["restaurants"][c] for c in sources["restaurants"].columns])
        .createOrReplaceTempView("feature_locations"))
    return lines, baskets


def feature_frames(spark, sources, fact, coverage, daily, as_of, window_days):
    lines, baskets = prepare_views(spark, sources, fact, coverage, daily, as_of, window_days)
    items = spark.sql((SQL_ROOT / "item_features.sql").read_text())
    items = (items.withColumn("orders_per_day", F.col("order_frequency") / F.lit(window_days))
             .withColumn("item_age_days", F.datediff(F.lit(as_of), "introduced_on")))
    customers = spark.sql((SQL_ROOT / "customer_features.sql").read_text())
    customers = customers.withColumn("recency_days", F.datediff(F.lit(as_of), "last_visit_date"))
    frames = {"item_location_features": items, "customer_features": customers,
              "order_features": baskets, "location_features": spark.sql((SQL_ROOT / "location_features.sql").read_text())}
    for name, frame in frames.items():
        frames[name] = (frame.drop("_month").withColumn("feature_as_of", F.lit(as_of).cast("date"))
                        .withColumn("window_days", F.lit(window_days))
                        .withColumn("_month", F.lit(as_of[:7])))
    return frames, lines, baskets


def build_features(spark, integration_path, integration_report, output, report_dir, as_of, window_days):
    date.fromisoformat(as_of)
    require(1 <= window_days <= 3650, "window-days must be between 1 and 3650")
    integration_path, output, report_dir = (Path(p).resolve() for p in (integration_path, output, report_dir))
    require(not output.exists() and not report_dir.exists(), "Choose unused output/report directories")
    require(not output.is_relative_to(integration_path) and not report_dir.is_relative_to(integration_path),
            "Do not write inside source integration")
    require(not output.is_relative_to(report_dir) and not report_dir.is_relative_to(output), "Keep outputs separate")
    upstream_bytes = Path(integration_report).read_bytes()
    upstream = json.loads(upstream_bytes)
    require(upstream.get("status") == "passed", "Integration report must be passed")
    source = Path(upstream["source"])
    require(not output.is_relative_to(source) and not report_dir.is_relative_to(source), "Do not write inside clean sources")
    quality_bytes = Path(upstream["upstream_report"]).read_bytes()
    require(hashlib.sha256(quality_bytes).hexdigest() == upstream["upstream_sha256"], "Upstream quality report changed")
    quality = json.loads(quality_bytes)
    require(quality.get("status") == "passed", "Quality report must be passed")
    started = time.perf_counter()
    report_dir.mkdir(parents=True)
    report = {"status": "running", "as_of_exclusive_local_date": as_of, "window_days": window_days,
              "source": str(integration_path), "integration_report": str(integration_report),
              "integration_sha256": hashlib.sha256(upstream_bytes).hexdigest(),
              "job_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "sql_sha256": {name: hashlib.sha256((SQL_ROOT / name).read_bytes()).hexdigest()
                             for name in ["item_features.sql", "customer_features.sql", "location_features.sql"]},
              "application_id": spark.sparkContext.applicationId, "spark_version": spark.version, "outputs": {}}
    report_path = report_dir / "feature_report.json"
    save_report(report_path, report)
    try:
        sources = load_sources(spark, source, quality)
        inputs = {}
        for name in ["order_lines", "order_coverage", "item_location_daily"]:
            require((integration_path / name / "_SUCCESS").is_file(), f"Missing source write: {name}")
            inputs[name] = spark.read.parquet(str(integration_path / name))
            require(inputs[name].count() == upstream["outputs"][name]["rows"], f"Integrated source count mismatch: {name}")
        frames, lines, baskets = feature_frames(spark, sources, inputs["order_lines"], inputs["order_coverage"],
                                               inputs["item_location_daily"], as_of, window_days)
        keys = {"item_location_features": ["restaurant_code", "item_code"], "customer_features": ["customer_code"],
                "order_features": ["order_code"], "location_features": ["restaurant_code"]}
        outputs = {}
        for name, frame in frames.items():
            outputs[name], report["outputs"][name] = persist_output(spark, frame, output, name, keys[name])
            print(f"FEATURES {name}: {report['outputs'][name]['rows']}", flush=True)
            save_report(report_path, report)
        expected = totals(lines, ["revenue", "cost", "contribution"])
        for name in ["item_location_features", "location_features"]:
            require(totals(outputs[name], list(expected)) == expected, f"Feature totals changed: {name}")
        eligible = baskets.filter("customer_metric_eligible")
        require(totals(outputs["customer_features"], ["monetary_value"])["monetary_value"] ==
                totals(eligible, ["accepted_basket_revenue"])["accepted_basket_revenue"], "Customer spend changed")
        require(totals(outputs["customer_features"], ["frequency"])["frequency"] == eligible.count(), "Customer frequency changed")
        require(outputs["order_features"].filter(F.col("date") >= F.lit(as_of)).count() == 0, "Future orders leaked")
        report["accepted_completed_window_totals"] = expected
        report["customer_metric_eligible_orders"] = eligible.count()
        report["excluded_customer_metric_orders"] = baskets.filter("NOT customer_metric_eligible").count()
        report["observed_rating_count"] = spark.table("feature_ratings").count()
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
    for name in ["input", "integration-report", "output", "reports", "as-of"]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--window-days", type=int, default=90)
    args = parser.parse_args()
    spark = (SparkSession.builder.appName("DineIQ cutoff-aware features")
             .config("spark.sql.session.timeZone", "UTC").config("spark.sql.ansi.enabled", "true")
             .config("spark.sql.shuffle.partitions", "8").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        build_features(spark, args.input, args.integration_report, args.output, args.reports, args.as_of, args.window_days)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
