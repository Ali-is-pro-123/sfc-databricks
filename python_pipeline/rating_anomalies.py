"""Flag unusual rating patterns with explicit historical baselines."""

import argparse
import json
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


WEEKLY_FLAGS=("sudden_rating_spike","sudden_rating_drop",
              "excessive_identical_ratings","high_short_period_volume")
MONTHLY_FLAGS=("rating_coverage_vs_sales_spike","ratings_up_sales_down")


def validate(con,source):
    event_count=con.execute("SELECT COUNT(*) FROM rating_events").fetchone()[0]
    metric_count=con.execute("SELECT COUNT(*) FROM rating_metrics").fetchone()[0]
    require(event_count==source["outputs"]["rating_events"]["rows"] and
            metric_count==source["outputs"]["rating_metrics"]["rows"],
            "Step 29 source row counts differ")
    weekly_count=con.execute("SELECT COUNT(*) FROM weekly_rating_anomalies").fetchone()[0]
    weekly_sum=con.execute("""SELECT SUM(rating_count) FROM weekly_rating_anomalies
        WHERE grain='item'""").fetchone()[0]
    location_sum=con.execute("""SELECT SUM(rating_count) FROM weekly_rating_anomalies
        WHERE grain='location'""").fetchone()[0]
    require(weekly_sum==location_sum==event_count,
            "Weekly rating counts do not conserve source events")
    duplicate=con.execute("""SELECT COUNT(*) FROM (
        SELECT grain,entity_code,week_start FROM weekly_rating_anomalies
        GROUP BY 1,2,3 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicate==0,"Duplicate weekly anomaly keys")
    monthly=con.execute("""SELECT COUNT(*),SUM(rating_count),SUM(sold_lines)
        FROM monthly_item_rating_sales""").fetchone()
    require(monthly[1]==event_count and
            monthly[2]==source["checks"]["accepted_completed_lines"],
            "Monthly rating/sale counts do not conserve source")
    bad=con.execute("""SELECT COUNT(*) FROM weekly_rating_anomalies WHERE
        rating_count<0 OR identical_score_count>rating_count
        OR (sudden_rating_spike AND sudden_rating_drop)
        OR ((sudden_rating_spike OR sudden_rating_drop OR high_short_period_volume)
             AND prior_weeks<>8)""").fetchone()[0]
    bad_month=con.execute("""SELECT COUNT(*) FROM monthly_item_rating_sales WHERE
        rating_count>sold_lines OR rating_coverage<0 OR rating_coverage>1
        OR ((rating_coverage_vs_sales_spike OR ratings_up_sales_down)
             AND prior_months<>3)""").fetchone()[0]
    require(bad==bad_month==0,"Invalid anomaly evidence")
    weekly_flags={name:con.execute(f"SELECT COUNT(*) FROM weekly_rating_anomalies WHERE {name}").fetchone()[0]
                  for name in WEEKLY_FLAGS}
    monthly_flags={name:con.execute(f"SELECT COUNT(*) FROM monthly_item_rating_sales WHERE {name}").fetchone()[0]
                   for name in MONTHLY_FLAGS}
    return {"rating_events":int(event_count),"weekly_rows":int(weekly_count),
            "monthly_item_rows":int(monthly[0]),
            "weekly_flag_counts":weekly_flags,"monthly_flag_counts":monthly_flags}


def execute(args):
    require(args.rating_report.is_file() and args.events.is_file() and args.metrics.is_file(),
            "Missing Step 29 source")
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve()!=args.reports.resolve(),"Output paths must differ")
    for target in (args.output,args.reports):
        for source in (args.rating_report,args.events,args.metrics):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside source")
    prior=json.loads(args.rating_report.read_text(encoding="utf-8"))
    require(prior["status"]=="passed" and
            Path(prior["outputs"]["rating_events"]["path"]).resolve()==args.events.resolve() and
            Path(prior["outputs"]["rating_metrics"]["path"]).resolve()==args.metrics.resolve(),
            "Step 29 lineage differs")
    con=duckdb.connect()
    con.execute("SET threads=4")
    con.execute(f"CREATE VIEW rating_events AS SELECT * FROM read_parquet('{sql_path(args.events)}')")
    con.execute(f"CREATE VIEW rating_metrics AS SELECT * FROM read_parquet('{sql_path(args.metrics)}')")
    sql_file=Path(__file__).parent/"sql"/"rating_anomalies.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks=validate(con,prior)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs={}
    for name in ("weekly_rating_anomalies","monthly_item_rating_sales"):
        path=args.output/f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        rows=con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0]
        require(rows==con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"Saved {name} count differs")
        outputs[name]={"path":str(path.resolve()),"rows":int(rows)}
    result={"status":"passed","source_rating_report_sha256":digest(args.rating_report),
            "lineage":{"rating_events_sha256":digest(args.events),
                       "rating_metrics_sha256":digest(args.metrics),
                       "analysis_sql_sha256":digest(sql_file)},
            "checks":checks,"outputs":outputs,
            "thresholds":{"weekly_prior_calendar_weeks":8,
                          "weekly_mean_shift_points":1.0,
                          "identical_share_at_least":0.90,
                          "identical_minimum_ratings":15,
                          "volume_minimum_ratings":20,
                          "monthly_prior_months":3,
                          "coverage_minimum":0.35,
                          "coverage_multiple_of_prior":2.0},
            "limits":"Flags are review-only statistical/rule signals, not fraud findings. Small groups abstain; rating participation is selective and purchase-month cohorts may contain delayed ratings."}
    report_file=args.reports/"rating_anomalies_report.json"
    report_file.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file.resolve()),"checks":checks},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events",type=Path,required=True)
    parser.add_argument("--metrics",type=Path,required=True)
    parser.add_argument("--rating-report",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__=="__main__":
    main()
