"""Build auditable analytical grains from a verified ingestion snapshot."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark import StorageLevel
from pyspark.sql import SparkSession, functions as F
from data_generator.schemas import SCHEMAS, field_type

SQL_ROOT = Path(__file__).resolve().parents[1] / "spark_sql"


def save_report(path, report):
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(frame, keys, label):
    require(not frame.groupBy(*keys).count().filter("count > 1").take(1),
            f"Duplicate grain: {label}")


def totals(frame, columns):
    return frame.agg(*[F.coalesce(F.sum(c), F.lit(0)).alias(c) for c in columns]).first().asDict()


def load_sources(spark, source, upstream):
    frames = {}
    for table, fields in SCHEMAS.items():
        path = source / "clean" / table
        require((path / "_SUCCESS").is_file(), f"Missing successful source write: {table}")
        frame = spark.read.parquet(str(path))
        actual = {f.name: f.dataType.simpleString() for f in frame.schema.fields}
        for field in fields:
            expected = {"integer": "int", "timestamp_utc": "timestamp"}.get(
                field_type(field), field_type(field))
            require(actual.get(field) == expected, f"Source type mismatch: {table}.{field}")
        stats = frame.agg(F.count("*").alias("rows"),
                          F.countDistinct("code").alias("codes")).first()
        require(stats.rows == upstream["tables"][table]["accepted_rows"],
                f"Source count does not match report: {table}")
        require(stats.rows == stats.codes, f"Duplicate/null source code: {table}")
        frame.createOrReplaceTempView(table)
        frames[table] = frame
    for table, keys in {
        "pricing_history": ["restaurant_code", "item_code", "effective_at"],
        "ratings": ["order_item_code"],
        "inventory": ["restaurant_code", "item_code", "date"],
        "order_items": ["order_code", "line_number"],
    }.items():
        unique(frames[table], keys, table)
    for row in frames["restaurants"].select("timezone").distinct().collect():
        ZoneInfo(row.timezone)
    return frames


def order_coverage(orders, lines, quarantine, restaurants):
    accepted = lines.groupBy("order_code").agg(
        F.count("*").alias("accepted_line_count"), F.sum("quantity").alias("accepted_quantity"),
        F.sum("revenue").alias("accepted_basket_revenue"))
    # Duplicate copies alone do not make the retained basket incomplete.
    rejected = (quarantine
        .filter(F.size(F.array_except("_errors", F.array(F.lit("duplicate_exact")))) > 0)
        .withColumn("order_code", F.get_json_object("_raw_json", "$.order_code"))
        .withColumn("line_identity", F.coalesce(F.get_json_object("_raw_json", "$.code"),
                                               F.sha2("_raw_json", 256)))
        .groupBy("order_code").agg(F.countDistinct("line_identity").alias("known_rejected_lines")))
    headers = orders.select(F.col("code").alias("order_code"), "restaurant_code",
                            "customer_code", "ordered_at", "status")
    locations = restaurants.select(F.col("code").alias("restaurant_code"), "timezone")
    return (headers.join(accepted, "order_code", "left").join(rejected, "order_code", "left")
        .join(locations, "restaurant_code", "left")
        .fillna(0, ["accepted_line_count", "accepted_quantity", "accepted_basket_revenue", "known_rejected_lines"])
        .withColumn("coverage_status", F.when(F.col("accepted_line_count") == 0, "no_accepted_lines")
                    .when(F.col("known_rejected_lines") > 0, "partial")
                    .otherwise("no_known_rejections"))
        .withColumn("_month", F.date_format(F.from_utc_timestamp("ordered_at", F.col("timezone")), "yyyy-MM")))


def persist_output(spark, frame, output, name, keys):
    frame = frame.persist(StorageLevel.DISK_ONLY)
    try:
        count = frame.count()
        unique(frame, keys, name)
        require(not frame.filter(F.col("_month").isNull()).take(1), f"Null output month: {name}")
        path = output / name
        frame.write.mode("errorifexists").partitionBy("_month").parquet(str(path))
        readback = spark.read.parquet(str(path))
        require(readback.count() == count, f"Read-back count mismatch: {name}")
        return readback, {"rows": count, "keys": keys, "schema": readback.schema.jsonValue()}
    finally:
        frame.unpersist()


def integrate(spark, source, quality_report, output, report_dir):
    source, output, report_dir = (Path(p).resolve() for p in (source, output, report_dir))
    require(not output.exists() and not report_dir.exists(), "Choose unused output and report directories")
    require(not output.is_relative_to(source) and not report_dir.is_relative_to(source),
            "Outputs must be outside the immutable source snapshot")
    require(not output.is_relative_to(report_dir) and not report_dir.is_relative_to(output),
            "Output and report directories must be separate")
    report_bytes = Path(quality_report).read_bytes()
    upstream = json.loads(report_bytes)
    require(upstream.get("status") == "passed", "Upstream quality report must be passed")
    require(set(SCHEMAS).issubset(upstream.get("tables", {})), "Incomplete upstream report")
    started = time.perf_counter()
    report_dir.mkdir(parents=True)
    report = {"status": "running", "source": str(source), "upstream_report": str(quality_report),
              "upstream_sha256": hashlib.sha256(report_bytes).hexdigest(),
              "upstream_application_id": upstream.get("application_id"),
              "application_id": spark.sparkContext.applicationId, "spark_version": spark.version,
              "job_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "outputs": {}, "currency": "PKR", "day_basis": "restaurant local date",
              "sql_sha256": {name: hashlib.sha256((SQL_ROOT / name).read_bytes()).hexdigest()
                             for name in ["order_lines.sql", "item_location_daily.sql"]}}
    report_path = report_dir / "integration_report.json"
    save_report(report_path, report)
    try:
        sources = load_sources(spark, source, upstream)
        quarantine = spark.read.parquet(str(source / "quarantine" / "order_items"))
        require(quarantine.count() == upstream["tables"]["order_items"]["quarantined_rows"],
                "Quarantine count does not match report")
        fact = spark.sql((SQL_ROOT / "order_lines.sql").read_text(encoding="utf-8"))
        fact, report["outputs"]["order_lines"] = persist_output(spark, fact, output, "order_lines", ["line_code"])
        require(report["outputs"]["order_lines"]["rows"] == upstream["tables"]["order_items"]["accepted_rows"],
                "Fact joins lost or multiplied order lines")
        require(not fact.filter("broken_dimension").take(1), "Unresolved required fact dimension")
        require(fact.filter("rating_code IS NOT NULL").count() == upstream["tables"]["ratings"]["accepted_rows"],
                "Fact join lost ratings")
        source_money = sources["order_items"].selectExpr(
            "quantity * unit_price AS gross_amount", "discount_amount",
            "quantity * unit_price - discount_amount AS revenue", "quantity * unit_cost AS cost")
        money = ["gross_amount", "discount_amount", "revenue", "cost"]
        require(totals(source_money, money) == totals(fact, money), "Fact monetary totals changed")
        report["all_line_totals"] = totals(fact, money + ["quantity", "contribution"])
        report["price_checks"] = {
            "missing_history": fact.filter("missing_price_history").count(),
            "snapshot_mismatches": fact.filter("price_snapshot_mismatch").count()}
        fact.createOrReplaceTempView("integrated_lines")
        print(f"INTEGRATED order_lines: {report['outputs']['order_lines']['rows']}", flush=True)
        save_report(report_path, report)

        coverage = order_coverage(sources["orders"], fact, quarantine, sources["restaurants"])
        coverage, report["outputs"]["order_coverage"] = persist_output(
            spark, coverage, output, "order_coverage", ["order_code"])
        require(report["outputs"]["order_coverage"]["rows"] == upstream["tables"]["orders"]["accepted_rows"],
                "Order coverage lost headers")
        require(totals(coverage, ["accepted_line_count"])["accepted_line_count"] == report["outputs"]["order_lines"]["rows"],
                "Coverage line counts changed")
        report["order_coverage"] = {r.coverage_status: r['count'] for r in
                                    coverage.groupBy("coverage_status").count().collect()}
        print(f"INTEGRATED order_coverage: {report['outputs']['order_coverage']['rows']}", flush=True)
        save_report(report_path, report)

        daily = spark.sql((SQL_ROOT / "item_location_daily.sql").read_text(encoding="utf-8"))
        daily, report["outputs"]["item_location_daily"] = persist_output(
            spark, daily, output, "item_location_daily", ["restaurant_code", "item_code", "date"])
        completed = fact.filter("status = 'completed'")
        metrics = money + ["contribution"]
        require(totals(completed, metrics) == totals(daily, metrics), "Daily aggregation changed money")
        require(totals(completed, ["quantity"])["quantity"] == totals(daily, ["sold_quantity"])["sold_quantity"],
                "Daily aggregation changed sold quantity")
        require(totals(daily, ["rating_count"])["rating_count"] == upstream["tables"]["ratings"]["accepted_rows"],
                "Daily aggregation changed rating count")
        require(totals(daily, ["waste_record_count"])["waste_record_count"] == upstream["tables"]["wastage"]["accepted_rows"],
                "Daily aggregation changed wastage count")
        require(totals(daily, ["wasted_quantity"])["wasted_quantity"] == totals(sources["wastage"], ["wasted_quantity"])["wasted_quantity"],
                "Daily aggregation changed wastage quantity")
        require(daily.filter("has_inventory").count() == upstream["tables"]["inventory"]["accepted_rows"],
                "Daily integration lost inventory")
        report["completed_sales_totals"] = totals(completed, metrics + ["quantity"])
        report["cancelled_line_count"] = fact.filter("status = 'cancelled'").count()
        report["inventory_reconciliation"] = {
            "nonzero_gap_days": daily.filter("consumption_gap <> 0").count(),
            "negative_gap_days": daily.filter("consumption_gap < 0").count(),
            "missing_inventory_days": daily.filter("NOT has_inventory").count(),
            "net_gap_portions": totals(daily, ["consumption_gap"])["consumption_gap"],
            "interpretation": "Descriptive coverage difference; not an automatic stock correction"}
        print(f"INTEGRATED item_location_daily: {report['outputs']['item_location_daily']['rows']}", flush=True)
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
    for name in ["input", "quality-report", "output", "reports"]:
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    spark = (SparkSession.builder.appName("DineIQ analytical integration")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.ansi.enabled", "true")
             .config("spark.sql.shuffle.partitions", "8").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        integrate(spark, args.input, args.quality_report, args.output, args.reports)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
