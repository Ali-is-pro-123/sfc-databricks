"""Analyze observed ratings against accepted sales and later repeat purchase."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


TABLES = ("orders","order_items","restaurants","menu_items","ratings")
GRAINS = ("item","location","item_location","purchase_month",
          "promotion_status","item_location_month_promotion")


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


def validate(con,counts,as_of):
    direct=con.execute("""SELECT COUNT(*),SUM(i.quantity),
        SUM(i.quantity*i.unit_price-i.discount_amount),
        SUM(i.quantity*(i.unit_price-i.unit_cost)-i.discount_amount)
        FROM clean_order_items i JOIN clean_orders o ON o.code=i.order_code
        WHERE o.status='completed' AND o.ordered_at<?""",[as_of]).fetchone()
    sold=con.execute("""SELECT COUNT(*),SUM(sold_quantity),SUM(net_revenue),
        SUM(direct_contribution) FROM sold_lines""").fetchone()
    require(direct[0]==sold[0] and all(abs(float(a)-float(b))<0.01
            for a,b in zip(direct[1:],sold[1:])),
            "Completed sales do not reconcile")
    rated=con.execute("""SELECT COUNT(*),COUNT(rating_code),
        COUNT(*) FILTER (WHERE followup_eligible),
        COUNT(*) FILTER (WHERE repeat_same_item_within_90d),
        COUNT(*) FILTER (WHERE rating_score<1 OR rating_score>5),
        COUNT(*) FILTER (WHERE rating_code IS NOT NULL AND rated_at<ordered_at)
        FROM rated_lines""").fetchone()
    require(rated[0]==sold[0] and rated[4]==rated[5]==0,
            "Rating join multiplied or invalidated sale lines")
    dup=con.execute("""SELECT COUNT(*) FROM (
        SELECT line_code FROM rating_events GROUP BY 1 HAVING COUNT(*)>1)""").fetchone()[0]
    require(dup==0,"Multiple ratings joined to a sale line")
    event_count=con.execute("SELECT COUNT(*) FROM rating_events").fetchone()[0]
    require(event_count==rated[1] and event_count<=counts["ratings"],
            "Rating events do not reconcile")
    grain_checks={}
    for grain in GRAINS:
        rows=con.execute("""SELECT COUNT(*),SUM(sold_lines),SUM(sold_quantity),
            SUM(net_revenue),SUM(direct_contribution),SUM(rating_count),
            SUM(repeat_followup_eligible_ratings),SUM(repeat_same_item_90d_count)
            FROM rating_metrics WHERE grain=?""",[grain]).fetchone()
        require(rows[0]>0 and rows[1]==sold[0] and rows[5]==event_count
                and rows[6]==rated[2] and rows[7]==rated[3]
                and all(abs(float(a)-float(b))<0.01
                        for a,b in zip(rows[2:5],sold[1:4])),
                f"Rating grain does not conserve source: {grain}")
        grain_checks[grain]=int(rows[0])
    bad=con.execute("""SELECT COUNT(*) FROM rating_metrics WHERE
        rating_count>sold_lines OR repeat_same_item_90d_count>
        repeat_followup_eligible_ratings OR rating_coverage<0 OR rating_coverage>1
        OR mean_rating<1 OR mean_rating>5""").fetchone()[0]
    require(bad==0,"Invalid rating coverage, score or repeat rate")
    return {"accepted_completed_lines":int(sold[0]),
            "sold_quantity":float(sold[1]),"net_revenue":float(sold[2]),
            "direct_contribution":float(sold[3]),
            "joined_completed_ratings":int(event_count),
            "accepted_ratings_outside_completed_cohort":int(counts["ratings"]-event_count),
            "eligible_90_day_rating_followups":int(rated[2]),
            "observed_same_item_90_day_repeats":int(rated[3]),
            "grain_rows":grain_checks}


def execute(args):
    require(args.clean.is_dir() and args.quality_report.is_file(),"Missing accepted source")
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
    con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT ?::TIMESTAMP AS as_of",[args.as_of])
    sql_file=Path(__file__).parent/"sql"/"rating_satisfaction.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks=validate(con,counts,args.as_of)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs={}
    for name in ("rating_events","rating_metrics"):
        path=args.output/f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        rows=con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0]
        require(rows==con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"Saved {name} count differs")
        outputs[name]={"path":str(path.resolve()),"rows":int(rows)}
    result={"status":"passed","as_of_exclusive":args.as_of.isoformat(),
            "source_counts":counts,"checks":checks,"outputs":outputs,
            "lineage":{"quality_report_sha256":digest(args.quality_report),
                       "analysis_sql_sha256":digest(sql_file)},
            "interpretation":"Rating means use observed scores only; unrated accepted lines remain in sales and coverage denominators. Monthly sales/rating cohorts use purchase month; raw event rating date is preserved for anomaly work.",
            "limits":"Observed ratings are selective, not a census of satisfaction. Ninety-day repeat is same item/location among identified, follow-up-complete rated buyers; late or anonymous ratings are unknown. Contribution excludes overhead and association is not causation."}
    report_file=args.reports/"rating_satisfaction_report.json"
    report_file.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file.resolve()),"checks":checks},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean",type=Path,required=True)
    parser.add_argument("--quality-report",type=Path,required=True)
    parser.add_argument("--as-of",type=date.fromisoformat,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__=="__main__":
    main()
