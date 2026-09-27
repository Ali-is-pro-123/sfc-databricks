"""Evaluate held-out monthly forecasts without scoring unknown future months."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from python_pipeline.demand import FEATURES, NUMERIC, TRAIN_END, VALIDATION_END, require
from python_pipeline.forecast import digest, load_sources, training_query


def accuracy(actual, predicted):
    """MAPE excludes zero actuals; WAPE retains them in the error numerator."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    require(actual.ndim == predicted.ndim == 1 and len(actual) == len(predicted) > 0,
            "Accuracy arrays must be nonempty and aligned")
    require(np.isfinite(actual).all() and np.isfinite(predicted).all()
            and (actual >= 0).all() and (predicted >= 0).all(),
            "Accuracy inputs must be finite and nonnegative")
    error = predicted - actual
    positive = actual > 0
    centered = np.square(actual - actual.mean()).sum()
    return {"rows": int(len(actual)), "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.square(error).mean())),
            "mape_percent_nonzero_actual": float(np.mean(np.abs(error[positive] / actual[positive])) * 100) if positive.any() else None,
            "mape_eligible_rows": int(positive.sum()), "zero_actual_rows": int((~positive).sum()),
            "wape": float(np.abs(error).sum() / actual.sum()) if actual.sum() else None,
            "r2": float(1 - np.square(error).sum() / centered) if centered > 0 else None,
            "actual_quantity": float(actual.sum()), "predicted_quantity": float(predicted.sum()),
            "mean_error": float(error.mean())}


def model_pipeline():
    transformer = ColumnTransformer([
        ("numeric", StandardScaler(), list(range(len(NUMERIC)))),
        ("categorical", OneHotEncoder(handle_unknown="ignore"),
         [len(NUMERIC), len(NUMERIC) + 1]),
    ])
    return Pipeline([
        ("preprocess", transformer),
        ("regressor", ExtraTreesRegressor(n_estimators=32, max_depth=8,
                                         min_samples_leaf=10, random_state=42, n_jobs=4)),
    ])


def compare_prior(actual, predicted, prior):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    require(len(actual) == prior["rows"], "Step 20 held-out row count differs")
    error = predicted - actual
    checks = {"mae": np.abs(error).mean(),
              "rmse": np.sqrt(np.square(error).mean()),
              "wape": np.abs(error).sum() / actual.sum() if actual.sum() else None,
              "actual_quantity": actual.sum(), "mean_error": error.mean()}
    for name, value in checks.items():
        require((value is None and prior[name] is None) or
                (value is not None and np.isclose(value, prior[name], rtol=1e-8, atol=1e-7)),
                f"Step 20 held-out {name} differs")


def evaluate_horizon(con, horizon, origin, reported):
    rows = con.execute(training_query(horizon), [origin]).fetchall()
    n = len(FEATURES)
    values = np.asarray([row[:n] for row in rows], dtype=object)
    actual = np.asarray([row[n] for row in rows], dtype=float)
    baseline = np.asarray([row[n + 1] for row in rows], dtype=float)
    months = np.asarray([row[n + 2] for row in rows])
    train = months < TRAIN_END
    validation = (months >= TRAIN_END) & (months < VALIDATION_END)
    test = (months >= VALIDATION_END) & (months < origin)
    require((int(train.sum()), int(validation.sum()), int(test.sum())) ==
            tuple(reported[name] for name in ("training_rows", "validation_rows", "test_rows")),
            "Step 20 split row counts differ")
    model = model_pipeline()
    model.fit(values[train], actual[train])
    validation_model = np.maximum(0, model.predict(values[validation]))
    selected = ("extra_trees" if np.abs(validation_model - actual[validation]).mean()
                < np.abs(baseline[validation] - actual[validation]).mean()
                else "recent_30_day_baseline")
    require(selected == reported["selected_method"], "Step 20 validation selection differs")
    model_prediction = np.maximum(0, model.predict(values[test]))
    baseline_prediction = baseline[test]
    compare_prior(actual[test], model_prediction, reported["heldout_model"])
    compare_prior(actual[test], baseline_prediction, reported["heldout_baseline"])
    chosen = model_prediction if selected == "extra_trees" else baseline_prediction
    compare_prior(actual[test], chosen, reported["heldout_selected"])
    monthly = {}
    for month in sorted(set(months[test])):
        mask = months[test] == month
        monthly[month.isoformat()] = {"selected": accuracy(actual[test][mask], chosen[mask]),
                                      "baseline": accuracy(actual[test][mask], baseline_prediction[mask])}
    overall = accuracy(actual[test], chosen)
    baseline_overall = accuracy(actual[test], baseline_prediction)
    return {"selected_method": selected, "heldout": overall,
            "baseline_heldout": baseline_overall, "by_target_month": monthly,
            "mae_improvement_over_baseline_percent":
                float(100 * (baseline_overall["mae"] - overall["mae"]) / baseline_overall["mae"])
                if baseline_overall["mae"] else None}


def execute(args):
    require(not args.output.exists(), "Refusing to overwrite accuracy output")
    for source in (args.clean, args.quality_report, args.python_report,
                   args.snapshot, args.forecast_report, args.time_report):
        require(not args.output.resolve().is_relative_to(source.resolve()),
                "Accuracy output cannot be inside an input source")
    forecast = json.loads(args.forecast_report.read_text(encoding="utf-8"))
    temporal = json.loads(args.time_report.read_text(encoding="utf-8"))
    require(forecast["status"] == temporal["status"] == "passed"
            and temporal["forecast_report_sha256"] == digest(args.forecast_report),
            "Step 20/21 lineage or status differs")
    require(forecast["lineage"]["quality_report_sha256"] == digest(args.quality_report)
            and forecast["lineage"]["python_report_sha256"] == digest(args.python_report)
            and forecast["lineage"]["python_snapshot_sha256"] == digest(args.snapshot),
            "Source lineage differs")
    origin = date.fromisoformat(forecast["origin"])
    require(origin.isoformat() == temporal["forecast_origin"], "Forecast origins differ")
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts, _ = load_sources(con, args)
    require(counts == forecast["source_counts"], "Accepted source counts differ")
    results = {}
    for key, detail in forecast["horizon_models"].items():
        require(key in temporal["horizons"], "Step 21 did not audit this horizon")
        results[key] = evaluate_horizon(con, int(key), origin, detail)
    require(results, "No forecast horizons to evaluate")
    evaluated_months = sorted({month for value in results.values()
                               for month in value["by_target_month"]})
    result = {"status": "passed", "forecast_origin": origin.isoformat(),
              "evaluated_target_months": evaluated_months,
              "forecast_report_sha256": digest(args.forecast_report),
              "time_validation_report_sha256": digest(args.time_report),
              "horizons": results,
              "interpretation": "MAPE excludes zero-actual rows; R2 is undefined for constant actuals. Held-out errors do not measure unobserved July-September forecasts.",
              "publication_status": "review_only_not_inventory_or_staffing_approved"}
    args.output.mkdir(parents=True)
    path = args.output / "forecast_accuracy_report.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path.resolve()), "status": result["status"],
                      "horizons": {key: {"heldout": value["heldout"],
                                         "mae_improvement_over_baseline_percent": value["mae_improvement_over_baseline_percent"]}
                                   for key, value in results.items()}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--python-report", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--forecast-report", type=Path, required=True)
    parser.add_argument("--time-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
