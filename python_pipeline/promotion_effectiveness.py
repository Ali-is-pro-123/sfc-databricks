"""Measure campaign economics, observed customers and eligible-item wastage."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


TABLES = ("orders", "order_items", "restaurants", "promotions",
          "promotion_items", "wastage")


def load_sources(con, clean, quality):
    require(quality.get("status") == "passed", "Step 5 quality report did not pass")
    counts = {}
    for name in TABLES:
        folder = clean/name
        require((folder/"_SUCCESS").is_file() and any(folder.rglob("*.parquet")),
                f"Missing accepted source: {name}")
        con.execute(f"CREATE VIEW clean_{name} AS SELECT * FROM read_parquet('{sql_path(folder)}/**/*.parquet')")
        counts[name] = con.execute(f"SELECT COUNT(*) FROM clean_{name}").fetchone()[0]
        require(counts[name] == quality["tables"][name]["accepted_rows"],
                f"Accepted source count differs: {name}")
    return counts


def validate(con, counts):
    total_orders = con.execute("SELECT COUNT(*) FROM accepted_orders").fetchone()[0]
    duplicate = con.execute("""SELECT COUNT(*) FROM (
        SELECT order_code FROM accepted_orders GROUP BY 1 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicate == 0, "Accepted order grain is not unique")
    bad = con.execute("""SELECT COUNT(*) FROM campaign_order_facts WHERE
        attributed_quantity>sold_quantity OR attributed_revenue>net_revenue+discount_amount
        OR first_observed_customer_order AND returning_customer_order""").fetchone()[0]
    require(bad == 0, "Invalid campaign order attribution or customer state")
    summed = con.execute("""SELECT COUNT(*),SUM(net_revenue),SUM(direct_contribution),
        SUM(discount_amount) FROM campaign_order_facts""").fetchone()
    campaigns = con.execute("""SELECT COUNT(*),SUM(order_volume),SUM(net_revenue),
        SUM(direct_contribution),SUM(discount_amount),
        COUNT(*) FILTER (WHERE followup_complete),
        COUNT(*) FILTER (WHERE order_volume>0 AND direct_contribution<0)
        FROM promotion_effectiveness""").fetchone()
    require(campaigns[0] == counts["promotions"] and campaigns[1] == summed[0]
            and all(abs(float(a or 0)-float(b or 0))<0.01
                    for a,b in zip(campaigns[2:5],summed[1:4])),
            "Campaign order/money totals do not reconcile")
    duplicate = con.execute("""SELECT COUNT(*) FROM (
        SELECT promotion_code FROM promotion_effectiveness GROUP BY 1 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicate == 0, "Duplicate campaign keys")
    bad_campaign = con.execute("""SELECT COUNT(*) FROM promotion_effectiveness WHERE
        order_volume<0 OR sold_quantity<0 OR discount_amount<0
        OR first_observed_customers>identified_customers
        OR returning_customers>identified_customers
        OR post_30_day_repeat_customers>identified_customers
        OR active_eligible_item_waste<0 OR campaign_days<=0""").fetchone()[0]
    require(bad_campaign == 0, "Invalid campaign-level measures")
    return {"accepted_completed_orders": int(total_orders),
            "campaigns": int(campaigns[0]),"campaign_orders": int(campaigns[1]),
            "campaign_net_revenue": float(campaigns[2] or 0),
            "campaign_direct_contribution": float(campaigns[3] or 0),
            "campaign_discount": float(campaigns[4] or 0),
            "complete_30_day_followup_campaigns": int(campaigns[5]),
            "negative_contribution_campaigns": int(campaigns[6])}


def execute(args):
    require(args.clean.is_dir() and args.quality_report.is_file(), "Missing accepted source")
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    for target in (args.output,args.reports):
        for source in (args.clean,args.quality_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside source")
    quality = json.loads(args.quality_report.read_text(encoding="utf-8"))
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts = load_sources(con,args.clean,quality)
    con.execute("CREATE TEMP TABLE analysis_parameters AS SELECT ?::TIMESTAMP AS as_of",[args.as_of])
    sql_file = Path(__file__).parent/"sql"/"promotion_effectiveness.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks = validate(con,counts)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs = {}
    for name in ("campaign_order_facts","promotion_effectiveness"):
        path = args.output/f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        rows = con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0]
        require(rows == con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"Saved {name} count differs")
        outputs[name] = {"path":str(path.resolve()),"rows":int(rows)}
    result = {"status":"passed","as_of_exclusive":args.as_of.isoformat(),
              "source_counts":counts,"checks":checks,"outputs":outputs,
              "lineage":{"quality_report_sha256":digest(args.quality_report),
                         "analysis_sql_sha256":digest(sql_file)},
              "interpretation":"No automatic success label. Revenue, direct contribution, discount, observed acquisition/repeat, AOV, eligible-item waste and complete/partial post-30-day follow-up must be considered together.",
              "limits":"Accepted line baskets can be incomplete after quarantine. First observed is not guaranteed truly new. Wastage of eligible items may overlap campaigns and cannot be causally attributed. Post behavior is observational."}
    report_file = args.reports/"promotion_effectiveness_report.json"
    report_file.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file.resolve()),"checks":checks},indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean",type=Path,required=True)
    parser.add_argument("--quality-report",type=Path,required=True)
    parser.add_argument("--as-of",type=date.fromisoformat,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
