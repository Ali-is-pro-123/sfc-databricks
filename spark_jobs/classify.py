"""Assign auditable, peer-relative menu classes from verified performance data."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import SparkSession, Window, functions as F
from spark_jobs.integrate import persist_output, require, save_report, totals


CLASSES = ("Profit Driver", "Volume Driver", "Hidden Opportunity", "Low Performer")
MONEY = ("revenue", "cost", "contribution")


def item_summary(locations):
    grouped = locations.groupBy("item_code", "item_name", "category_code", "category_name")
    summary = grouped.agg(
        F.count("restaurant_code").alias("location_count"),
        F.max("item_age_days").alias("item_age_days"),
        F.sum("order_frequency").alias("order_frequency"),
        F.sum("quantity_sold").alias("quantity_sold"),
        *(F.sum(name).alias(name) for name in MONEY),
        F.sum("rating_count").alias("rating_count"),
        F.sum(F.col("average_rating") * F.col("rating_count")).alias("rating_score_sum"),
        F.sum("eligible_customers").alias("eligible_customers"),
        F.sum(F.col("repeat_purchase_rate") * F.col("eligible_customers")).alias("repeat_customer_weighted_sum"),
        F.sum(F.when(F.col("repeat_purchase_rate").isNotNull(), F.col("eligible_customers"))
              .otherwise(F.lit(0))).alias("repeat_customer_weight"),
        F.sum("wasted_quantity").alias("wasted_quantity"),
        F.sum(F.col("promotion_dependency") * F.col("quantity_sold")).alias("promoted_quantity_estimate"),
        F.sum("prior_30d_quantity").alias("prior_30d_quantity"),
        F.sum("recent_30d_quantity").alias("recent_30d_quantity"),
        F.first("profitability_as_of").alias("profitability_as_of"),
        F.first("_month").alias("_month"))
    return (summary
        .withColumn("profit_percentage", F.when(F.col("revenue") > 0,
                    100.0 * F.col("contribution") / F.col("revenue")))
        .withColumn("average_rating", F.when(F.col("rating_count") > 0,
                    F.col("rating_score_sum") / F.col("rating_count")))
        .withColumn("repeat_purchase_rate", F.when(F.col("repeat_customer_weight") > 0,
                    F.col("repeat_customer_weighted_sum") / F.col("repeat_customer_weight")))
        .withColumn("repeat_rate_basis", F.lit("eligible customer-location weighted"))
        .withColumn("accounted_wastage_percentage", F.when(
                    F.col("quantity_sold") + F.col("wasted_quantity") > 0,
                    100.0 * F.col("wasted_quantity") /
                    (F.col("quantity_sold") + F.col("wasted_quantity"))))
        .withColumn("promotion_dependency", F.when(F.col("quantity_sold") > 0,
                    F.col("promoted_quantity_estimate") / F.col("quantity_sold")))
        .withColumn("quantity_trend_percentage", F.when(
                    (F.col("item_age_days") >= 60) & (F.col("prior_30d_quantity") > 0),
                    100.0 * (F.col("recent_30d_quantity") - F.col("prior_30d_quantity")) /
                    F.col("prior_30d_quantity")))
        .withColumn("negative_contribution", F.col("contribution") < 0)
        .drop("rating_score_sum", "repeat_customer_weighted_sum",
              "repeat_customer_weight", "promoted_quantity_estimate"))


def score_peers(frame, peer_keys):
    peers = Window.partitionBy(*peer_keys)
    result = (frame
        .withColumn("exposure_days", F.least(F.lit(90), F.col("item_age_days")))
        .withColumn("sales_velocity", F.when(F.col("exposure_days") > 0,
                    F.col("quantity_sold") / F.col("exposure_days")))
        .withColumn("contribution_per_portion", F.when(F.col("quantity_sold") > 0,
                    F.col("contribution") / F.col("quantity_sold")))
        .withColumn("peer_count", F.count("*").over(peers)))
    for metric, name in (("sales_velocity", "velocity_rank"),
                         ("order_frequency", "frequency_rank"),
                         ("profit_percentage", "margin_rank"),
                         ("contribution_per_portion", "unit_contribution_rank")):
        order = Window.partitionBy(*peer_keys).orderBy(F.coalesce(F.col(metric).cast("double"), F.lit(-1e12)))
        result = result.withColumn(name, F.percent_rank().over(order))
    result = (result
        .withColumn("demand_score", 0.65 * F.col("velocity_rank") + 0.35 * F.col("frequency_rank"))
        .withColumn("profitability_score", 0.65 * F.col("margin_rank") +
                    0.35 * F.col("unit_contribution_rank")))
    thresholds = frame.groupBy(*peer_keys).agg(
        F.percentile_approx(F.when(F.col("rating_count") >= 10, F.col("average_rating")), 0.25).alias("peer_low_rating"),
        F.percentile_approx(F.when(F.col("rating_count") >= 10, F.col("average_rating")), 0.75).alias("peer_high_rating"),
        F.percentile_approx(F.when(F.col("eligible_customers") >= 10, F.col("repeat_purchase_rate")), 0.75).alias("peer_high_repeat"),
        F.percentile_approx("accounted_wastage_percentage", 0.75).alias("peer_high_waste"),
        F.percentile_approx("promotion_dependency", 0.75).alias("peer_high_promotion"))
    result = result.join(thresholds, peer_keys)
    return (result
        .withColumn("high_demand", F.col("demand_score") >= 0.65)
        .withColumn("high_profitability", F.col("profitability_score") >= 0.65)
        .withColumn("high_recorded_waste", F.coalesce(
                    (F.col("wasted_quantity") > 0) &
                    (F.col("accounted_wastage_percentage") >= F.col("peer_high_waste")), F.lit(False)))
        .withColumn("poor_rating", F.coalesce(
                    (F.col("rating_count") >= 10) &
                    (F.col("average_rating") <= F.col("peer_low_rating")), F.lit(False)))
        .withColumn("strong_rating", F.coalesce(
                    (F.col("rating_count") >= 10) &
                    (F.col("average_rating") >= F.col("peer_high_rating")), F.lit(False)))
        .withColumn("strong_repeat", F.coalesce(
                    (F.col("eligible_customers") >= 10) &
                    (F.col("repeat_purchase_rate") >= F.col("peer_high_repeat")), F.lit(False)))
        .withColumn("high_promotion_reliance", F.coalesce(
                    (F.col("promotion_dependency") > 0) &
                    (F.col("promotion_dependency") >= F.col("peer_high_promotion")), F.lit(False)))
        .withColumn("declining_sales", F.coalesce(F.col("quantity_trend_percentage") < 0, F.lit(False))))


def apply_policy(scored):
    economic = (F.col("contribution") > 0) & (F.col("quantity_sold") > 0)
    acceptable = ~F.col("high_recorded_waste") & ~F.col("poor_rating")
    promotion_decline = F.col("high_promotion_reliance") & F.col("declining_sales")
    profit_driver = economic & F.col("high_demand") & F.col("high_profitability") & acceptable & ~promotion_decline
    volume_driver = economic & F.col("high_demand") & acceptable
    hidden = economic & ~F.col("high_demand") & acceptable & ~promotion_decline & (
        F.col("high_profitability") | F.col("strong_rating") | F.col("strong_repeat"))
    return (scored
        .withColumn("menu_class", F.when(profit_driver, "Profit Driver")
                    .when(volume_driver, "Volume Driver")
                    .when(hidden, "Hidden Opportunity")
                    .otherwise("Low Performer"))
        .withColumn("classification_reason", F.when(F.col("contribution") < 0,
                    "negative direct contribution")
                    .when(F.col("menu_class") == "Profit Driver",
                          "peer-high demand and profitability with acceptable quality and waste")
                    .when(F.col("menu_class") == "Volume Driver",
                          "peer-high demand with positive contribution but weaker combined evidence")
                    .when(F.col("menu_class") == "Hidden Opportunity",
                          "positive economics and supporting quality or profitability below high demand")
                    .when(F.col("high_recorded_waste"), "high recorded waste relative to peers")
                    .when(F.col("poor_rating"), "poor observed rating relative to peers")
                    .otherwise("insufficient combined demand and profitability evidence"))
        .withColumn("provisional_evidence", (F.col("item_age_days") < 30) |
                    (F.col("quantity_sold") < 5) | (F.col("rating_count") == 0) |
                    (F.col("eligible_customers") == 0)))


def build_classification(spark, source, source_report_path, output, report_dir):
    source, output, report_dir = (Path(p).resolve() for p in (source, output, report_dir))
    require(not output.exists() and not report_dir.exists(), "Choose unused output/report directories")
    require(not output.is_relative_to(source) and not report_dir.is_relative_to(source),
            "Outputs must be outside source")
    require(not output.is_relative_to(report_dir) and not report_dir.is_relative_to(output),
            "Keep output and report directories separate")
    raw = Path(source_report_path).read_bytes()
    upstream = json.loads(raw)
    require(upstream.get("status") == "passed", "Profitability report must be passed")
    require(upstream.get("window_days") == 90, "Expected 90-day profitability window")
    require(upstream.get("job_sha256") == hashlib.sha256(
            (Path(__file__).parent / "profitability.py").read_bytes()).hexdigest(),
            "Profitability job changed after source report")
    path = source / "item_location_performance"
    require((path / "_SUCCESS").is_file(), "Missing successful profitability output")
    started = time.perf_counter()
    report_dir.mkdir(parents=True)
    report_path = report_dir / "classification_report.json"
    report = {"status": "running", "as_of_exclusive_local_date": upstream["as_of_exclusive_local_date"],
              "source_report_sha256": hashlib.sha256(raw).hexdigest(),
              "job_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "application_id": spark.sparkContext.applicationId, "spark_version": spark.version,
              "outputs": {}, "class_labels": list(CLASSES)}
    save_report(report_path, report)
    try:
        locations = spark.read.parquet(str(path))
        require(locations.count() == upstream["outputs"]["item_location_performance"]["rows"],
                "Profitability row count changed")
        require(locations.filter(F.col("profitability_as_of") !=
                F.lit(upstream["as_of_exclusive_local_date"])).count() == 0, "Mixed cutoff dates")
        item_rows = item_summary(locations)
        inputs = {"item_location_classification": (locations, ["restaurant_code", "item_code"],
                 ["restaurant_code", "category_code"]),
                  "item_classification": (item_rows, ["item_code"], ["category_code"])}
        outputs = {}
        for name, (frame, keys, peers) in inputs.items():
            classified = apply_policy(score_peers(frame, peers))
            outputs[name], report["outputs"][name] = persist_output(spark, classified, output, name, keys)
            require(report["outputs"][name]["rows"] == frame.count(), f"Missing {name} rows")
            require(outputs[name].filter(~F.col("menu_class").isin(*CLASSES) |
                                         F.col("menu_class").isNull()).count() == 0,
                    f"Unclassified {name} row")
            require(outputs[name].filter((F.col("contribution") < 0) &
                                         (F.col("menu_class") != "Low Performer")).count() == 0,
                    f"Loss-making {name} row escaped guard")
            report["outputs"][name]["class_counts"] = {
                row.menu_class: row["count"] for row in outputs[name].groupBy("menu_class").count().collect()}
            report["outputs"][name]["provisional_count"] = outputs[name].filter("provisional_evidence").count()
            save_report(report_path, report)
        require(totals(outputs["item_location_classification"], ["quantity_sold", *MONEY]) ==
                totals(locations, ["quantity_sold", *MONEY]), "Location financial totals changed")
        require(totals(outputs["item_classification"], ["quantity_sold", *MONEY]) ==
                totals(locations, ["quantity_sold", *MONEY]), "Item financial totals changed")
        require(outputs["item_classification"].count() ==
                locations.select("item_code").distinct().count(), "Item coverage changed")
        report["conservation"] = totals(locations, ["quantity_sold", *MONEY])
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
    for name in ("input", "source-report", "output", "reports"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    spark = (SparkSession.builder.appName("DineIQ menu classification")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.ansi.enabled", "true")
             .config("spark.sql.shuffle.partitions", "8").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        build_classification(spark, args.input, args.source_report, args.output, args.reports)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
