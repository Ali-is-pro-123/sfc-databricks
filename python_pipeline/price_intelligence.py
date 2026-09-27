"""Describe price-period relationships from accepted completed sales."""

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


TABLES = ("orders", "order_items", "restaurants", "menu_items",
          "pricing_history", "ratings")


def load_sources(con, clean, quality):
    require(quality.get("status") == "passed", "Step 5 quality report did not pass")
    counts = {}
    for name in TABLES:
        folder = clean / name
        require((folder / "_SUCCESS").is_file() and any(folder.rglob("*.parquet")),
                f"Missing accepted source: {name}")
        con.execute(f"CREATE VIEW clean_{name} AS SELECT * FROM read_parquet('{sql_path(folder)}/**/*.parquet')")
        counts[name] = con.execute(f"SELECT COUNT(*) FROM clean_{name}").fetchone()[0]
        require(counts[name] == quality["tables"][name]["accepted_rows"],
                f"Accepted source count differs: {name}")
    return counts


def validate(con, as_of):
    expected = con.execute("""SELECT COUNT(*),SUM(i.quantity),
        SUM(i.quantity*i.unit_price-i.discount_amount),SUM(i.quantity*i.unit_cost),
        SUM(i.discount_amount) FROM clean_order_items i JOIN clean_orders o
          ON o.code=i.order_code JOIN clean_restaurants r ON r.code=o.restaurant_code
        WHERE o.status='completed' AND
          CAST(timezone(r.timezone,timezone('UTC',o.ordered_at)) AS DATE) < ?""", [as_of]).fetchone()
    line = con.execute("""SELECT COUNT(*),SUM(quantity),
        SUM(quantity*unit_price-discount_amount),SUM(quantity*unit_cost),
        SUM(discount_amount) FROM completed_lines""").fetchone()
    require(expected[0] == line[0] and all(abs(float(a)-float(b)) < 0.01
            for a,b in zip(expected[1:],line[1:])),
            "Completed price-period lines do not reconcile")
    bad = con.execute("""SELECT COUNT(*) FROM completed_lines l
        JOIN price_periods p USING (price_code) WHERE
        ABS(l.unit_price-p.unit_price)>0.001 OR ABS(l.unit_cost-p.unit_cost)>0.001
        OR l.discount_amount<0 OR l.discount_amount>l.quantity*l.unit_price""").fetchone()[0]
    require(bad == 0, "Accepted line differs from effective price or cost")
    dup = con.execute("""SELECT COUNT(*) FROM (
        SELECT line_code FROM completed_lines GROUP BY 1 HAVING COUNT(*)>1)""").fetchone()[0]
    require(dup == 0, "Price-period join multiplied sale lines")
    epochs = con.execute("""SELECT COUNT(*),SUM(sold_lines),SUM(sold_quantity),
        SUM(net_revenue),SUM(direct_cost),SUM(discount_amount),
        COUNT(*) FILTER (WHERE exposure_days<=0 OR sold_quantity<0 OR
            discount_amount<0 OR repeat_lines>identified_lines)
        FROM price_epochs""").fetchone()
    require(epochs[1] == expected[0] and all(abs(float(a)-float(b)) < 0.01
            for a,b in zip(epochs[2:6],expected[1:])) and epochs[6] == 0,
            "Price epochs do not conserve lines or money")
    transitions = con.execute("""SELECT COUNT(*),COUNT(*) FILTER
        (WHERE notable_demand_change) FROM price_transitions""").fetchone()
    return {"accepted_completed_lines": int(expected[0]),
            "sold_quantity": float(expected[1]), "net_revenue": float(expected[2]),
            "direct_cost": float(expected[3]), "direct_contribution": float(expected[2]-expected[3]),
            "discount_amount": float(expected[4]), "price_epoch_rows": int(epochs[0]),
            "price_transition_rows": int(transitions[0]),
            "notable_demand_change_rows": int(transitions[1])}


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
    sql_file = Path(__file__).parent / "sql" / "price_intelligence.sql"
    for statement in sql_file.read_text(encoding="utf-8").split(";"):
        if statement.strip():
            con.execute(statement, [args.as_of] * statement.count("?"))
    totals = validate(con,args.as_of)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs = {}
    for name in ("price_epochs","price_transitions"):
        path = args.output / f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        count = con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0]
        require(count == con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0],
                f"{name} read-back differs")
        outputs[name] = {"path": str(path.resolve()), "rows": count}
    report = {"status":"passed", "as_of_exclusive":args.as_of.isoformat(),
              "source_counts":counts,"totals":totals,"outputs":outputs,
              "lineage":{"quality_report_sha256":digest(args.quality_report),
                         "analysis_sql_sha256":digest(sql_file)},
              "limits":"Descriptive before/after association; price changes may coincide with seasonality, promotions and synthetic demand shifts. Repeat rate is line-based among identified buyers. Missing ratings remain null. Step 26 owns sensitivity classification."}
    report_file = args.reports / "price_intelligence_report.json"
    report_file.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file.resolve()),"totals":totals},indent=2))


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
