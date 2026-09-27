"""Build and train next-month demand forecasts from accepted clean records."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path

import duckdb
import joblib
import numpy as np
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parents[1]
TABLES = ("orders", "order_items", "restaurants", "menu_items", "ratings", "wastage")
NUMERIC = (
    "quantity_last_30", "quantity_previous_30", "quantity_last_90",
    "orders_last_30", "revenue_last_30", "contribution_last_90",
    "waste_last_90", "rating_mean_last_90", "rating_observed_last_90",
    "sales_days_last_90", "days_since_first_sale", "cutoff_month_sin",
    "cutoff_month_cos",
)
FEATURES = (*NUMERIC, "restaurant_code", "category_code")
START, END = date(2025, 5, 1), date(2026, 7, 1)
TRAIN_END, VALIDATION_END = date(2026, 1, 1), date(2026, 3, 1)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sql_path(path):
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def validate_paths(clean, quality, output, reports, model):
    require(clean.is_dir(), f"Missing clean directory: {clean}")
    require(quality.is_file(), f"Missing quality report: {quality}")
    for target in (output, reports, model):
        require(not target.exists(), f"Refusing to overwrite existing path: {target}")
        require(not target.resolve().is_relative_to(clean.resolve()),
                f"Output cannot be inside clean source: {target}")
    targets = [path.resolve() for path in (output, reports, model)]
    require(len(set(targets)) == 3, "Output, reports and model paths must differ")
    return json.loads(quality.read_text(encoding="utf-8"))


def register_sources(con, clean, quality):
    require(quality.get("status") == "passed", "Step 5 quality report did not pass")
    counts = {}
    for table in TABLES:
        folder = clean / table
        require((folder / "_SUCCESS").is_file(), f"Missing clean success marker: {table}")
        require(any(folder.rglob("*.parquet")), f"Missing clean Parquet: {table}")
        pattern = sql_path(folder) + "/**/*.parquet"
        con.execute(f"CREATE VIEW clean_{table} AS SELECT * FROM read_parquet('{pattern}')")
        count = con.execute(f"SELECT COUNT(*) FROM clean_{table}").fetchone()[0]
        expected = quality["tables"][table]["accepted_rows"]
        require(count == expected, f"Accepted-row mismatch for {table}: {count} != {expected}")
        counts[table] = count
    return counts


def cutoffs():
    index = START.year * 12 + START.month - 1
    stop = END.year * 12 + END.month - 1
    return [date(i // 12, i % 12 + 1, 1) for i in range(index, stop)]


def build_snapshots(con):
    con.execute((Path(__file__).parent / "sql" / "clean_daily.sql").read_text(encoding="utf-8"))
    direct = con.execute("""SELECT SUM(i.quantity),
        SUM(i.quantity * i.unit_price - i.discount_amount),
        SUM(i.quantity * i.unit_cost)
        FROM clean_order_items i JOIN clean_orders o ON i.order_code=o.code
        WHERE o.status='completed'""").fetchone()
    aggregate = con.execute("SELECT SUM(sold_quantity), SUM(revenue), SUM(cost) FROM daily").fetchone()
    require(tuple(round(float(x or 0), 2) for x in direct) ==
            tuple(round(float(x or 0), 2) for x in aggregate),
            "Independent sales totals do not reconcile to clean lines")
    con.execute("CREATE OR REPLACE TEMP TABLE cutoffs (cutoff DATE)")
    con.executemany("INSERT INTO cutoffs VALUES (?)", [(day,) for day in cutoffs()])
    con.execute((Path(__file__).parent / "sql" / "snapshots.sql").read_text(encoding="utf-8"),
                [TRAIN_END, VALIDATION_END])
    duplicates = con.execute("""SELECT COUNT(*) FROM (
        SELECT restaurant_code,item_code,cutoff FROM supervised_snapshots
        GROUP BY 1,2,3 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicates == 0, "Duplicate snapshot keys")
    invalid = con.execute("""SELECT COUNT(*) FROM supervised_snapshots
        WHERE first_sale_date >= cutoff OR label < 0 OR cutoff < ? OR cutoff >= ?""",
        [START, END]).fetchone()[0]
    require(invalid == 0, "Invalid snapshot chronology or label")
    source_target = con.execute("""SELECT SUM(d.sold_quantity) FROM sale_days d
        JOIN first_sales k USING (restaurant_code,item_code)
        WHERE d.local_date >= ? AND d.local_date < ?
        AND k.first_sale_date < date_trunc('month', d.local_date)""",
        [START, END]).fetchone()[0]
    snapshot_target = con.execute("SELECT SUM(label) FROM supervised_snapshots").fetchone()[0]
    require(float(source_target) == float(snapshot_target),
            "Monthly labels do not reconcile to independent daily sales")
    counts = dict(con.execute("SELECT split, COUNT(*) FROM supervised_snapshots GROUP BY split").fetchall())
    require(all(counts.get(s, 0) > 0 for s in ("train", "validation", "test")),
            "A chronological split is empty")
    return {"source_sales": [str(x) for x in direct], "daily_sales": [str(x) for x in aggregate],
            "target_quantity": float(snapshot_target), "split_rows": counts,
            "snapshot_rows": sum(counts.values())}


def metrics(actual, predicted):
    error = np.asarray(predicted, dtype=float) - np.asarray(actual, dtype=float)
    actual = np.asarray(actual, dtype=float)
    absolute = np.abs(error)
    return {"rows": int(len(actual)), "mae": float(absolute.mean()),
            "rmse": float(np.sqrt(np.mean(error ** 2))),
            "wape": float(absolute.sum() / actual.sum()) if actual.sum() else None,
            "actual_quantity": float(actual.sum()), "mean_error": float(error.mean())}


def train_models(con):
    columns = ", ".join((*FEATURES, "label", "baseline", "split", "item_code", "cutoff"))
    rows = con.execute(f"SELECT {columns} FROM supervised_snapshots ORDER BY cutoff, restaurant_code, item_code").fetchall()
    values = np.asarray([row[:len(FEATURES)] for row in rows], dtype=object)
    labels = np.asarray([row[len(FEATURES)] for row in rows], dtype=float)
    baseline = np.asarray([row[len(FEATURES) + 1] for row in rows], dtype=float)
    splits = np.asarray([row[len(FEATURES) + 2] for row in rows])
    train, validation, test = (splits == name for name in ("train", "validation", "test"))
    preprocess = ColumnTransformer([
        ("numeric", StandardScaler(), list(range(len(NUMERIC)))),
        ("categorical", OneHotEncoder(handle_unknown="ignore"),
         [len(NUMERIC), len(NUMERIC) + 1]),
    ])
    candidates = {
        "ridge": Ridge(alpha=10.0, solver="lsqr"),
        "extra_trees": ExtraTreesRegressor(n_estimators=32, max_depth=8,
                                           min_samples_leaf=10, random_state=42, n_jobs=4),
    }
    validation_scores = {}
    fitted = {}
    for name, estimator in candidates.items():
        pipeline = Pipeline([("preprocess", clone(preprocess)), ("regressor", estimator)])
        pipeline.fit(values[train], labels[train])
        prediction = np.maximum(0, pipeline.predict(values[validation]))
        validation_scores[name] = metrics(labels[validation], prediction)
        fitted[name] = pipeline
    winner = min(validation_scores, key=lambda name:
                 (validation_scores[name]["mae"], validation_scores[name]["rmse"]))
    model = fitted[winner]
    test_prediction = np.maximum(0, model.predict(values[test]))
    report = {"selected_model": winner, "validation_models": validation_scores,
              "validation_baseline": metrics(labels[validation], baseline[validation]),
              "test_model": metrics(labels[test], test_prediction),
              "test_baseline": metrics(labels[test], baseline[test])}
    test_rows = [row for row, selected in zip(rows, test) if selected]
    keys = {(row[len(NUMERIC)], row[len(FEATURES) + 3], row[len(FEATURES) + 4])
            for row in test_rows}
    require(len(keys) == len(test_rows), "Duplicate held-out prediction keys")
    return model, report, test_rows, test_prediction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", required=True, type=Path)
    parser.add_argument("--quality-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reports", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    args = parser.parse_args()
    quality = validate_paths(args.clean, args.quality_report, args.output, args.reports, args.model)
    con = duckdb.connect()
    con.execute("SET threads=4")
    source_counts = register_sources(con, args.clean, quality)
    checks = build_snapshots(con)
    model, training, test_rows, predictions = train_models(con)
    for folder in (args.output, args.reports, args.model):
        folder.mkdir(parents=True)
    snapshot_file = args.output / "supervised_snapshots.parquet"
    con.execute(f"COPY supervised_snapshots TO '{sql_path(snapshot_file)}' (FORMAT PARQUET)")
    model_file = args.model / "python_demand.joblib"
    joblib.dump(model, model_file)
    reloaded = joblib.load(model_file)
    sample = np.asarray([test_rows[0][:len(FEATURES)]], dtype=object)
    require(np.allclose(reloaded.predict(sample), model.predict(sample)), "Model reload mismatch")
    csv_file = args.reports / "python_predictions.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("restaurant_code", "item_code", "cutoff", "label", "prediction", "baseline", "model"))
        for row, prediction in zip(test_rows, predictions):
            writer.writerow((row[len(NUMERIC)], row[len(FEATURES) + 3],
                             row[len(FEATURES) + 4].isoformat(), row[len(FEATURES)],
                             float(prediction), row[len(FEATURES) + 1], training["selected_model"]))
    report = {"status": "passed", "source": str(args.clean.resolve()),
              "source_quality_report": str(args.quality_report.resolve()),
              "source_counts": source_counts, "checks": checks,
              "cutoffs": [d.isoformat() for d in cutoffs()],
              "train_end": TRAIN_END.isoformat(), "validation_end": VALIDATION_END.isoformat(),
              "features": list(FEATURES), "training": training,
              "snapshot_file": str(snapshot_file.resolve()),
              "prediction_file": str(csv_file.resolve()), "model_file": str(model_file.resolve()),
              "independence": "Built from Step 5 accepted clean Parquet only; no Spark integrated or prediction input."}
    report_file = args.reports / "python_demand_report.json"
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_file), "checks": checks, "training": training}, indent=2))


if __name__ == "__main__":
    main()
