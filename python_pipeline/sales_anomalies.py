"""Audit sales, demand, order value, discount and duplicate signals."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


TABLES=("orders","order_items","restaurants","menu_items","menu_categories")


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


def validate(con,as_of):
    direct=con.execute("""SELECT COUNT(*),SUM(i.quantity),
        SUM(i.quantity*i.unit_price-i.discount_amount),SUM(i.discount_amount)
        FROM clean_order_items i JOIN clean_orders o ON o.code=i.order_code
        WHERE o.status='completed' AND o.ordered_at<?""",[as_of]).fetchone()
    orders=con.execute("""SELECT COUNT(*),SUM(accepted_lines),SUM(sold_quantity),
        SUM(net_revenue),SUM(discount_amount) FROM order_facts""").fetchone()
    require(orders[1]==direct[0] and all(abs(float(a)-float(b))<0.01
            for a,b in zip(orders[2:5],direct[1:4])),
            "Accepted completed sale totals do not reconcile")
    duplicate_keys=con.execute("""SELECT COUNT(*) FROM (
        SELECT order_code FROM order_facts GROUP BY 1 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicate_keys==0,"Duplicate accepted order keys")
    daily=con.execute("""SELECT COUNT(*),SUM(orders),SUM(net_revenue)
        FROM location_day_anomalies""").fetchone()
    require(daily[1]==orders[0] and abs(float(daily[2])-float(orders[3]))<0.01,
            "Dense location days do not conserve orders/revenue")
    weekly=con.execute("""SELECT COUNT(*),SUM(sold_quantity)
        FROM category_week_demand""").fetchone()
    full_week_sale=con.execute("""SELECT SUM(i.quantity) FROM order_facts o
        JOIN clean_order_items i ON i.order_code=o.order_code
        CROSS JOIN analysis_parameters p
        WHERE date_trunc('week',o.local_date)+INTERVAL 7 DAY<=p.as_of""").fetchone()[0]
    require(abs(float(weekly[1])-float(full_week_sale))<0.01,
            "Complete category weeks do not conserve sold quantity")
    bad=con.execute("""SELECT COUNT(*) FROM location_day_anomalies WHERE
        orders<0 OR (sudden_sales_spike AND sudden_sales_drop) OR
        ((sudden_sales_spike OR sudden_sales_drop) AND prior_same_weekdays<>8)""").fetchone()[0]
    bad_week=con.execute("""SELECT COUNT(*) FROM category_week_demand WHERE
        sold_quantity<0 OR (unexpected_high_demand AND unexpected_low_demand)
        OR ((unexpected_high_demand OR unexpected_low_demand) AND prior_weeks<>8)""").fetchone()[0]
    require(bad==bad_week==0,"Invalid baseline-based sales flags")
    dup=con.execute("""SELECT COUNT(*),SUM(matching_orders) FROM
        duplicate_transaction_candidates""").fetchone()
    require(dup[0]==0 or dup[1]>=2*dup[0],"Invalid duplicate candidate group")
    flags={}
    for table,names in (("location_day_anomalies",("sudden_sales_spike","sudden_sales_drop")),
                        ("category_week_demand",("unexpected_high_demand","unexpected_low_demand")),
                        ("order_value_anomalies",("abnormally_high_order_value","unusual_discount"))):
        flags.update({name:con.execute(f"SELECT COUNT(*) FROM {table} WHERE {name}").fetchone()[0]
                      for name in names})
    return {"accepted_completed_orders":int(orders[0]),
            "accepted_completed_lines":int(direct[0]),
            "sold_quantity":float(orders[2]),"net_revenue":float(orders[3]),
            "discount_amount":float(orders[4]),
            "location_day_rows":int(daily[0]),"category_week_rows":int(weekly[0]),
            "monitored_order_rows":con.execute("SELECT COUNT(*) FROM order_value_anomalies").fetchone()[0],
            "flag_counts":flags,
            "duplicate_candidate_groups":int(dup[0]),
            "orders_in_duplicate_candidate_groups":int(dup[1] or 0)}


def execute(args):
    require(args.clean.is_dir() and args.quality_report.is_file(),"Missing accepted source")
    require(args.monitor_start<args.as_of,"Monitor start must precede as-of")
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve()!=args.reports.resolve(),"Output paths must differ")
    for target in (args.output,args.reports):
        for source in (args.clean,args.quality_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside source")
    quality=json.loads(args.quality_report.read_text(encoding="utf-8"))
    con=duckdb.connect()
    con.execute("SET threads=4")
    counts=load_sources(con,args.clean,quality)
    con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT ?::TIMESTAMP AS as_of,?::DATE AS monitor_start",
                [args.as_of,args.monitor_start])
    sql_file=Path(__file__).parent/"sql"/"sales_anomalies.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks=validate(con,args.as_of)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs={}
    for name in ("location_day_anomalies","category_week_demand",
                 "order_value_anomalies","duplicate_transaction_candidates"):
        path=args.output/f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        rows=con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0]
        require(rows==con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"Saved {name} count differs")
        outputs[name]={"path":str(path.resolve()),"rows":int(rows)}
    result={"status":"passed","as_of_exclusive":args.as_of.isoformat(),
            "monitor_start":args.monitor_start.isoformat(),
            "source_counts":counts,"checks":checks,"outputs":outputs,
            "lineage":{"quality_report_sha256":digest(args.quality_report),
                       "analysis_sql_sha256":digest(sql_file)},
            "interpretation":"Location-day sales compare with eight prior same weekdays; location/category-week demand compares with eight prior complete weeks. Order value and discount compare monitored orders with earlier same-location orders. Exact matching baskets are duplicate candidates, not proven duplicate charges.",
            "limits":"These review-only flags are not fraud findings or forecast residuals. Seasonal shifts, promotions, synthetic spikes and incomplete accepted baskets after quarantine may explain anomalies. The last partial calendar week is excluded from weekly demand checks."}
    report_file=args.reports/"sales_anomalies_report.json"
    report_file.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file.resolve()),"checks":checks},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean",type=Path,required=True)
    parser.add_argument("--quality-report",type=Path,required=True)
    parser.add_argument("--as-of",type=date.fromisoformat,required=True)
    parser.add_argument("--monitor-start",type=date.fromisoformat,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__=="__main__":
    main()
