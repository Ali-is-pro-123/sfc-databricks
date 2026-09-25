"""Run with spark-submit inside the project's Linux Spark container."""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_generator.schemas import SCHEMAS, REFERENCES, OPTIONAL, TRANSACTIONS, field_type
from pyspark import StorageLevel
from pyspark.sql import SparkSession, functions as F, types as T
from spark_jobs.quality import cast_and_check, conflicts, references

ORDER = ["restaurants", "menu_categories", "menu_items", "customers", "ordering_channels",
         "pricing_history", "promotions", "promotion_items", "orders", "order_items", "ratings", "inventory", "wastage"]


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ingest(spark, source, output, report_dir):
    source, output, report_dir = Path(source), Path(output), Path(report_dir)
    if source.name != "raw":
        raise ValueError("Input must be the raw/ directory, never the clean reference")
    if output.exists() or report_dir.exists():
        raise FileExistsError("Choose unused Parquet and report directories")
    # Fail before writing outputs if even one required table/header is missing.
    paths = {}
    for table in ORDER:
        paths[table] = sorted((source / table).glob("*.csv"))
        if not paths[table]:
            raise ValueError(f"Missing input table: {table}")
        for path in paths[table]:
            with path.open(newline="", encoding="utf-8") as stream:
                if next(csv.reader(stream), None) != SCHEMAS[table]:
                    raise ValueError(f"Invalid header: {path}")
    output.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    started = time.perf_counter()
    report = {"status": "running", "source": str(source), "spark_version": spark.version,
              "application_id": spark.sparkContext.applicationId, "tables": {},
              "policy": "quarantine invalid/conflicting rows; keep one exact copy; retain anonymous/cancelled orders"}
    save_json(report_dir / "quality_report.json", report)
    clean = {}
    try:
        for table in ORDER:
            tick = time.perf_counter()
            names = SCHEMAS[table]
            landing = T.StructType([T.StructField(n, T.StringType()) for n in names + ["_corrupt_record"]])
            raw = spark.read.option("header", True).option("mode", "PERMISSIVE").schema(landing).csv([str(p) for p in paths[table]])
            raw = raw.withColumn("_source_file", F.input_file_name())
            typed = cast_and_check(raw, table, names, {f: field_type(f) for f in names}, OPTIONAL)
            typed = references(conflicts(typed, table), table, clean, REFERENCES)
            typed = typed.persist(StorageLevel.DISK_ONLY)
            total = typed.count()
            if total != raw.count():
                raise ValueError(f"Reference joins changed the input row count: {table}")
            accepted = typed.filter(F.size("_errors") == 0)
            rejected = typed.filter(F.size("_errors") > 0)
            accepted_count = accepted.count()
            reasons = {r["reason"]: r["count"] for r in rejected.select(F.explode("_errors").alias("reason")).groupBy("reason").count().collect()}
            warnings = {}
            if table == "orders":
                warnings["anonymous_customer"] = accepted.filter("customer_code IS NULL").count()
                warnings["cancelled_retained"] = accepted.filter("status = 'cancelled'").count()
            result = accepted.select(*names, *(["_month"] if "_month" in accepted.columns else []))
            if table in TRANSACTIONS and table != "order_items":
                result = result.withColumn("_month", F.date_format(TRANSACTIONS[table], "yyyy-MM"))
            destination = output / "clean" / table
            writer = result.write.mode("errorifexists")
            if "_month" in result.columns:
                writer = writer.partitionBy("_month")
            writer.parquet(str(destination))
            rejected.select(*names, "_raw_json", "_corrupt_record", "_source_file", "_errors").write.mode("errorifexists").parquet(str(output / "quarantine" / table))
            clean[table] = spark.read.parquet(str(destination))
            readback = clean[table].count()
            quarantine_count = spark.read.parquet(str(output / "quarantine" / table)).count()
            if readback != accepted_count or total != readback + quarantine_count:
                raise ValueError(f"Row conservation failed: {table}")
            report["tables"][table] = {"input_files": len(paths[table]), "input_rows": total,
                "accepted_rows": accepted_count, "quarantined_rows": quarantine_count,
                "reason_counts": reasons, "warnings": warnings, "seconds": round(time.perf_counter() - tick, 3),
                "schema": clean[table].schema.jsonValue()}
            typed.unpersist()
            save_json(report_dir / "quality_report.json", report)
            print(f"QUALITY {table}: input={total} accepted={accepted_count} quarantined={quarantine_count}", flush=True)
        inferred = spark.read.option("header", True).option("inferSchema", True).csv(str(paths["orders"][0]))
        save_json(report_dir / "inferred_orders_schema.json", inferred.schema.jsonValue())
        report.update(status="passed", seconds=round(time.perf_counter() - started, 3))
    except Exception as error:
        report.update(status="failed", error=str(error), seconds=round(time.perf_counter() - started, 3))
        raise
    finally:
        save_json(report_dir / "quality_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reports", required=True)
    args = parser.parse_args()
    spark = (SparkSession.builder.appName("DineIQ ingestion and quality")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.ansi.enabled", "false")
             .config("spark.sql.shuffle.partitions", "8")
             .config("spark.sql.adaptive.enabled", "true").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        ingest(spark, args.input, args.output, args.reports)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
