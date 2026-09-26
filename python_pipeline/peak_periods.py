"""Describe restaurant-local order peaks with calendar-day exposure."""

import argparse
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path


SPECS = (
    ("overall_hour", "NULL", "NULL", "CAST(local_hour AS VARCHAR)", "local_hour"),
    ("location_hour", "restaurant_code", "NULL", "CAST(local_hour AS VARCHAR)", "restaurant_code,local_hour"),
    ("overall_weekday", "NULL", "NULL", "CAST(weekday_number AS VARCHAR)", "weekday_number"),
    ("location_weekday", "restaurant_code", "NULL", "CAST(weekday_number AS VARCHAR)", "restaurant_code,weekday_number"),
    ("overall_weekend", "NULL", "NULL", "day_type", "day_type"),
    ("location_weekend", "restaurant_code", "NULL", "day_type", "restaurant_code,day_type"),
    ("overall_month", "NULL", "NULL", "year_month", "year_month"),
    ("location_month", "restaurant_code", "NULL", "year_month", "restaurant_code,year_month"),
    ("overall_season", "NULL", "NULL", "season", "season"),
    ("location_season", "restaurant_code", "NULL", "season", "restaurant_code,season"),
    ("overall_date", "NULL", "NULL", "CAST(local_date AS VARCHAR)", "local_date"),
    ("location_date", "restaurant_code", "NULL", "CAST(local_date AS VARCHAR)", "restaurant_code,local_date"),
    ("channel_hour", "NULL", "channel_group", "CAST(local_hour AS VARCHAR)", "channel_group,local_hour"),
    ("location_channel_hour", "restaurant_code", "channel_group", "CAST(local_hour AS VARCHAR)", "restaurant_code,channel_group,local_hour"),
    ("channel_weekend", "NULL", "channel_group", "day_type", "channel_group,day_type"),
    ("location_channel_weekend", "restaurant_code", "channel_group", "day_type", "restaurant_code,channel_group,day_type"),
)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register(con, view, directory, expected):
    require((directory / "_SUCCESS").is_file(), f"Missing source success marker: {view}")
    require(any(directory.rglob("*.parquet")), f"Missing source Parquet: {view}")
    con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{sql_path(directory)}/**/*.parquet')")
    count = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
    require(count == expected, f"Source count differs from report: {view}")
    return count


def build_facts(con, cutoff):
    sql = (Path(__file__).parent / "sql" / "peak_periods.sql").read_text(encoding="utf-8")
    require(sql.count("?") == 2, "Unexpected cutoff parameter count")
    con.execute(sql.replace("?", f"DATE '{cutoff.isoformat()}'"))
    return hashlib.sha256(sql.encode()).hexdigest()


def build_metrics(con):
    con.execute("""CREATE TEMP TABLE metric_raw(grain VARCHAR,restaurant_code VARCHAR,
        channel_group VARCHAR,period_label VARCHAR,orders BIGINT,revenue DECIMAL(34,2))""")
    for grain, restaurant, channel, label, groupby in SPECS:
        con.execute(f"""INSERT INTO metric_raw
            SELECT '{grain}', {restaurant}, {channel}, {label}, COUNT(*), SUM(revenue)
            FROM order_facts GROUP BY {groupby}""")
    con.execute("""CREATE OR REPLACE TEMP TABLE period_metrics AS
        WITH exposed AS (
            SELECT m.*,
                   CASE WHEN grain LIKE '%_hour' THEN (SELECT COUNT(*) FROM calendar_days)
                        WHEN grain LIKE '%_weekday' THEN
                            (SELECT COUNT(*) FROM calendar_days c WHERE CAST(c.weekday_number AS VARCHAR)=m.period_label)
                        WHEN grain LIKE '%_weekend' THEN
                            (SELECT COUNT(*) FROM calendar_days c WHERE c.day_type=m.period_label)
                        WHEN grain LIKE '%_month' THEN
                            (SELECT COUNT(*) FROM calendar_days c WHERE c.year_month=m.period_label)
                        WHEN grain LIKE '%_season' THEN
                            (SELECT COUNT(*) FROM calendar_days c WHERE c.season=m.period_label)
                        ELSE 1 END AS exposure_days
            FROM metric_raw m
        )
        SELECT *, orders::DOUBLE / exposure_days AS orders_per_calendar_day,
                  revenue::DOUBLE / exposure_days AS revenue_per_calendar_day
        FROM exposed""")
    con.execute("""CREATE OR REPLACE TEMP TABLE monthly_trends AS
        WITH monthly AS (
            SELECT restaurant_code,period_label AS year_month,orders,revenue,
                   exposure_days,orders_per_calendar_day,
                   LAG(orders_per_calendar_day) OVER (
                       PARTITION BY grain,restaurant_code ORDER BY period_label) AS previous_month_daily_rate
            FROM period_metrics WHERE grain IN ('overall_month','location_month')
        )
        SELECT *, CASE WHEN previous_month_daily_rate > 0 THEN
            (orders_per_calendar_day / previous_month_daily_rate)-1 END AS month_over_month_rate_change
        FROM monthly""")


def audit(con, basket_report, cutoff):
    eligible = con.execute("SELECT COUNT(*),SUM(accepted_basket_revenue) FROM eligible_orders").fetchone()
    facts = con.execute("SELECT COUNT(*),SUM(revenue) FROM order_facts").fetchone()
    require(eligible[0] == facts[0] == basket_report["eligible_baskets"],
            "Eligible order population differs from Step 17")
    require(abs(Decimal(str(eligible[1]))-Decimal(str(facts[1]))) < Decimal("0.01"),
            "Order fact revenue differs from coverage")
    bad = con.execute("""SELECT COUNT(*) FROM order_facts WHERE
        joined_lines <> expected_lines OR distinct_channels <> 1
        OR channel_code IS NULL OR channel_group = 'Other/Unknown'
        OR ABS(joined_revenue-revenue)>0.001 OR local_date >= ?""", [cutoff]).fetchone()[0]
    require(bad == 0, f"Bad channel/line/revenue or future order facts: {bad}")
    start, days = con.execute("SELECT MIN(local_date),COUNT(*) FROM calendar_days").fetchone()
    require(days == (cutoff-start).days, "Calendar exposure has missing/extra days")
    conservation = {}
    for grain, *_ in SPECS:
        rows = con.execute("SELECT SUM(orders),SUM(revenue),MIN(exposure_days) FROM period_metrics WHERE grain=?", [grain]).fetchone()
        require(rows[0] == eligible[0] and abs(Decimal(str(rows[1]))-Decimal(str(eligible[1]))) < Decimal("0.01"),
                f"Metric grain does not conserve orders/revenue: {grain}")
        require(rows[2] > 0, f"Nonpositive exposure at {grain}")
        conservation[grain] = {"rows": con.execute("SELECT COUNT(*) FROM period_metrics WHERE grain=?", [grain]).fetchone()[0],
                               "orders": int(rows[0]), "revenue": str(rows[1])}
    require(con.execute("SELECT COUNT(*) FROM period_metrics WHERE exposure_days<=0 OR orders_per_calendar_day<0").fetchone()[0] == 0,
            "Invalid exposure-normalized rate")
    channels = dict(con.execute("SELECT channel_group,COUNT(*) FROM order_facts GROUP BY 1").fetchall())
    return {"eligible_orders": eligible[0], "eligible_revenue": str(eligible[1]),
            "calendar_start": start.isoformat(), "calendar_days": days,
            "channel_order_counts": channels, "grain_conservation": conservation}


def peaks(con):
    selection = {}
    for grain in ("overall_hour","overall_weekday","overall_date","overall_season",
                  "channel_hour","location_hour","location_weekday",
                  "location_channel_hour"):
        rows = con.execute("""SELECT restaurant_code,channel_group,period_label,orders,
            orders_per_calendar_day FROM (
                SELECT *,ROW_NUMBER() OVER (PARTITION BY restaurant_code,channel_group
                    ORDER BY orders_per_calendar_day DESC,
                    TRY_CAST(period_label AS INTEGER) ASC NULLS LAST,period_label ASC) AS peak_rank
                FROM period_metrics WHERE grain=?) ranked WHERE peak_rank=1
                ORDER BY restaurant_code,channel_group""", [grain]).fetchall()
        selection[grain] = [{"restaurant_code": r, "channel_group": c,
                             "period": p, "orders": int(n), "orders_per_calendar_day": float(rate)}
                            for r,c,p,n,rate in rows]
    weekends = {}
    rows = con.execute("""SELECT restaurant_code,channel_group,
        MAX(CASE WHEN period_label='weekend' THEN orders_per_calendar_day END) AS weekend_rate,
        MAX(CASE WHEN period_label='weekday' THEN orders_per_calendar_day END) AS weekday_rate
        FROM period_metrics WHERE grain IN ('overall_weekend','location_weekend',
             'channel_weekend','location_channel_weekend')
        GROUP BY restaurant_code,channel_group ORDER BY restaurant_code,channel_group""").fetchall()
    for restaurant, channel, weekend, weekday in rows:
        key = f"{restaurant or 'ALL'}|{channel or 'ALL'}"
        weekends[key] = {"weekend_orders_per_day": float(weekend or 0),
                         "weekday_orders_per_day": float(weekday or 0),
                         "weekend_to_weekday_rate_ratio":
                         float((weekend or 0)/weekday) if weekday else None}
    selection["weekend_patterns"] = weekends
    return selection


def execute(args):
    require(args.integration_report.is_file() and args.basket_report.is_file(), "Missing source report")
    require(not args.output.exists() and not args.reports.exists(), "Refusing to overwrite output")
    require(args.output.resolve() != args.reports.resolve(), "Output and reports must differ")
    for target in (args.output,args.reports):
        for source in (args.integration,args.integration_report,args.basket_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside source")
    integration = json.loads(args.integration_report.read_text(encoding="utf-8"))
    basket = json.loads(args.basket_report.read_text(encoding="utf-8"))
    require(integration.get("status") == basket.get("status") == "passed", "Source report did not pass")
    require(basket["lineage"]["integration_report_sha256"] == file_hash(args.integration_report),
            "Basket and integration lineage differs")
    cutoff = date.fromisoformat(basket["cutoff_exclusive"])
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts = {name: register(con,name,args.integration/name,
                             integration["outputs"][name]["rows"])
              for name in ("order_coverage","order_lines")}
    sql_hash = build_facts(con,cutoff)
    build_metrics(con)
    checks = audit(con,basket,cutoff)
    summary = peaks(con)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    metrics_file = args.output/"period_metrics.parquet"
    trends_file = args.output/"monthly_trends.parquet"
    con.execute(f"COPY period_metrics TO '{sql_path(metrics_file)}' (FORMAT PARQUET)")
    con.execute(f"COPY monthly_trends TO '{sql_path(trends_file)}' (FORMAT PARQUET)")
    for path,table in ((metrics_file,"period_metrics"),(trends_file,"monthly_trends")):
        require(con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0] ==
                con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                f"Saved {table} read-back differs")
    result = {"status":"passed","cutoff_exclusive":cutoff.isoformat(),
              "source_counts":counts,**checks,"peaks":summary,
              "outputs":{"period_metrics":str(metrics_file.resolve()),
                         "monthly_trends":str(trends_file.resolve())},
              "lineage":{"integration_report_sha256":file_hash(args.integration_report),
                         "basket_report_sha256":file_hash(args.basket_report),
                         "fact_sql_sha256":sql_hash},
              "limits":"Descriptive local-time peaks; website/app fulfillment unknown; no staffing or forecast claim."}
    report_file = args.reports/"peak_period_report.json"
    report_file.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file),"eligible_orders":checks["eligible_orders"],
                      "calendar_days":checks["calendar_days"],
                      "channel_order_counts":checks["channel_order_counts"],
                      "overall_peak_hour":summary["overall_hour"][0],
                      "overall_peak_weekday":summary["overall_weekday"][0]},indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration",type=Path,required=True)
    parser.add_argument("--integration-report",type=Path,required=True)
    parser.add_argument("--basket-report",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
