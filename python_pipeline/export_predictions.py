"""Re-export held-out predictions from a trusted local Step 13 snapshot/model."""

import argparse
import csv
from pathlib import Path

import duckdb
import joblib
import numpy as np

from python_pipeline.demand import FEATURES, NUMERIC, require


def export(snapshot, model_path, output):
    con = duckdb.connect()
    columns = ", ".join((*FEATURES, "label", "baseline", "item_code", "cutoff"))
    rows = con.execute(f"SELECT {columns} FROM read_parquet(?) WHERE split='test' "
                       "ORDER BY cutoff, restaurant_code, item_code", [str(snapshot)]).fetchall()
    require(rows, "No held-out rows in snapshot")
    keys = {(row[len(NUMERIC)], row[len(FEATURES) + 2], row[len(FEATURES) + 3])
            for row in rows}
    require(len(keys) == len(rows), "Duplicate held-out prediction keys")
    model = joblib.load(model_path)
    model_name = {"Ridge": "ridge", "ExtraTreesRegressor": "extra_trees"}.get(
        model.named_steps["regressor"].__class__.__name__)
    require(model_name is not None, "Unrecognized fitted model")
    features = np.asarray([row[:len(FEATURES)] for row in rows], dtype=object)
    predictions = np.maximum(0, model.predict(features))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("restaurant_code", "item_code", "cutoff", "label", "prediction", "baseline", "model"))
        for row, prediction in zip(rows, predictions):
            writer.writerow((row[len(NUMERIC)], row[len(FEATURES) + 2],
                             row[len(FEATURES) + 3].isoformat(), row[len(FEATURES)],
                             float(prediction), row[len(FEATURES) + 1], model_name))
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(export(arguments.snapshot, arguments.model, arguments.output))
