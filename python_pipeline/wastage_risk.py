"""Predict next-month wastage-event risk from prior-month observations."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb
import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


NUMERIC = ("prior_3m_sold", "prior_3m_wasted", "prior_3m_promoted_sold",
           "prior_3m_recorded_prepared", "prior_3m_waste_months",
           "prior_3m_high_waste_months",
           "prior_month_sold", "prior_month_wasted", "month_sin", "month_cos")
FEATURES = (*NUMERIC, "restaurant_code", "category_code")
TRAIN_END, VALIDATION_END, ORIGIN = date(2026, 1, 1), date(2026, 3, 1), date(2026, 7, 1)


def score(actual, probability):
    actual = np.asarray(actual, dtype=int)
    probability = np.asarray(probability, dtype=float)
    require(len(actual) == len(probability) > 0 and np.isin(actual, [0, 1]).all()
            and np.isfinite(probability).all() and ((0 <= probability) & (probability <= 1)).all(),
            "Invalid risk scores")
    order = np.argsort(-probability, kind="stable")
    top = max(1, int(np.ceil(len(actual) * 0.10)))
    return {"rows": int(len(actual)), "positive_rows": int(actual.sum()),
            "prevalence": float(actual.mean()),
            "average_precision": float(average_precision_score(actual, probability)) if actual.any() else None,
            "roc_auc": float(roc_auc_score(actual, probability)) if len(np.unique(actual)) == 2 else None,
            "brier": float(brier_score_loss(actual, probability)),
            "top_decile_rows": top, "top_decile_precision": float(actual[order[:top]].mean()),
            "top_decile_recall": float(actual[order[:top]].sum() / actual.sum()) if actual.any() else None}


def pipeline():
    return Pipeline([
        ("preprocess", ColumnTransformer([
            ("numeric", "passthrough", list(range(len(NUMERIC)))),
            ("categorical", OneHotEncoder(handle_unknown="ignore"),
             [len(NUMERIC), len(NUMERIC) + 1]),
        ])),
        ("classifier", ExtraTreesClassifier(n_estimators=64, max_depth=10,
                                             min_samples_leaf=20, random_state=42,
                                             n_jobs=4)),
    ])


def execute(args):
    require(args.daily.is_file() and args.wastage_report.is_file(), "Missing Step 23 source")
    for target in (args.output, args.reports, args.models):
        require(not target.exists(), f"Refusing to overwrite: {target}")
        for source in (args.daily, args.wastage_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside source")
    require(len({args.output.resolve(), args.reports.resolve(), args.models.resolve()}) == 3,
            "Output paths must differ")
    prior = json.loads(args.wastage_report.read_text(encoding="utf-8"))
    require(prior["status"] == "passed" and
            Path(prior["outputs"]["wastage_daily"]["path"]).resolve() == args.daily.resolve(),
            "Step 23 lineage differs")
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(f"CREATE VIEW wastage_daily AS SELECT * FROM read_parquet('{sql_path(args.daily)}')")
    require(con.execute("SELECT COUNT(*) FROM wastage_daily").fetchone()[0] ==
            prior["outputs"]["wastage_daily"]["rows"], "Step 23 daily row count differs")
    sql_file = Path(__file__).parent / "sql" / "wastage_risk.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    bad = con.execute("""SELECT COUNT(*) FROM monthly_risk WHERE
        history_months<>3 OR prior_3m_sold<0 OR prior_3m_wasted<0
        OR prior_3m_recorded_prepared<0 OR
        (month_start=? AND waste_event IS NOT NULL) OR
        (month_start<? AND waste_event IS NULL)""", [ORIGIN, ORIGIN]).fetchone()[0]
    require(bad == 0, "Risk feature chronology or values invalid")
    duplicate = con.execute("""SELECT COUNT(*) FROM (
        SELECT restaurant_code,item_code,month_start FROM monthly_risk
        GROUP BY 1,2,3 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicate == 0, "Duplicate monthly risk keys")
    columns = ",".join((*FEATURES, "item_code", "month_start", "waste_event"))
    rows = con.execute(f"SELECT {columns} FROM monthly_risk ORDER BY month_start,restaurant_code,item_code").fetchall()
    n = len(FEATURES)
    values = np.asarray([row[:n] for row in rows], dtype=object)
    months = np.asarray([row[n + 1] for row in rows])
    observed = months < ORIGIN
    y = np.asarray([int(row[n + 2]) for row in rows if row[n + 1] < ORIGIN])
    train = months[observed] < TRAIN_END
    validation = (months[observed] >= TRAIN_END) & (months[observed] < VALIDATION_END)
    test = (months[observed] >= VALIDATION_END) & (months[observed] < ORIGIN)
    require(all(mask.sum() > 0 for mask in (train, validation, test)) and
            len(np.unique(y[train])) == 2, "Empty or single-class chronological split")
    baseline = np.asarray([float(row[NUMERIC.index("prior_3m_high_waste_months")]) / 3
                           for row in rows if row[n + 1] < ORIGIN])
    model = pipeline()
    model.fit(values[observed][train], y[train])
    val_model = model.predict_proba(values[observed][validation])[:, 1]
    val_base = baseline[validation]
    selected = ("extra_trees" if score(y[validation], val_model)["average_precision"] >
                score(y[validation], val_base)["average_precision"] else "prior_3m_frequency")
    test_model = model.predict_proba(values[observed][test])[:, 1]
    test_base = baseline[test]
    selected_test = test_model if selected == "extra_trees" else test_base
    heldout = {"selected": score(y[test], selected_test),
               "model": score(y[test], test_model), "baseline": score(y[test], test_base)}
    monthly = {month.isoformat(): score(y[test][months[observed][test] == month],
                                        selected_test[months[observed][test] == month])
               for month in sorted(set(months[observed][test]))}
    future = months == ORIGIN
    require(future.sum() > 0, "Missing next-month item/location pairs")
    catalog_pairs = con.execute("""SELECT COUNT(*) FROM (
        SELECT DISTINCT restaurant_code,item_code FROM wastage_daily)""").fetchone()[0]
    require(future.sum() <= catalog_pairs, "Future risk population exceeds observed pairs")
    model_path = None
    if selected == "extra_trees":
        model.fit(values[observed], y)
        args.models.mkdir(parents=True)
        model_path = args.models / "wastage_risk.joblib"
        joblib.dump(model, model_path)
        loaded = joblib.load(model_path)
        require(np.allclose(loaded.predict_proba(values[future][:1]),
                            model.predict_proba(values[future][:1])), "Risk model reload differs")
        probabilities = model.predict_proba(values[future])[:, 1]
    else:
        args.models.mkdir(parents=True)
        probabilities = np.asarray([float(row[NUMERIC.index("prior_3m_high_waste_months")]) / 3
                                    for row, active in zip(rows, future) if active])
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    con.execute("CREATE TEMP TABLE future_risk(restaurant_code VARCHAR,item_code VARCHAR,category_code VARCHAR,month_start DATE,risk_probability DOUBLE,method VARCHAR)")
    future_rows = [row for row, active in zip(rows, future) if active]
    con.executemany("INSERT INTO future_risk VALUES (?,?,?,?,?,?)",
                    [(row[len(NUMERIC)], row[n], row[len(NUMERIC) + 1],
                      row[n + 1], float(probability), selected)
                     for row, probability in zip(future_rows, probabilities)])
    output_file = args.output / "next_month_wastage_risk.parquet"
    con.execute(f"COPY (SELECT * FROM future_risk ORDER BY risk_probability DESC,restaurant_code,item_code) TO '{sql_path(output_file)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(output_file)]).fetchone()[0] == future.sum(),
            "Risk output read-back differs")
    invalid_future = con.execute("""SELECT COUNT(*) FROM future_risk WHERE
        risk_probability IS NULL OR risk_probability<0 OR risk_probability>1
        OR month_start<>?""", [ORIGIN]).fetchone()[0]
    require(invalid_future == 0, "Invalid future risk probability or month")
    report = {"status": "passed", "target_month": ORIGIN.isoformat(),
              "training_rows": int(train.sum()), "validation_rows": int(validation.sum()),
              "test_rows": int(test.sum()), "future_rows": int(future.sum()),
              "unscored_insufficient_history_pairs": int(catalog_pairs - future.sum()),
              "selected_method": selected, "heldout": heldout, "heldout_by_month": monthly,
              "future_output": str(output_file.resolve()),
              "operational_model": str(model_path.resolve()) if model_path else None,
              "lineage": {"step23_report_sha256": digest(args.wastage_report),
                          "step23_daily_sha256": digest(args.daily),
                          "feature_sql_sha256": digest(sql_file)},
              "publication_status": "review_only_not_inventory_or_preparation_approved",
              "target_definition": "At least five accepted wasted portions in the next item/location/month",
              "quality_warning": "Held-out ROC-AUC is only modestly above chance; risk ranking is exploratory, not operationally reliable.",
              "limits": "Predicts a recorded high-waste month, not exact wasted quantity. Synthetic source and Step 23 inventory gap remain; no future preparation or promotion plan is assumed."}
    report_file = args.reports / "wastage_risk_report.json"
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_file.resolve()), "selected_method": selected,
                      "heldout": heldout["selected"], "future_rows": int(future.sum())}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", type=Path, required=True)
    parser.add_argument("--wastage-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
