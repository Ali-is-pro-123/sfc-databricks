"""Forecast accepted menu demand for configurable future calendar months."""

import argparse
import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path

import duckdb
import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from python_pipeline.demand import (FEATURES, NUMERIC, TRAIN_END,
                                    VALIDATION_END, metrics, register_sources,
                                    require, sql_path)


def add_months(day, months):
    require(day.day == 1, "Month must begin on day one")
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def months_between(start, end):
    require(start.day == end.day == 1, "Month bounds must start on day one")
    return (end.year-start.year)*12 + end.month-start.month


def month_days(day):
    return (add_months(day, 1)-day).days


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def training_query(horizon):
    require(1 <= horizon <= 3, "Only direct horizons 1–3 are supported")
    columns = ", ".join(f"a.{name}" for name in FEATURES)
    return f"""SELECT {columns}, b.label AS target,
        a.quantity_last_30 * date_diff('day', b.cutoff, b.cutoff+INTERVAL 1 MONTH)/30.0
            AS baseline, b.cutoff AS target_month
        FROM historic_snapshots a JOIN historic_snapshots b
          ON a.restaurant_code=b.restaurant_code AND a.item_code=b.item_code
         AND b.cutoff=a.cutoff+({horizon-1} * INTERVAL 1 MONTH)
        WHERE b.cutoff < ? ORDER BY b.cutoff,a.restaurant_code,a.item_code"""


def load_sources(con, args):
    require(args.quality_report.is_file() and args.python_report.is_file()
            and args.snapshot.is_file(), "Missing passed source report or snapshot")
    quality = json.loads(args.quality_report.read_text(encoding="utf-8"))
    python_report = json.loads(args.python_report.read_text(encoding="utf-8"))
    require(quality.get("status") == python_report.get("status") == "passed",
            "Source report did not pass")
    require(Path(python_report["source"]).resolve() == args.clean.resolve()
            and Path(python_report["source_quality_report"]).resolve() == args.quality_report.resolve()
            and Path(python_report["snapshot_file"]).resolve() == args.snapshot.resolve(),
            "Step 13 lineage does not identify these sources")
    source_counts = register_sources(con, args.clean, quality)
    require(source_counts == python_report["source_counts"],
            "Step 13 accepted source counts differ")
    con.execute(f"CREATE VIEW historic_snapshots AS SELECT * FROM read_parquet('{sql_path(args.snapshot)}')")
    count = con.execute("SELECT COUNT(*) FROM historic_snapshots").fetchone()[0]
    require(count == python_report["checks"]["snapshot_rows"],
            "Step 13 snapshot row count differs")
    duplicates = con.execute("""SELECT COUNT(*) FROM (
        SELECT restaurant_code,item_code,cutoff FROM historic_snapshots
        GROUP BY 1,2,3 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicates == 0, "Duplicate historic snapshot keys")
    return source_counts, python_report


def make_origin(con, origin):
    con.execute((Path(__file__).parent/"sql"/"clean_daily.sql").read_text(encoding="utf-8"))
    latest = con.execute("SELECT MAX(local_date) FROM sale_days").fetchone()[0]
    require(latest is not None, "No accepted sale history")
    expected_origin = add_months(date(latest.year,latest.month,1),1)
    require(origin == expected_origin,
            f"Forecast origin must follow the latest observed month: {expected_origin}")
    con.execute("CREATE TEMP TABLE cutoffs(cutoff DATE)")
    con.execute("INSERT INTO cutoffs VALUES (?)", [add_months(origin,-1)])
    sql = (Path(__file__).parent/"sql"/"snapshots.sql").read_text(encoding="utf-8")
    con.execute(sql,[TRAIN_END,VALIDATION_END])
    historic_month = add_months(origin,-1)
    comparisons = ["s.category_code IS DISTINCT FROM h.category_code",
                   "s.label IS DISTINCT FROM h.label"]
    comparisons += [f"ABS(s.{field}-h.{field})>0.000001" for field in NUMERIC]
    comparison = " OR ".join(comparisons)
    parity = con.execute(f"""SELECT COUNT(*) AS total,
        SUM(CASE WHEN h.restaurant_code IS NULL OR ({comparison}) THEN 1 ELSE 0 END) AS bad
        FROM supervised_snapshots s LEFT JOIN historic_snapshots h
          ON s.restaurant_code=h.restaurant_code AND s.item_code=h.item_code
         AND s.cutoff=h.cutoff""").fetchone()
    historic_count = con.execute("SELECT COUNT(*) FROM historic_snapshots WHERE cutoff=?",[historic_month]).fetchone()[0]
    require(parity[0] == historic_count and parity[1] == 0,
            "Rebuilt prior-month features/labels differ from Step 13")
    con.execute("DELETE FROM cutoffs")
    con.execute("INSERT INTO cutoffs VALUES (?)",[origin])
    con.execute(sql,[TRAIN_END,VALIDATION_END])
    require(con.execute("SELECT COUNT(*) FROM supervised_snapshots WHERE label<>0 OR cutoff<>?",[origin]).fetchone()[0] == 0,
            "Inference snapshot contains observed future target or wrong cutoff")
    known = con.execute("SELECT COUNT(*) FROM supervised_snapshots").fetchone()[0]
    require(known > 0, "No known item/location pairs at origin")
    duplicates = con.execute("""SELECT COUNT(*) FROM (
        SELECT restaurant_code,item_code FROM supervised_snapshots
        GROUP BY 1,2 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicates == 0, "Duplicate inference pair keys")
    available_pairs = con.execute("""SELECT COUNT(*) FROM clean_restaurants r
        CROSS JOIN clean_menu_items i WHERE r.is_active AND i.is_available""").fetchone()[0]
    require(known <= available_pairs, "Known pairs exceed available catalog")
    return {"latest_sale_date":latest.isoformat(), "prior_month_parity_rows":parity[0],
            "known_pairs":known, "catalog_pairs":available_pairs,
            "unmodeled_cold_start_pairs":available_pairs-known}


def fit_horizon(con,horizon,origin,model_dir):
    rows = con.execute(training_query(horizon),[origin]).fetchall()
    n = len(FEATURES)
    values = np.asarray([row[:n] for row in rows],dtype=object)
    target = np.asarray([row[n] for row in rows],dtype=float)
    baseline = np.asarray([row[n+1] for row in rows],dtype=float)
    months = [row[n+2] for row in rows]
    train = np.asarray([month<TRAIN_END for month in months])
    validation = np.asarray([TRAIN_END<=month<VALIDATION_END for month in months])
    test = np.asarray([VALIDATION_END<=month<origin for month in months])
    require(all(mask.sum()>0 for mask in (train,validation,test)),
            f"Empty chronological partition for horizon {horizon}")
    transformer = ColumnTransformer([
        ("numeric",StandardScaler(),list(range(len(NUMERIC)))),
        ("categorical",OneHotEncoder(handle_unknown="ignore"),
         [len(NUMERIC),len(NUMERIC)+1]),
    ])
    model = Pipeline([
        ("preprocess",transformer),
        ("regressor",ExtraTreesRegressor(n_estimators=32,max_depth=8,
                                         min_samples_leaf=10,random_state=42,n_jobs=4)),
    ])
    model.fit(values[train],target[train])
    validation_model = metrics(target[validation],np.maximum(0,model.predict(values[validation])))
    validation_baseline = metrics(target[validation],baseline[validation])
    selected = "extra_trees" if validation_model["mae"] < validation_baseline["mae"] else "recent_30_day_baseline"
    # The test is inspected only after the validation-only method choice.
    test_model = metrics(target[test],np.maximum(0,model.predict(values[test])))
    test_baseline = metrics(target[test],baseline[test])
    model_path = None
    if selected == "extra_trees":
        model.fit(values,target)
        model_path = model_dir/f"horizon_{horizon}.joblib"
        joblib.dump(model,model_path)
        loaded = joblib.load(model_path)
        require(np.allclose(loaded.predict(values[:1]),model.predict(values[:1])),
                "Operational refit model reload differs")
    return model if selected=="extra_trees" else None, {
        "horizon_months":horizon,"training_rows":int(train.sum()),
        "validation_rows":int(validation.sum()),"test_rows":int(test.sum()),
        "target_month_train_end_exclusive":TRAIN_END.isoformat(),
        "target_month_validation_end_exclusive":VALIDATION_END.isoformat(),
        "validation_model":validation_model,"validation_baseline":validation_baseline,
        "selected_method":selected,"heldout_model":test_model,
        "heldout_baseline":test_baseline,
        "heldout_selected":test_model if selected=="extra_trees" else test_baseline,
        "operational_refit_rows":len(rows) if selected=="extra_trees" else 0,
        "operational_model":str(model_path.resolve()) if model_path else None,
    }


def write_forecasts(con,methods,origin,target_months,output):
    columns = ", ".join((*FEATURES,"item_code"))
    rows = con.execute(f"SELECT {columns} FROM supervised_snapshots ORDER BY restaurant_code,item_code").fetchall()
    n = len(FEATURES)
    features = np.asarray([row[:n] for row in rows],dtype=object)
    values = []
    for target_month in target_months:
        horizon = months_between(origin,target_month)+1
        model, report = methods[horizon]
        baseline = np.asarray([float(row[0])*month_days(target_month)/30 for row in rows])
        prediction = (np.maximum(0,model.predict(features)) if model is not None else baseline)
        require(len(prediction)==len(rows) and np.isfinite(prediction).all()
                and (prediction>=0).all(),"Invalid future forecast values")
        values.extend((row[len(NUMERIC)],row[n],row[len(NUMERIC)+1],
                       target_month.isoformat(),horizon,float(pred),float(base),
                       report["selected_method"])
                      for row,pred,base in zip(rows,prediction,baseline))
    csv_file = output/"item_location_forecast.csv"
    with csv_file.open("w",newline="",encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("restaurant_code","item_code","category_code","target_month",
                         "horizon_months","forecast_quantity","baseline_quantity","method"))
        writer.writerows(values)
    return csv_file,len(values)


def save_rollups(con,csv_file,output,expected_rows,target_months):
    con.execute(f"""CREATE VIEW forecast_base AS SELECT restaurant_code,item_code,category_code,
        CAST(target_month AS DATE) AS target_month,
        CAST(horizon_months AS INTEGER) AS horizon_months,
        CAST(forecast_quantity AS DOUBLE) AS forecast_quantity,
        CAST(baseline_quantity AS DOUBLE) AS baseline_quantity,method
        FROM read_csv_auto('{sql_path(csv_file)}',header=true,all_varchar=true)""")
    require(con.execute("SELECT COUNT(*) FROM forecast_base").fetchone()[0]==expected_rows,
            "Forecast CSV read-back count differs")
    duplicates = con.execute("""SELECT COUNT(*) FROM (SELECT restaurant_code,item_code,
        target_month FROM forecast_base GROUP BY 1,2,3 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicates==0,"Duplicate item/location/month forecast keys")
    output_specs = {
        "item_location_forecast":"SELECT * FROM forecast_base",
        "item_forecast":"SELECT target_month,item_code,category_code,SUM(forecast_quantity) AS forecast_quantity FROM forecast_base GROUP BY 1,2,3",
        "category_forecast":"SELECT target_month,category_code,SUM(forecast_quantity) AS forecast_quantity FROM forecast_base GROUP BY 1,2",
        "category_location_forecast":"SELECT target_month,restaurant_code,category_code,SUM(forecast_quantity) AS forecast_quantity FROM forecast_base GROUP BY 1,2,3",
        "location_forecast":"SELECT target_month,restaurant_code,SUM(forecast_quantity) AS forecast_quantity FROM forecast_base GROUP BY 1,2",
    }
    paths = {}
    totals = {}
    for name,query in output_specs.items():
        path = output/f"{name}.parquet"
        con.execute(f"COPY ({query}) TO '{sql_path(path)}' (FORMAT PARQUET)")
        paths[name] = str(path.resolve())
        totals[name] = {day.isoformat():float(amount) for day,amount in con.execute(
            f"SELECT target_month,SUM(forecast_quantity) FROM ({query}) GROUP BY 1 ORDER BY 1").fetchall()}
    for month in target_months:
        day = month.isoformat()
        amounts = [value[day] for value in totals.values()]
        require(max(amounts)-min(amounts)<0.0001,
                f"Forecast rollups do not conserve quantity for {day}")
    return paths,totals


def execute(args):
    require(1<=args.months<=3,"Forecast range must be 1–3 months")
    for target in (args.output,args.reports,args.models):
        require(not target.exists(),f"Refusing to overwrite: {target}")
        for source in (args.clean,args.quality_report,args.python_report,args.snapshot):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside an input source")
    require(len({args.output.resolve(),args.reports.resolve(),args.models.resolve()})==3,
            "Output/report/model paths must differ")
    con = duckdb.connect()
    con.execute("SET threads=4")
    source_counts,python_report = load_sources(con,args)
    latest = con.execute("""SELECT MAX(CAST(timezone(r.timezone,
        timezone('UTC',o.ordered_at)) AS DATE))
        FROM clean_orders o JOIN clean_restaurants r ON o.restaurant_code=r.code
        WHERE o.status='completed'""").fetchone()[0]
    origin = add_months(date(latest.year,latest.month,1),1)
    start = args.start_month or origin
    offset = months_between(origin,start)
    require(offset>=0 and offset+args.months<=3,
            "Selected months must be within the next three complete calendar months")
    target_months = [add_months(start,i) for i in range(args.months)]
    origin_check = make_origin(con,origin)
    for directory in (args.output,args.reports,args.models):
        directory.mkdir(parents=True)
    methods = {}
    for horizon in range(offset+1,offset+args.months+1):
        methods[horizon] = fit_horizon(con,horizon,origin,args.models)
    csv_file,rows = write_forecasts(con,methods,origin,target_months,args.output)
    require(rows==origin_check["known_pairs"]*args.months,
            "Forecast population differs from known pairs times months")
    paths,totals = save_rollups(con,csv_file,args.output,rows,target_months)
    report = {"status":"passed","origin":origin.isoformat(),
              "forecast_months":[month.isoformat() for month in target_months],
              "months_requested":args.months,"source_counts":source_counts,
              "origin_checks":origin_check,"horizon_models":{str(h):detail for h,(_,detail) in methods.items()},
              "forecast_rows":rows,"output_files":paths,
              "forecast_csv":str(csv_file.resolve()),"rollup_totals":totals,
              "lineage":{"quality_report_sha256":digest(args.quality_report),
                         "python_report_sha256":digest(args.python_report),
                         "python_snapshot_sha256":digest(args.snapshot)},
              "publication_status":"review_only_not_inventory_or_staffing_approved"}
    report_file = args.reports/"forecast_report.json"
    report_file.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file),"origin_checks":origin_check,
                      "forecast_months":report["forecast_months"],
                      "forecast_rows":rows,
                      "selected_methods":{h:detail["selected_method"] for h,(_,detail) in methods.items()},
                      "item_location_totals":totals["item_location_forecast"]},indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean",type=Path,required=True)
    parser.add_argument("--quality-report",type=Path,required=True)
    parser.add_argument("--python-report",type=Path,required=True)
    parser.add_argument("--snapshot",type=Path,required=True)
    parser.add_argument("--start-month",type=date.fromisoformat)
    parser.add_argument("--months",type=int,default=3)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    parser.add_argument("--models",type=Path,required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
