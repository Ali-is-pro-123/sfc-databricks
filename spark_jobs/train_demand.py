"""Compare three Spark MLlib models for next-calendar-month item demand."""

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.feature import OneHotEncoder, StandardScaler, StringIndexer, VectorAssembler
from pyspark.ml.regression import DecisionTreeRegressor, LinearRegression, RandomForestRegressor
from pyspark.sql import SparkSession, functions as F
from spark_jobs.integrate import persist_output, require, save_report, totals


NUMERIC_FEATURES = (
    "quantity_last_30", "quantity_previous_30", "quantity_last_90",
    "orders_last_30", "revenue_last_30", "contribution_last_90",
    "waste_last_90", "rating_mean_last_90", "rating_observed_last_90",
    "sales_days_last_90", "days_since_first_sale", "cutoff_month_sin",
    "cutoff_month_cos",
)
PREDICTORS = (*NUMERIC_FEATURES, "restaurant_code", "category_code")


def month_cutoffs(start, end):
    require(start.day == 1 and end.day == 1 and start < end,
            "Cutoff bounds must be increasing first-of-month dates")
    months = []
    index = start.year * 12 + start.month - 1
    stop = end.year * 12 + end.month - 1
    while index < stop:
        months.append(date(index // 12, index % 12 + 1, 1))
        index += 1
    return months


def make_snapshots(spark, daily, start, end, train_end, validation_end):
    dates = month_cutoffs(start, end)
    cutoffs = spark.createDataFrame([(day,) for day in dates], "cutoff date")
    keys = (daily.filter(F.col("sold_quantity") > 0)
        .groupBy("restaurant_code", "item_code")
        .agg(F.min("date").alias("first_sale_date"),
             F.first("category_code", ignorenulls=True).alias("category_code")))
    grid = (keys.crossJoin(F.broadcast(cutoffs))
        .filter(F.col("first_sale_date") < F.col("cutoff")))
    g, d = grid.alias("g"), daily.alias("d")
    match = ((F.col("g.restaurant_code") == F.col("d.restaurant_code")) &
             (F.col("g.item_code") == F.col("d.item_code")) &
             (F.col("d.date") >= F.date_sub(F.col("g.cutoff"), 90)) &
             (F.col("d.date") < F.add_months(F.col("g.cutoff"), 1)))
    observed = (g.join(d, match, "left")
        .select(F.col("g.restaurant_code").alias("restaurant_code"),
                F.col("g.item_code").alias("item_code"),
                F.col("g.category_code").alias("category_code"),
                F.col("g.first_sale_date").alias("first_sale_date"),
                F.col("g.cutoff").alias("cutoff"),
                F.col("d.date").alias("observation_date"),
                *[F.col("d." + name).alias(name) for name in
                  ("sold_quantity", "order_count", "revenue", "contribution",
                   "wasted_quantity", "rating_count", "rating_sum")]))
    day = F.col("observation_date")
    cutoff = F.col("cutoff")
    recent = (day >= F.date_sub(cutoff, 30)) & (day < cutoff)
    previous = (day >= F.date_sub(cutoff, 60)) & (day < F.date_sub(cutoff, 30))
    history = (day >= F.date_sub(cutoff, 90)) & (day < cutoff)
    future = (day >= cutoff) & (day < F.add_months(cutoff, 1))
    def amount(predicate, column):
        return F.coalesce(F.sum(F.when(predicate, F.col(column))), F.lit(0))
    frame = (observed.groupBy("restaurant_code", "item_code", "category_code",
                              "first_sale_date", "cutoff")
        .agg(amount(recent, "sold_quantity").alias("quantity_last_30"),
             amount(previous, "sold_quantity").alias("quantity_previous_30"),
             amount(history, "sold_quantity").alias("quantity_last_90"),
             amount(recent, "order_count").alias("orders_last_30"),
             amount(recent, "revenue").alias("revenue_last_30"),
             amount(history, "contribution").alias("contribution_last_90"),
             amount(history, "wasted_quantity").alias("waste_last_90"),
             amount(history, "rating_count").alias("rating_count_last_90"),
             amount(history, "rating_sum").alias("rating_sum_last_90"),
             F.countDistinct(F.when(history & (F.col("sold_quantity") > 0), day))
              .alias("sales_days_last_90"),
             amount(future, "sold_quantity").alias("label")))
    frame = (frame
        .withColumn("rating_observed_last_90", (F.col("rating_count_last_90") > 0).cast("double"))
        .withColumn("rating_mean_last_90", F.when(F.col("rating_count_last_90") > 0,
                    F.col("rating_sum_last_90") / F.col("rating_count_last_90")).otherwise(F.lit(0.0)))
        .withColumn("days_since_first_sale", F.datediff("cutoff", "first_sale_date"))
        .withColumn("cutoff_month_sin", F.sin(2 * 3.141592653589793 * F.month("cutoff") / 12))
        .withColumn("cutoff_month_cos", F.cos(2 * 3.141592653589793 * F.month("cutoff") / 12))
        .withColumn("target_month_days", F.datediff(F.add_months("cutoff", 1), "cutoff"))
        .withColumn("baseline", F.col("quantity_last_30") * F.col("target_month_days") / 30.0)
        .withColumn("split", F.when(F.col("cutoff") < F.lit(train_end), "train")
                    .when(F.col("cutoff") < F.lit(validation_end), "validation")
                    .otherwise("test"))
        .withColumn("_month", F.date_format("cutoff", "yyyy-MM")))
    for name in (*NUMERIC_FEATURES, "label", "baseline"):
        frame = frame.withColumn(name, F.col(name).cast("double"))
    return frame


def preprocess_training(train):
    stages = [
        StringIndexer(inputCol="restaurant_code", outputCol="restaurant_index", handleInvalid="keep"),
        StringIndexer(inputCol="category_code", outputCol="category_index", handleInvalid="keep"),
        OneHotEncoder(inputCols=["restaurant_index", "category_index"],
                      outputCols=["restaurant_vector", "category_vector"], handleInvalid="keep"),
        VectorAssembler(inputCols=[*NUMERIC_FEATURES, "restaurant_vector", "category_vector"],
                        outputCol="unscaled_features"),
        StandardScaler(inputCol="unscaled_features", outputCol="features", withStd=True, withMean=False),
    ]
    return Pipeline(stages=stages).fit(train)


def evaluate(frame, prediction_column):
    error = F.col(prediction_column) - F.col("label")
    row = frame.agg(
        F.count("*").alias("rows"),
        F.avg(F.abs(error)).alias("mae"),
        F.sqrt(F.avg(F.pow(error, 2))).alias("rmse"),
        F.sum(F.abs(error)).alias("absolute_error_sum"),
        F.sum("label").alias("actual_quantity"),
        F.avg(error).alias("mean_error")).first()
    require(row.rows > 0, "Evaluation partition is empty")
    return {"rows": row.rows, "mae": float(row.mae), "rmse": float(row.rmse),
            "wape": (float(row.absolute_error_sum / row.actual_quantity)
                     if row.actual_quantity else None),
            "actual_quantity": float(row.actual_quantity), "mean_error": float(row.mean_error)}


def candidate_models():
    return {
        "linear_regression": LinearRegression(labelCol="label", featuresCol="features",
                                              maxIter=40, regParam=0.1, elasticNetParam=0.0),
        "decision_tree": DecisionTreeRegressor(labelCol="label", featuresCol="features",
                                                maxDepth=5, minInstancesPerNode=20, seed=42),
        "random_forest": RandomForestRegressor(labelCol="label", featuresCol="features",
                                                numTrees=16, maxDepth=5,
                                                minInstancesPerNode=20, seed=42),
    }


def run_training(spark, integration_path, integration_report, output, report_dir,
                 model_path, start, train_end, validation_end, test_end):
    start, train_end, validation_end, test_end = (
        date.fromisoformat(value) for value in (start, train_end, validation_end, test_end))
    require(start < train_end < validation_end < test_end, "Chronological split dates must increase")
    cutoffs = month_cutoffs(start, test_end)
    require(train_end in cutoffs and validation_end in cutoffs,
            "Split dates must be first-of-month cutoffs in range")
    integration_path, output, report_dir, model_path = (
        Path(p).resolve() for p in (integration_path, output, report_dir, model_path))
    require(not output.exists() and not report_dir.exists() and not model_path.exists(),
            "Choose unused output, report and model directories")
    for target in (output, report_dir, model_path):
        require(not target.is_relative_to(integration_path), "Outputs must be outside input")
    require(not output.is_relative_to(report_dir) and not report_dir.is_relative_to(output),
            "Keep output and report directories separate")
    raw = Path(integration_report).read_bytes()
    upstream = json.loads(raw)
    require(upstream.get("status") == "passed", "Integration report must be passed")
    quality_raw = Path(upstream["upstream_report"]).read_bytes()
    require(hashlib.sha256(quality_raw).hexdigest() == upstream["upstream_sha256"],
            "Quality report changed")
    require(json.loads(quality_raw).get("status") == "passed", "Quality report must be passed")
    daily_path = integration_path / "item_location_daily"
    require((daily_path / "_SUCCESS").is_file(), "Missing integrated daily output")
    started = time.perf_counter()
    report_dir.mkdir(parents=True)
    report_path = report_dir / "demand_model_report.json"
    report = {"status": "running", "task": "next calendar month accepted sold portions",
              "source_report_sha256": hashlib.sha256(raw).hexdigest(),
              "job_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "application_id": spark.sparkContext.applicationId, "spark_version": spark.version,
              "cutoffs": {"start": start, "train_end_exclusive": train_end,
                          "validation_end_exclusive": validation_end, "test_end_exclusive": test_end},
              "feature_columns": list(PREDICTORS), "target_column": "label",
              "outputs": {}, "validation_metrics": {}}
    save_report(report_path, report)
    try:
        daily = spark.read.parquet(str(daily_path))
        require(daily.count() == upstream["outputs"]["item_location_daily"]["rows"],
                "Integrated daily row count changed")
        require(daily.agg(F.max("date")).first()[0] >=
                date.fromordinal(test_end.toordinal() - 1), "Incomplete test target month")
        snapshots = make_snapshots(spark, daily, start, test_end, train_end, validation_end)
        snapshots, report["outputs"]["supervised_snapshots"] = persist_output(
            spark, snapshots, output, "supervised_snapshots",
            ["restaurant_code", "item_code", "cutoff"])
        require(snapshots.filter((F.col("first_sale_date") >= F.col("cutoff")) |
                                 (F.col("label") < 0)).count() == 0,
                "Invalid known-pair or target row")
        report["split_rows"] = {row.split: row["count"] for row in
                                snapshots.groupBy("split").count().collect()}
        require(all(report["split_rows"].get(split, 0) > 0 for split in
                    ("train", "validation", "test")), "Empty chronological split")
        source_keys = (daily.filter(F.col("sold_quantity") > 0)
            .groupBy("restaurant_code", "item_code")
            .agg(F.min("date").alias("first_sale_date")))
        expected_target = (daily.filter((F.col("date") >= F.lit(start)) &
                                        (F.col("date") < F.lit(test_end)))
            .join(source_keys, ["restaurant_code", "item_code"])
            .filter(F.col("first_sale_date") < F.trunc(F.col("date"), "month")))
        require(totals(snapshots, ["label"])["label"] ==
                totals(expected_target, ["sold_quantity"])["sold_quantity"],
                "Future target quantity changed")
        report["target_quantity"] = totals(snapshots, ["label"])["label"]
        train = snapshots.filter("split = 'train'").cache()
        validation = snapshots.filter("split = 'validation'").cache()
        test = snapshots.filter("split = 'test'").cache()
        preprocessing = preprocess_training(train)
        train_x = preprocessing.transform(train).cache()
        validation_x = preprocessing.transform(validation).cache()
        test_x = preprocessing.transform(test).cache()
        baseline_validation = evaluate(validation, "baseline")
        report["baseline_validation"] = baseline_validation
        fitted = {}
        for name, estimator in candidate_models().items():
            model = estimator.fit(train_x)
            fitted[name] = model
            predictions = model.transform(validation_x).withColumn(
                "prediction_nonnegative", F.greatest(F.col("prediction"), F.lit(0.0)))
            report["validation_metrics"][name] = evaluate(predictions, "prediction_nonnegative")
            save_report(report_path, report)
        winner = min(report["validation_metrics"],
                     key=lambda name: (report["validation_metrics"][name]["mae"],
                                       report["validation_metrics"][name]["rmse"], name))
        report["selected_model"] = winner
        report["baseline_beats_selected_on_validation"] = (
            baseline_validation["mae"] < report["validation_metrics"][winner]["mae"])
        test_predictions = fitted[winner].transform(test_x).withColumn(
            "prediction_nonnegative", F.greatest(F.col("prediction"), F.lit(0.0)))
        report["selected_test_metrics"] = evaluate(test_predictions, "prediction_nonnegative")
        report["baseline_test_metrics"] = evaluate(test, "baseline")
        columns = ["restaurant_code", "item_code", "cutoff", "label", "prediction",
                   "prediction_nonnegative", "baseline", "_month"]
        heldout = test_predictions.select(*columns).withColumn("model_name", F.lit(winner))
        heldout, report["outputs"]["heldout_predictions"] = persist_output(
            spark, heldout, output, "heldout_predictions",
            ["restaurant_code", "item_code", "cutoff"])
        require(heldout.count() == report["split_rows"]["test"], "Missing held-out predictions")
        require(heldout.filter(F.isnan("prediction_nonnegative") |
                               F.col("prediction_nonnegative").isNull() |
                               (F.col("prediction_nonnegative") < 0)).count() == 0,
                "Invalid held-out prediction")
        pipeline = PipelineModel(stages=[*preprocessing.stages, fitted[winner]])
        pipeline.write().save(str(model_path))
        require((model_path / "metadata").is_dir(), "Fitted model save failed")
        reloaded = PipelineModel.load(str(model_path))
        require(reloaded.transform(test.limit(1)).count() == 1, "Fitted model read-back failed")
        report["model_path"] = str(model_path)
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
    for name in ("input", "integration-report", "output", "reports", "model"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--start", default="2025-05-01")
    parser.add_argument("--train-end", default="2026-01-01")
    parser.add_argument("--validation-end", default="2026-03-01")
    parser.add_argument("--test-end", default="2026-07-01")
    args = parser.parse_args()
    spark = (SparkSession.builder.appName("DineIQ next-month demand models")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.ansi.enabled", "true")
             .config("spark.sql.shuffle.partitions", "8").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        run_training(spark, args.input, args.integration_report, args.output,
                     args.reports, args.model, args.start, args.train_end,
                     args.validation_end, args.test_end)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
