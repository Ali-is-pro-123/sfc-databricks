"""Classify slow-moving dishes from multiple independent 90-day signals."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


TABLES=("orders","order_items","restaurants")
PAIR_CLASSES=("slow_moving","watchlist","not_slow_moving","insufficient_evidence")


def load_sources(con,clean,quality):
    require(quality.get("status")=="passed","Step 5 quality report did not pass")
    counts={}
    for name in TABLES:
        folder=clean/name
        require((folder/"_SUCCESS").is_file() and any(folder.rglob("*.parquet")),
                f"Missing accepted source: {name}")
        con.execute(f"CREATE VIEW clean_{name} AS SELECT * FROM read_parquet('{sql_path(folder)}/**/*.parquet')")
        counts[name]=con.execute(f"SELECT COUNT(*) FROM clean_{name}").fetchone()[0]
        require(counts[name]==quality["tables"][name]["accepted_rows"],
                f"Accepted source count differs: {name}")
    return counts


def validate(con,report):
    expected=report["outputs"]["item_location_performance"]["rows"]
    counts=con.execute("""SELECT COUNT(*),SUM(quantity_sold),SUM(revenue),SUM(cost),
        SUM(order_frequency) FROM performance""").fetchone()
    require(counts[0]==expected,"Step 9 performance population differs")
    mismatches=con.execute("""SELECT COUNT(*) FROM performance p
        LEFT JOIN sale_90 s USING (restaurant_code,item_code)
        WHERE p.quantity_sold<>COALESCE(s.quantity_sold,0)
           OR p.order_frequency<>COALESCE(s.order_frequency,0)
           OR ABS(p.revenue::DOUBLE-COALESCE(s.revenue,0))>0.01
           OR ABS(p.cost::DOUBLE-COALESCE(s.cost,0))>0.01""").fetchone()[0]
    require(mismatches==0,"Step 9 feature rows differ from accepted clean sales")
    pair=con.execute("SELECT COUNT(*) FROM slow_moving_pairs").fetchone()[0]
    items=con.execute("SELECT COUNT(*) FROM slow_moving_items").fetchone()[0]
    require(pair==expected and items==con.execute("SELECT COUNT(DISTINCT item_code) FROM performance").fetchone()[0],
            "Slow-moving population differs")
    dup=con.execute("""SELECT COUNT(*) FROM (
        SELECT restaurant_code,item_code FROM slow_moving_pairs
        GROUP BY 1,2 HAVING COUNT(*)>1)""").fetchone()[0]
    require(dup==0,"Duplicate slow-moving pair keys")
    bad=con.execute("""SELECT COUNT(*) FROM slow_moving_pairs WHERE
        longest_no_sale_gap_days<0 OR days_since_last_sale<0
        OR low_activity_signals<0 OR low_activity_signals>3
        OR adverse_health_signals<0 OR adverse_health_signals>4
        OR movement_class NOT IN (?,?,?,?)
        OR (item_age_days<60 AND movement_class<>'insufficient_evidence')
        OR (movement_class='slow_moving' AND quantity_sold>0
            AND low_activity_signals<2)""",list(PAIR_CLASSES)).fetchone()[0]
    require(bad==0,"Invalid slow-moving evidence or class")
    classes=dict(con.execute("SELECT movement_class,COUNT(*) FROM slow_moving_pairs GROUP BY 1").fetchall())
    item_classes=dict(con.execute("SELECT item_movement_class,COUNT(*) FROM slow_moving_items GROUP BY 1").fetchall())
    return {"pairs":int(pair),"items":int(items),
            "window_quantity":float(counts[1]),"window_revenue":float(counts[2]),
            "window_cost":float(counts[3]),
            "pair_classes":classes,"item_classes":item_classes}


def execute(args):
    require(args.clean.is_dir() and args.quality_report.is_file() and
            args.performance.is_dir() and args.performance_report.is_file(),
            "Missing accepted source or Step 9 report")
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve()!=args.reports.resolve(),"Output paths must differ")
    for target in (args.output,args.reports):
        for source in (args.clean,args.quality_report,args.performance,args.performance_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside source")
    quality=json.loads(args.quality_report.read_text(encoding="utf-8"))
    report=json.loads(args.performance_report.read_text(encoding="utf-8"))
    require(report["status"]=="passed" and
            report["as_of_exclusive_local_date"]==args.as_of.isoformat() and
            report["window_days"]==90,
            "Step 9 report cutoff or status differs")
    require((args.performance/"_SUCCESS").is_file() and
            any(args.performance.rglob("*.parquet")),"Missing Step 9 performance Parquet")
    con=duckdb.connect()
    con.execute("SET threads=4")
    load_sources(con,args.clean,quality)
    con.execute(f"CREATE VIEW performance AS SELECT * FROM read_parquet('{sql_path(args.performance)}/**/*.parquet')")
    con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT ?::DATE AS as_of",[args.as_of])
    sql_file=Path(__file__).parent/"sql"/"slow_moving.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks=validate(con,report)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs={}
    for name in ("slow_moving_pairs","slow_moving_items"):
        path=args.output/f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        rows=con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0]
        require(rows==con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"Saved {name} count differs")
        outputs[name]={"path":str(path.resolve()),"rows":int(rows)}
    result={"status":"passed","as_of_exclusive":args.as_of.isoformat(),
            "window_days":90,"checks":checks,"outputs":outputs,
            "thresholds":{"minimum_item_age_days":60,"minimum_category_peers":8,
                          "low_activity_category_quantile":0.25,
                          "long_no_sale_gap_days":21,
                          "low_repeat_rate_at_most":0.05,
                          "high_accounted_wastage_percentage_at_least":25,
                          "weak_direct_margin_percentage_at_most":20,
                          "poor_quantity_trend_percentage_at_most":-25},
            "lineage":{"quality_report_sha256":digest(args.quality_report),
                       "step09_report_sha256":digest(args.performance_report),
                       "analysis_sql_sha256":digest(sql_file)},
            "limits":"Review-only multi-signal classifications. Relative category quartiles and thresholds are analytic choices, not SRS cutoffs. Repeat purchase and trend may be unobserved; accepted waste/inventory gaps and synthetic June shifts remain. Direct margin excludes overhead."}
    report_file=args.reports/"slow_moving_report.json"
    report_file.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file.resolve()),"checks":checks},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean",type=Path,required=True)
    parser.add_argument("--quality-report",type=Path,required=True)
    parser.add_argument("--performance",type=Path,required=True)
    parser.add_argument("--performance-report",type=Path,required=True)
    parser.add_argument("--as-of",type=date.fromisoformat,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__=="__main__":
    main()
