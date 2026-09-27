"""Flag review-only promotion traps with explicit before/after evidence."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.promotion_effectiveness import TABLES, load_sources
from python_pipeline.wastage_analysis import digest


FLAGS = ("sales_up_contribution_down", "customers_up_margin_down",
         "eligible_waste_up", "low_post_discount_repeat",
         "possible_high_margin_cannibalization")


def validate(con, prior):
    source = con.execute("""SELECT COUNT(*),SUM(order_volume),SUM(net_revenue),
        SUM(direct_contribution) FROM promotion_effectiveness""").fetchone()
    expected = prior["checks"]
    require(source[0] == expected["campaigns"] and source[1] == expected["campaign_orders"]
            and abs(float(source[2])-expected["campaign_net_revenue"])<0.01
            and abs(float(source[3])-expected["campaign_direct_contribution"])<0.01,
            "Rebuilt Step 27 campaign totals differ")
    duplicate = con.execute("""SELECT COUNT(*) FROM (
        SELECT promotion_code FROM promotion_traps GROUP BY 1 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicate == 0 and con.execute("SELECT COUNT(*) FROM promotion_traps").fetchone()[0] == source[0],
            "Campaign trap population or key differs")
    bad = con.execute("""SELECT COUNT(*) FROM promotion_traps WHERE
        prior_eligible_quantity<0 OR active_eligible_quantity<0
        OR prior_eligible_waste<0 OR active_eligible_waste<0
        OR cannibalization_candidate_count<0
        OR (low_post_discount_repeat AND NOT followup_complete)
        OR (possible_high_margin_cannibalization<>
            (cannibalization_candidate_count>0))""").fetchone()[0]
    require(bad == 0, "Invalid promotion trap evidence")
    flags = {name:con.execute(
        f"SELECT COUNT(*) FROM promotion_traps WHERE {name}").fetchone()[0]
        for name in FLAGS}
    return {"campaigns":int(source[0]),
            "eligible_window_lines":con.execute("SELECT COUNT(*) FROM eligible_window_lines").fetchone()[0],
            "cannibalization_candidates":con.execute("SELECT COUNT(*) FROM cannibalization_candidates").fetchone()[0],
            "flag_counts":{name:int(flags.get(name) or 0) for name in FLAGS}}


def execute(args):
    require(args.clean.is_dir() and args.quality_report.is_file() and
            args.effectiveness_report.is_file() and args.effectiveness.is_file(),
            "Missing accepted source or Step 27 report")
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve()!=args.reports.resolve(),"Output paths must differ")
    for target in (args.output,args.reports):
        for source in (args.clean,args.quality_report,args.effectiveness_report,args.effectiveness):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside source")
    quality = json.loads(args.quality_report.read_text(encoding="utf-8"))
    prior = json.loads(args.effectiveness_report.read_text(encoding="utf-8"))
    require(prior["status"]=="passed" and
            prior["as_of_exclusive"]==args.as_of.isoformat() and
            prior["lineage"]["quality_report_sha256"]==digest(args.quality_report) and
            prior["lineage"]["analysis_sql_sha256"]==digest(Path(__file__).parent/"sql"/"promotion_effectiveness.sql") and
            Path(prior["outputs"]["promotion_effectiveness"]["path"]).resolve()==args.effectiveness.resolve(),
            "Step 27 lineage differs")
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts = load_sources(con,args.clean,quality)
    require(counts=={name:prior["source_counts"][name] for name in TABLES},
            "Accepted source counts differ")
    menu_folder = args.clean/"menu_items"
    require((menu_folder/"_SUCCESS").is_file() and any(menu_folder.rglob("*.parquet")),
            "Missing accepted menu items")
    con.execute(f"CREATE VIEW clean_menu_items AS SELECT * FROM read_parquet('{sql_path(menu_folder)}/**/*.parquet')")
    require(con.execute("SELECT COUNT(*) FROM clean_menu_items").fetchone()[0] ==
            quality["tables"]["menu_items"]["accepted_rows"],
            "Accepted menu item count differs")
    con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT ?::TIMESTAMP AS as_of",[args.as_of])
    con.execute((Path(__file__).parent/"sql"/"promotion_effectiveness.sql").read_text(encoding="utf-8"))
    saved = con.execute(f"""SELECT COUNT(*),SUM(order_volume),SUM(net_revenue)
        FROM read_parquet('{sql_path(args.effectiveness)}')""").fetchone()
    require(saved[0]==prior["outputs"]["promotion_effectiveness"]["rows"] and
            saved[1]==prior["checks"]["campaign_orders"] and
            abs(float(saved[2])-prior["checks"]["campaign_net_revenue"])<0.01,
            "Saved Step 27 campaign file differs")
    sql_file = Path(__file__).parent/"sql"/"promotion_traps.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks = validate(con,prior)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs = {}
    for name in ("eligible_window_metrics","cannibalization_candidates","promotion_traps"):
        path = args.output/f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        rows = con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0]
        require(rows==con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"Saved {name} count differs")
        outputs[name]={"path":str(path.resolve()),"rows":int(rows)}
    result={"status":"passed","as_of_exclusive":args.as_of.isoformat(),
            "checks":checks,"outputs":outputs,
            "thresholds":{"sales_quantity_rise_rate":0.20,
                          "contribution_drop_rate":0.10,
                          "customer_count_rise_rate":0.10,
                          "margin_drop_percentage_points":10,
                          "waste_rise_rate":0.20,"waste_minimum_extra_portions":10,
                          "low_post_30_day_repeat_rate_at_most":0.05,
                          "minimum_followup_customers":30,
                          "cannibalization_item_quantity_rise_rate":0.20,
                          "cannibalization_peer_quantity_drop_rate":0.20},
            "lineage":{"quality_report_sha256":digest(args.quality_report),
                       "step27_report_sha256":digest(args.effectiveness_report),
                       "step27_output_sha256":digest(args.effectiveness),
                       "trap_sql_sha256":digest(sql_file)},
            "interpretation":"These are potential-trap review flags, not proven promotion effects or an automatic success/failure classification.",
            "limits":"Equal-length before/active windows can differ in seasonality and exposure. Eligible-item waste can overlap campaigns. Direct contribution excludes overhead. Discount-only behavior uses observed 30-day repeat, not lifetime loyalty. Cannibalization is a same-category co-movement candidate, not customer substitution proof."}
    report_file=args.reports/"promotion_traps_report.json"
    report_file.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file.resolve()),"checks":checks},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean",type=Path,required=True)
    parser.add_argument("--quality-report",type=Path,required=True)
    parser.add_argument("--effectiveness",type=Path,required=True)
    parser.add_argument("--effectiveness-report",type=Path,required=True)
    parser.add_argument("--as-of",type=date.fromisoformat,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__=="__main__":
    main()
