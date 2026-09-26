"""Describe accepted food wastage across SRS dimensions without causal claims."""

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path


TABLES = ("orders", "order_items", "restaurants", "menu_items", "wastage", "inventory")
GRAINS = {
    "item": ("item_code",),
    "category": ("category_code",),
    "location": ("restaurant_code",),
    "day": ("business_date",),
    "month": ("year_month",),
    "item_location": ("restaurant_code", "item_code", "category_code"),
    "category_location_month": ("restaurant_code", "category_code", "year_month"),
    "promotion_day": ("promotion_day",),
    "month_promotion_day": ("year_month", "promotion_day"),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def validate_facts(con, counts):
    duplicate = con.execute("""SELECT COUNT(*) FROM (
        SELECT restaurant_code,item_code,business_date FROM wastage_daily
        GROUP BY 1,2,3 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicate == 0, "Duplicate daily keys")
    bad = con.execute("""SELECT COUNT(*) FROM wastage_daily WHERE
        sold_quantity<0 OR wasted_quantity<0 OR prepared_quantity<0
        OR promoted_sold_quantity>sold_quantity OR wasted_quantity>prepared_quantity
        OR waste_cost<0 OR inventory_records>1
        OR (consumed_quantity IS NOT NULL AND
            (consumed_quantity<0 OR consumed_quantity>opening_quantity+replenished_quantity))""").fetchone()[0]
    require(bad == 0, "Invalid daily quantities or duplicate inventory")
    totals = con.execute("""SELECT COUNT(*),SUM(waste_records),SUM(inventory_records),
        SUM(sold_quantity),SUM(wasted_quantity),SUM(prepared_quantity),SUM(waste_cost),
        SUM(consumed_quantity),
        COUNT(*) FILTER (WHERE inventory_records=0 AND
            (sold_quantity>0 OR wasted_quantity>0)),
        COUNT(*) FILTER (WHERE inventory_records>0 AND
            ABS(consumed_quantity-sold_quantity-wasted_quantity)>0.0001)
        FROM wastage_daily""").fetchone()
    require(totals[1] == counts["wastage"] and totals[2] == counts["inventory"],
            "Source wastage/inventory records do not reconcile")
    direct = con.execute("""SELECT SUM(i.quantity) FROM clean_order_items i
        JOIN clean_orders o ON i.order_code=o.code WHERE o.status='completed'""").fetchone()[0]
    require(abs(float(totals[3])-float(direct)) < 0.0001,
            "Daily sold quantity does not reconcile")
    # Clean sources can contain accepted records without a matching inventory
    # snapshot, so report coverage and mismatches rather than hiding either.
    return {"daily_rows": int(totals[0]), "wastage_records": int(totals[1]),
            "inventory_records": int(totals[2]), "sold_quantity": float(totals[3]),
            "wasted_quantity": float(totals[4]),
            "prepared_quantity": float(totals[5]), "waste_cost": float(totals[6]),
            "consumed_quantity": float(totals[7]),
            "inventory_minus_accepted_sales_and_waste":
                float(totals[7] - totals[3] - totals[4]),
            "sale_or_waste_days_without_inventory": int(totals[8]),
            "inventory_consumption_mismatch_days": int(totals[9])}


def summary_query(columns):
    keys = ",".join(columns)
    return f"""SELECT {keys},COUNT(*) AS observed_days,
        SUM(sold_quantity) AS sold_quantity,
        SUM(promoted_sold_quantity) AS promoted_sold_quantity,
        SUM(prepared_quantity) AS prepared_quantity,
        SUM(wasted_quantity) AS wasted_quantity,
        SUM(waste_cost) AS waste_cost,
        SUM(consumed_quantity) AS consumed_quantity,
        SUM(CASE WHEN inventory_records>0 THEN 1 ELSE 0 END) AS inventory_days,
        SUM(CASE WHEN wasted_quantity>0 THEN 1 ELSE 0 END) AS waste_days,
        CASE WHEN SUM(prepared_quantity)>0
             THEN SUM(wasted_quantity)/SUM(prepared_quantity) END AS waste_to_prepared_rate,
        CASE WHEN SUM(sold_quantity)+SUM(wasted_quantity)>0
             THEN SUM(wasted_quantity)/(SUM(sold_quantity)+SUM(wasted_quantity)) END AS waste_share_of_outflow
        FROM wastage_daily GROUP BY {keys}"""


def save_outputs(con, output, totals):
    paths = {}
    specs = {"wastage_daily": "SELECT * FROM wastage_daily"}
    specs.update({f"wastage_by_{name}": summary_query(keys) for name, keys in GRAINS.items()})
    for name, query in specs.items():
        path = output / f"{name}.parquet"
        con.execute(f"COPY ({query}) TO '{sql_path(path)}' (FORMAT PARQUET)")
        count, waste, cost = con.execute(f"""SELECT COUNT(*),SUM(wasted_quantity),SUM(waste_cost)
            FROM read_parquet('{sql_path(path)}')""").fetchone()
        require(count > 0 and abs(float(waste)-totals["wasted_quantity"]) < 0.0001
                and abs(float(cost)-totals["waste_cost"]) < 0.001,
                f"Saved grain does not conserve waste: {name}")
        paths[name] = {"path": str(path.resolve()), "rows": count}
    return paths


def execute(args):
    require(args.clean.is_dir() and args.quality_report.is_file(), "Missing accepted source")
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    for target in (args.output, args.reports):
        for source in (args.clean, args.quality_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside an input source")
    quality = json.loads(args.quality_report.read_text(encoding="utf-8"))
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts = load_sources(con, args.clean, quality)
    sql_file = Path(__file__).parent / "sql" / "wastage_analysis.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    totals = validate_facts(con, counts)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs = save_outputs(con, args.output, totals)
    result = {"status": "passed", "source_counts": counts, "totals": totals,
              "outputs": outputs,
              "lineage": {"quality_report_sha256": digest(args.quality_report),
                          "sql_sha256": digest(sql_file)},
              "interpretation": "Promotion-day grouping is association, not campaign attribution or causal effect. Prepared quantity is summed from accepted wastage records only; missing preparation logs cannot be inferred. Inventory mismatch days are reported, not suppressed."}
    report = args.reports / "wastage_report.json"
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report.resolve()), "totals": totals,
                      "output_rows": {key: value["rows"] for key, value in outputs.items()}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
