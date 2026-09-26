"""Run reproducible descriptive analysis over verified restaurant transactions."""

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark import StorageLevel
from pyspark.sql import SparkSession, functions as F
from spark_jobs.integrate import SQL_ROOT, load_sources, persist_output, require, save_report, totals


TABLES = {
    "items": ("eda_items.sql", ["item_code"]),
    "categories": ("eda_categories.sql", ["category_code"]),
    "locations": ("eda_locations.sql", ["restaurant_code"]),
    "channels": ("eda_channels.sql", ["channel_code"]),
    "promotions": ("eda_promotions.sql", ["has_line_promotion", "promotion_code"]),
    "hours": ("eda_hours.sql", ["local_hour"]),
    "weekdays": ("eda_weekdays.sql", ["iso_weekday"]),
    "months": ("eda_months.sql", ["local_month"]),
    "location_hours": ("eda_location_hours.sql", ["restaurant_code", "local_hour"]),
    "location_days": ("eda_location_days.sql", ["restaurant_code", "date"]),
}
MONEY = ["revenue", "cost", "contribution"]


def prepare_views(spark, sources, fact, coverage, daily, as_of):
    cutoff = date.fromisoformat(as_of)
    require(cutoff.isoformat() == as_of, "as-of must use YYYY-MM-DD")
    lines = (fact.filter((F.col("status") == "completed") & (F.col("date") < F.lit(cutoff)))
        .select("line_code", "order_code", "restaurant_code", "item_code", "category_code",
                "channel_code", "line_promotion_code", "ordered_local_at", "date",
                "quantity", "gross_amount", "discount_amount", "revenue", "cost", "contribution",
                "rating_code", "rating_score", "rated_at", "restaurant_timezone")
        .persist(StorageLevel.DISK_ONLY))
    lines.createOrReplaceTempView("eda_lines")
    ratings = (lines.filter("rating_code IS NOT NULL")
        .withColumn("rating_date", F.to_date(F.from_utc_timestamp("rated_at", F.col("restaurant_timezone"))))
        .filter(F.col("rating_date") < F.lit(cutoff))
        .select("rating_code", "item_code", "rating_score", "rating_date")
        .persist(StorageLevel.DISK_ONLY))
    ratings.createOrReplaceTempView("eda_ratings")
    days = (daily.filter(F.col("date") < F.lit(cutoff))
        .select("restaurant_code", "item_code", "category_code", "date",
                "sales_line_count", "sold_quantity", "revenue", "cost", "contribution",
                "wasted_quantity", "waste_cost", "prepared_quantity", "waste_record_count",
                "rating_count", "has_inventory", "consumption_gap")
        .persist(StorageLevel.DISK_ONLY))
    days.createOrReplaceTempView("eda_daily")
    headers = (coverage
        .withColumn("date", F.to_date(F.from_utc_timestamp("ordered_at", F.col("timezone"))))
        .filter((F.col("status") == "completed") & (F.col("date") < F.lit(cutoff)))
        .select("order_code", "restaurant_code", "customer_code", "coverage_status", "date")
        .join(sources["orders"].select(F.col("code").alias("order_code"), "channel_code"),
              "order_code")
        .persist(StorageLevel.DISK_ONLY))
    headers.createOrReplaceTempView("eda_orders")
    sources["menu_items"].filter(F.col("introduced_on") < F.lit(cutoff)).createOrReplaceTempView("eda_catalog")
    spark.createDataFrame([(cutoff,)], "cutoff date").createOrReplaceTempView("eda_context")
    return {"lines": lines, "ratings": ratings, "daily": days, "orders": headers}


def check_totals(views, output_tables):
    expected = totals(views["lines"], ["quantity"] + MONEY)
    expected_waste = totals(views["daily"], ["wasted_quantity", "waste_record_count"])
    rated = views["ratings"].count()
    require(totals(views["daily"], ["rating_count"])["rating_count"] == rated,
            "Daily and line rating counts differ")
    for name in ["items", "categories", "locations", "channels", "promotions",
                 "hours", "weekdays", "months", "location_hours", "location_days"]:
        observed = totals(output_tables[name], ["quantity_sold"] + MONEY)
        require(observed["quantity_sold"] == expected["quantity"], f"Quantity changed in {name}")
        for amount in MONEY:
            require(observed[amount] == expected[amount], f"{amount} changed in {name}")
    for name in ["items", "locations", "location_days"]:
        actual = totals(output_tables[name], ["wasted_quantity"])["wasted_quantity"]
        require(actual == expected_waste["wasted_quantity"], f"Waste quantity changed in {name}")
    require(totals(output_tables["items"], ["rating_count"])["rating_count"] == rated,
            "Item rating count changed")
    require(totals(output_tables["items"], ["waste_record_count"])["waste_record_count"] ==
            expected_waste["waste_record_count"], "Waste record count changed")
    headers = views["orders"].count()
    for name in ["locations", "channels", "location_days"]:
        actual = totals(output_tables[name], ["completed_header_count"])["completed_header_count"]
        require(actual == headers, f"Header count changed in {name}")
    bearing = views["lines"].select("order_code").distinct().count()
    for name in ["locations", "channels", "hours", "weekdays", "months", "location_hours"]:
        field = "sales_bearing_order_count" if name in ["locations", "channels"] else "order_count"
        actual = totals(output_tables[name], [field])[field]
        require(actual == bearing, f"Distinct sales order count changed in {name}")
    require(output_tables["hours"].count() == 24, "Expected 24 local hours")
    require(output_tables["weekdays"].count() == 7, "Expected 7 local weekdays")
    require(output_tables["location_hours"].count() == output_tables["locations"].count() * 24,
            "Location-hour grid is incomplete")
    return {"completed_line_totals": expected, "completed_header_count": headers,
            "sales_bearing_order_count": bearing, "observed_rating_count": rated,
            "observed_waste": expected_waste}


def ranking_rows(frame, metric, direction, limit, predicate=None):
    if predicate is not None:
        frame = frame.filter(predicate)
    value = F.col(metric).asc() if direction == "asc" else F.col(metric).desc()
    result = frame.orderBy(value, F.col("item_code").asc()).limit(limit).collect()
    fields = ["item_code", "item_name", "category_name", "introduced_on", "exposure_days",
              "quantity_sold", "revenue", "cost", "contribution", "margin_percentage",
              "rating_count", "average_rating", "wasted_quantity",
              "waste_share_of_accounted_portions", "promoted_quantity"]
    return [{"rank": number, **{field: row[field] for field in fields}}
            for number, row in enumerate(result, start=1)]


def rankings(items, categories, hours, weekdays, months, locations, channels, promotions,
             minimum_ratings, limit):
    rating_filter = F.col("rating_count") >= minimum_ratings
    positive_revenue = F.col("revenue") > 0
    ranked = {
        "top_selling": ranking_rows(items, "quantity_sold", "desc", limit),
        "lowest_selling": ranking_rows(items, "quantity_sold", "asc", limit),
        "highest_revenue": ranking_rows(items, "revenue", "desc", limit),
        "highest_contribution": ranking_rows(items, "contribution", "desc", limit),
        "highest_margin": ranking_rows(items, "margin_percentage", "desc", limit, positive_revenue),
        "highest_recorded_waste": ranking_rows(items, "wasted_quantity", "desc", limit),
        "best_rated": ranking_rows(items, "average_rating", "desc", limit, rating_filter),
        "poorly_rated": ranking_rows(items, "average_rating", "asc", limit, rating_filter),
    }
    snapshots = {
        "most_popular_category": categories.orderBy(F.desc("quantity_sold"), "category_code").first(),
        "peak_local_hour": hours.orderBy(F.desc("order_count"), "local_hour").first(),
        "peak_weekday": weekdays.orderBy(F.desc("order_count"), "iso_weekday").first(),
        "peak_month": months.orderBy(F.desc("order_count"), "local_month").first(),
        "highest_revenue_location": locations.orderBy(F.desc("revenue"), "restaurant_code").first(),
        "most_used_channel": channels.orderBy(F.desc("completed_header_count"), "channel_code").first(),
        "most_revenue_line_campaign": promotions.filter("has_line_promotion")
            .orderBy(F.desc("revenue"), "promotion_code").first(),
    }
    return {"items": ranked, "other_leaders": {
        key: value.asDict() if value is not None else None for key, value in snapshots.items()}}


def run_eda(spark, integration_path, integration_report, output, report_dir,
            as_of, minimum_ratings=30, top_n=10):
    cutoff = date.fromisoformat(as_of)
    require(cutoff.isoformat() == as_of, "as-of must use YYYY-MM-DD")
    require(1 <= minimum_ratings <= 100000, "min-ratings must be positive")
    require(1 <= top_n <= 100, "top-n must be between 1 and 100")
    integration_path, output, report_dir = (Path(p).resolve() for p in
                                            (integration_path, output, report_dir))
    require(not output.exists() and not report_dir.exists(), "Choose unused output and report directories")
    require(not output.is_relative_to(integration_path) and not report_dir.is_relative_to(integration_path),
            "Outputs must be outside integration input")
    require(not output.is_relative_to(report_dir) and not report_dir.is_relative_to(output),
            "Keep output and report directories separate")
    upstream_bytes = Path(integration_report).read_bytes()
    upstream = json.loads(upstream_bytes)
    require(upstream.get("status") == "passed", "Integration report must be passed")
    source = Path(upstream["source"])
    require(not output.is_relative_to(source) and not report_dir.is_relative_to(source),
            "Outputs must be outside clean input")
    quality_bytes = Path(upstream["upstream_report"]).read_bytes()
    require(hashlib.sha256(quality_bytes).hexdigest() == upstream["upstream_sha256"],
            "Upstream quality report changed")
    quality = json.loads(quality_bytes)
    require(quality.get("status") == "passed", "Quality report must be passed")
    started = time.perf_counter()
    report_dir.mkdir(parents=True)
    report = {"status": "running", "as_of_exclusive_local_date": as_of,
              "minimum_rating_count": minimum_ratings, "top_n": top_n,
              "integration_input": str(integration_path),
              "integration_report": str(integration_report),
              "integration_sha256": hashlib.sha256(upstream_bytes).hexdigest(),
              "job_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "sql_sha256": {sql: hashlib.sha256((SQL_ROOT / sql).read_bytes()).hexdigest()
                             for sql, _ in TABLES.values()},
              "application_id": spark.sparkContext.applicationId, "spark_version": spark.version,
              "currency": "PKR", "outputs": {}}
    report_path = report_dir / "eda_report.json"
    save_report(report_path, report)
    views = {}
    try:
        sources = load_sources(spark, source, quality)
        inputs = {}
        for name in ["order_lines", "order_coverage", "item_location_daily"]:
            path = integration_path / name
            require((path / "_SUCCESS").is_file(), f"Missing successful integration output: {name}")
            inputs[name] = spark.read.parquet(str(path))
            require(inputs[name].count() == upstream["outputs"][name]["rows"],
                    f"Integration row count differs from report: {name}")
        views = prepare_views(spark, sources, inputs["order_lines"], inputs["order_coverage"],
                              inputs["item_location_daily"], as_of)
        latest_source_date = inputs["order_lines"].agg(F.max("date")).first()[0]
        report["includes_all_integrated_order_dates"] = bool(latest_source_date and latest_source_date < cutoff)
        if report["includes_all_integrated_order_dates"]:
            observed = totals(views["lines"], ["quantity"] + MONEY)
            recorded = upstream["completed_sales_totals"]
            for metric, amount in observed.items():
                require(str(amount) == str(recorded[metric]),
                        f"Completed {metric} differs from upstream integration report")
        output_tables = {}
        for name, (sql_name, keys) in TABLES.items():
            frame = spark.sql((SQL_ROOT / sql_name).read_text(encoding="utf-8"))
            frame = frame.withColumn("analysis_as_of", F.lit(cutoff).cast("date"))
            partition = F.date_format("date", "yyyy-MM") if name == "location_days" else (
                F.col("local_month") if name == "months" else F.lit(as_of[:7]))
            frame = frame.withColumn("_month", partition)
            output_tables[name], report["outputs"][name] = persist_output(spark, frame, output, name, keys)
            print(f"EDA {name}: {report['outputs'][name]['rows']}", flush=True)
            save_report(report_path, report)
        report["conservation"] = check_totals(views, output_tables)
        report["rankings"] = rankings(
            output_tables["items"], output_tables["categories"], output_tables["hours"],
            output_tables["weekdays"], output_tables["months"], output_tables["locations"],
            output_tables["channels"], output_tables["promotions"], minimum_ratings, top_n)
        report["observed_local_dates"] = {"first": views["orders"].agg(F.min("date")).first()[0],
                                          "last": views["orders"].agg(F.max("date")).first()[0]}
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        for frame in views.values():
            frame.unpersist()
        report["seconds"] = round(time.perf_counter() - started, 3)
        save_report(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in ["input", "integration-report", "output", "reports", "as-of"]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--min-ratings", type=int, default=30)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()
    spark = (SparkSession.builder.appName("DineIQ exploratory analysis")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.ansi.enabled", "true")
             .config("spark.sql.shuffle.partitions", "8").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        run_eda(spark, args.input, args.integration_report, args.output, args.reports,
                args.as_of, args.min_ratings, args.top_n)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
