"""Audit difficult SRS menu cases without reusing synthetic scenario labels."""

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


CASE_COLUMNS = (
    "high_sales_loss", "profitable_low_demand", "popular_high_waste",
    "high_rating_low_profit", "low_rating_high_sales", "promotion_dependent",
    "location_difference", "weekend_dominant", "possible_seasonal_pattern",
    "new_insufficient_history",
)


def shift_months(day, offset):
    month_index = day.year * 12 + day.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def seasonal_evidence(lines, cutoff):
    require(cutoff.day == 1, "Seasonal comparison needs a first-of-month cutoff")
    current_start = shift_months(cutoff, -6)
    current_middle = shift_months(cutoff, -3)
    prior_start = shift_months(cutoff, -18)
    prior_middle = shift_months(cutoff, -15)
    prior_end = shift_months(cutoff, -12)
    observed = lines.filter(
        (F.col("status") == "completed") &
        (((F.col("date") >= F.lit(prior_start)) & (F.col("date") < F.lit(prior_end))) |
         ((F.col("date") >= F.lit(current_start)) & (F.col("date") < F.lit(cutoff)))))
    segment = (F.when(F.col("date") < F.lit(prior_middle), "prior_first")
        .when(F.col("date") < F.lit(prior_end), "prior_second")
        .when(F.col("date") < F.lit(current_middle), "current_first")
        .otherwise("current_second"))
    frame = observed.withColumn("segment", segment).groupBy("item_code").agg(*[
        F.coalesce(F.sum(F.when(F.col("segment") == label, F.col("quantity"))), F.lit(0)).alias(label + "_quantity")
        for label in ("prior_first", "prior_second", "current_first", "current_second")])
    prior_first_days = (prior_middle - prior_start).days
    prior_second_days = (prior_end - prior_middle).days
    current_first_days = (current_middle - current_start).days
    current_second_days = (cutoff - current_middle).days
    frame = (frame
        .withColumn("prior_first_rate", F.col("prior_first_quantity") / F.lit(prior_first_days))
        .withColumn("prior_second_rate", F.col("prior_second_quantity") / F.lit(prior_second_days))
        .withColumn("current_first_rate", F.col("current_first_quantity") / F.lit(current_first_days))
        .withColumn("current_second_rate", F.col("current_second_quantity") / F.lit(current_second_days)))
    first_dominant = ((F.col("prior_first_rate") >= 1.5 * F.col("prior_second_rate")) &
                      (F.col("current_first_rate") >= 1.5 * F.col("current_second_rate")))
    second_dominant = ((F.col("prior_second_rate") >= 1.5 * F.col("prior_first_rate")) &
                       (F.col("current_second_rate") >= 1.5 * F.col("current_first_rate")))
    return (frame
        .withColumn("seasonal_half", F.when(first_dominant, "first")
                    .when(second_dominant, "second"))
        .withColumn("seasonal_pattern_observed",
                    (F.col("prior_first_quantity") + F.col("prior_second_quantity") >= 50) &
                    (F.col("current_first_quantity") + F.col("current_second_quantity") >= 50) &
                    F.col("seasonal_half").isNotNull())
        .withColumn("seasonal_prior_start", F.lit(prior_start).cast("date"))
        .withColumn("seasonal_current_start", F.lit(current_start).cast("date")))


def local_evidence(locations, items, cutoff):
    window_start = cutoff - timedelta(days=90)
    weekend_days = sum((window_start + timedelta(days=index)).weekday() >= 5 for index in range(90))
    weekday_days = 90 - weekend_days
    joined = locations.join(items.select("item_code", F.col("menu_class").alias("item_wide_class")), "item_code")
    weekend_orders = F.col("weekend_order_ratio") * F.col("order_frequency")
    weekday_orders = (1 - F.col("weekend_order_ratio")) * F.col("order_frequency")
    return (joined
        .withColumn("weekend_days_in_window", F.lit(weekend_days))
        .withColumn("weekday_days_in_window", F.lit(weekday_days))
        .withColumn("weekend_orders_estimate", weekend_orders)
        .withColumn("weekday_orders_estimate", weekday_orders)
        .withColumn("weekend_daily_order_rate", weekend_orders / F.lit(weekend_days))
        .withColumn("weekday_daily_order_rate", weekday_orders / F.lit(weekday_days))
        .withColumn("case_weekend_dominant", F.coalesce(
                    (F.col("order_frequency") >= 20) &
                    (F.col("weekend_order_ratio") >= 0.65) &
                    (F.col("weekend_daily_order_rate") >= 3 * F.col("weekday_daily_order_rate")),
                    F.lit(False)))
        .withColumn("differs_from_item_wide_class", F.col("menu_class") != F.col("item_wide_class")))


def item_evidence(items, local, seasonal, cutoff):
    location_mix = (local.filter(F.col("quantity_sold") >= 5)
        .groupBy("item_code").agg(
            F.count("*").alias("sold_location_count"),
            F.countDistinct("menu_class").alias("sold_location_class_count")))
    weekend = (local.groupBy("item_code")
        .agg(F.sum(F.when(F.col("case_weekend_dominant"), 1).otherwise(0)).alias("weekend_dominant_location_count")))
    joined = items.join(location_mix, "item_code", "left").join(weekend, "item_code", "left")
    joined = joined.join(seasonal, "item_code", "left")
    for field in ("sold_location_count", "sold_location_class_count", "weekend_dominant_location_count",
                  "prior_first_quantity", "prior_second_quantity", "current_first_quantity", "current_second_quantity"):
        joined = joined.withColumn(field, F.coalesce(F.col(field), F.lit(0)))
    introduced_on = F.date_sub(F.lit(cutoff), F.col("item_age_days").cast("int"))
    return (joined
        .withColumn("case_high_sales_loss", F.col("high_demand") & (F.col("contribution") < 0))
        .withColumn("case_profitable_low_demand", ~F.col("high_demand") & F.col("high_profitability") &
                    (F.col("contribution") > 0) & (F.col("quantity_sold") > 0))
        .withColumn("case_popular_high_waste", F.col("high_demand") & F.col("high_recorded_waste"))
        .withColumn("case_high_rating_low_profit", F.col("strong_rating") & ~F.col("high_profitability") &
                    (F.col("rating_count") >= 10))
        .withColumn("case_low_rating_high_sales", F.col("poor_rating") & F.col("high_demand"))
        .withColumn("case_promotion_dependent", F.col("high_promotion_reliance") &
                    (F.col("promotion_dependency") >= 0.25))
        .withColumn("case_location_difference", (F.col("sold_location_count") >= 2) &
                    (F.col("sold_location_class_count") >= 2))
        .withColumn("case_weekend_dominant", F.col("weekend_dominant_location_count") > 0)
        .withColumn("case_possible_seasonal_pattern", F.coalesce(
                    F.col("seasonal_pattern_observed") & (introduced_on <= F.col("seasonal_prior_start")),
                    F.lit(False)))
        .withColumn("case_new_insufficient_history", (F.col("item_age_days") < 30) &
                    F.col("quantity_trend_percentage").isNull())
        .withColumn("audit_as_of", F.lit(cutoff).cast("date")))


def case_summary(frame):
    rows = frame.select("item_code", "item_name", "menu_class", "quantity_sold",
                        "contribution", *["case_" + name for name in CASE_COLUMNS]).collect()
    summary = {}
    for name in CASE_COLUMNS:
        field = "case_" + name
        matches = [row for row in rows if row[field]]
        matches.sort(key=lambda row: (-row.quantity_sold, row.item_code))
        summary[name] = {"count": len(matches), "examples": [
            {"item_code": row.item_code, "item_name": row.item_name,
             "menu_class": row.menu_class, "quantity_sold": row.quantity_sold,
             "contribution": row.contribution} for row in matches[:5]]}
    return summary


def run_audit(spark, classification_path, classification_report, profitability_report_path,
              integration_path, integration_report, output, report_dir):
    classification_path, integration_path, output, report_dir = (
        Path(p).resolve() for p in (classification_path, integration_path, output, report_dir))
    require(not output.exists() and not report_dir.exists(), "Choose unused output/report directories")
    for target in (output, report_dir):
        require(not target.is_relative_to(classification_path) and
                not target.is_relative_to(integration_path), "Outputs must be outside inputs")
    require(not output.is_relative_to(report_dir) and not report_dir.is_relative_to(output),
            "Keep output and report directories separate")
    classification_raw = Path(classification_report).read_bytes()
    classification = json.loads(classification_raw)
    integration_raw = Path(integration_report).read_bytes()
    integration = json.loads(integration_raw)
    require(classification.get("status") == "passed" and integration.get("status") == "passed",
            "Upstream reports must be passed")
    require(classification["job_sha256"] == hashlib.sha256(
            (Path(__file__).parent / "classify.py").read_bytes()).hexdigest(),
            "Classifier changed after report")
    profitability_report_path = Path(profitability_report_path)
    require(profitability_report_path.is_file(), "Missing matching profitability report")
    profitability_raw = profitability_report_path.read_bytes()
    profitability = json.loads(profitability_raw)
    require(hashlib.sha256(profitability_raw).hexdigest() == classification["source_report_sha256"],
            "Profitability report changed")
    require(profitability["integration_report_sha256"] == hashlib.sha256(integration_raw).hexdigest(),
            "Integration report changed")
    cutoff = date.fromisoformat(classification["as_of_exclusive_local_date"])
    require(cutoff.isoformat() == classification["as_of_exclusive_local_date"], "Invalid cutoff")
    for name in ("item_classification", "item_location_classification"):
        require((classification_path / name / "_SUCCESS").is_file(), f"Missing {name} output")
    require((integration_path / "order_lines" / "_SUCCESS").is_file(), "Missing integrated lines")
    started = time.perf_counter()
    report_dir.mkdir(parents=True)
    report_path = report_dir / "case_audit_report.json"
    report = {"status": "running", "as_of_exclusive_local_date": cutoff,
              "classification_report_sha256": hashlib.sha256(classification_raw).hexdigest(),
              "integration_report_sha256": hashlib.sha256(integration_raw).hexdigest(),
              "job_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "application_id": spark.sparkContext.applicationId, "spark_version": spark.version,
              "outputs": {}}
    save_report(report_path, report)
    try:
        items = spark.read.parquet(str(classification_path / "item_classification"))
        locations = spark.read.parquet(str(classification_path / "item_location_classification"))
        lines = spark.read.parquet(str(integration_path / "order_lines"))
        require(items.count() == classification["outputs"]["item_classification"]["rows"],
                "Item classification row count changed")
        require(locations.count() == classification["outputs"]["item_location_classification"]["rows"],
                "Local classification row count changed")
        require(lines.count() == integration["outputs"]["order_lines"]["rows"],
                "Integrated line count changed")
        require(items.filter(F.col("profitability_as_of") != F.lit(cutoff)).count() == 0,
                "Mixed item cutoffs")
        require(locations.filter(F.col("profitability_as_of") != F.lit(cutoff)).count() == 0,
                "Mixed local cutoffs")
        local = local_evidence(locations, items, cutoff)
        seasonal = seasonal_evidence(lines, cutoff)
        item = item_evidence(items, local, seasonal, cutoff)
        local_out, report["outputs"]["location_case_audit"] = persist_output(
            spark, local, output, "location_case_audit", ["restaurant_code", "item_code"])
        item_out, report["outputs"]["item_case_audit"] = persist_output(
            spark, item, output, "item_case_audit", ["item_code"])
        require(local_out.count() == locations.count() and item_out.count() == items.count(),
                "Audit row coverage changed")
        money = ["quantity_sold", "revenue", "cost", "contribution"]
        require(totals(local_out, money) == totals(locations, money), "Local money changed")
        require(totals(item_out, money) == totals(items, money), "Item money changed")
        require(item_out.filter(F.col("case_high_sales_loss") &
                                (F.col("menu_class") != "Low Performer")).count() == 0,
                "High-sales loss escaped Low Performer class")
        for flag in ("case_popular_high_waste", "case_low_rating_high_sales"):
            require(item_out.filter(F.col(flag) & F.col("menu_class").isin(
                    "Profit Driver", "Volume Driver")).count() == 0,
                    f"Risky case escaped class guard: {flag}")
        require(item_out.filter(F.col("case_new_insufficient_history") &
                                ~F.col("provisional_evidence")).count() == 0,
                "New item lacks provisional evidence flag")
        report["cases"] = case_summary(item_out)
        report["conservation"] = totals(item_out, money)
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
    for name in ("classification", "classification-report", "profitability-report",
                 "integration", "integration-report", "output", "reports"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    spark = (SparkSession.builder.appName("DineIQ tricky case audit")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.ansi.enabled", "true")
             .config("spark.sql.shuffle.partitions", "8").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        run_audit(spark, args.classification, args.classification_report,
                  args.profitability_report, args.integration, args.integration_report,
                  args.output, args.reports)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
