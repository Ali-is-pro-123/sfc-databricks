"""Produce location-level, evidence-backed menu recommendation candidates."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register_directory(con, view, directory, expected):
    require((directory / "_SUCCESS").is_file(), f"Missing successful source: {view}")
    require(any(directory.rglob("*.parquet")), f"Missing Parquet source: {view}")
    con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{sql_path(directory)}/**/*.parquet')")
    observed = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
    require(observed == expected, f"Source count mismatch for {view}")
    return observed


def register_file(con, view, file, expected):
    require(file.is_file(), f"Missing Parquet source: {view}")
    con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{sql_path(file)}')")
    observed = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
    require(observed == expected, f"Source count mismatch for {view}")
    return observed


def build(con, cutoff):
    sql = (Path(__file__).parent / "sql" / "recommendations.sql").read_text(encoding="utf-8")
    require(sql.count("?") == 1, "Unexpected recommendation SQL cutoff count")
    con.execute(sql.replace("?", f"DATE '{cutoff.isoformat()}'"))
    return hashlib.sha256(sql.encode()).hexdigest()


def audit(con, basket_report):
    baskets = con.execute("SELECT COUNT(*) FROM eligible_orders").fetchone()[0]
    local_baskets = con.execute("SELECT SUM(local_baskets) FROM local_basket_counts").fetchone()[0]
    require(baskets == local_baskets == basket_report["eligible_baskets"],
            "Local basket population differs from Step 17")
    presences = con.execute("SELECT COUNT(*) FROM local_basket_items").fetchone()[0]
    require(presences == basket_report["distinct_item_presences"],
            "Local distinct item presences differ from Step 17")
    pair_occurrences = con.execute("SELECT SUM(local_pair_baskets) FROM local_pair_counts").fetchone()[0]
    require(pair_occurrences == basket_report["all_pair_occurrences"],
            "Local pair occurrences differ from Step 17")
    missing_global = con.execute("""SELECT COUNT(*) FROM global_pairs gp
        LEFT JOIN (SELECT item_a,item_b,SUM(local_pair_baskets) AS local_total
                   FROM local_pair_counts GROUP BY 1,2) lp USING (item_a,item_b)
        WHERE gp.pair_baskets IS DISTINCT FROM lp.local_total""").fetchone()[0]
    require(missing_global == 0, f"Global pair counts differ from local sums: {missing_global}")
    screen_counts = dict(con.execute("SELECT screen_status,COUNT(*) FROM pair_screen GROUP BY 1").fetchall())
    candidate_count = con.execute("SELECT COUNT(*) FROM candidate_recommendations").fetchone()[0]
    require(candidate_count > 0, "No recommendation candidates passed the guards")
    duplicates = con.execute("""SELECT COUNT(*) FROM (
        SELECT restaurant_code,recommendation_type,antecedent_item_code,
               consequent_item_code FROM candidate_recommendations
        GROUP BY 1,2,3,4 HAVING COUNT(*)>1)""").fetchone()[0]
    require(duplicates == 0, "Duplicate recommendation keys")
    invalid = con.execute("""SELECT COUNT(*) FROM candidate_recommendations c
        LEFT JOIN global_rules r ON c.antecedent_item_code=r.antecedent_item_code
                                AND c.consequent_item_code=r.consequent_item_code
        LEFT JOIN pair_screen ps ON c.restaurant_code=ps.restaurant_code
              AND LEAST(c.antecedent_item_code,c.consequent_item_code)=ps.item_a
              AND GREATEST(c.antecedent_item_code,c.consequent_item_code)=ps.item_b
        WHERE r.antecedent_item_code IS NULL OR ps.screen_status <> 'eligible'
          OR c.local_pair_baskets < 10
          OR c.local_lift < 1.05 OR c.antecedent_contribution_90 <= 0
          OR c.consequent_contribution_90 <= 0 OR c.antecedent_price <= 0
          OR c.consequent_price <= 0 OR c.live_stock_verified <> FALSE
          OR ABS(c.global_confidence-r.confidence)>0.000000001
          OR ABS(c.local_support-c.local_pair_baskets::DOUBLE/c.local_baskets)>0.000000001
          OR ABS(c.local_confidence-c.local_pair_baskets::DOUBLE/c.antecedent_baskets)>0.000000001
          OR (c.recommendation_type='combo_meal' AND
              (c.local_pair_baskets::DOUBLE/c.consequent_baskets < 0.15
               OR c.local_confidence < 0.15 OR c.local_lift < 1.10 OR c.local_rank > 5))
          OR (c.recommendation_type='frequently_paired' AND c.local_rank > 10)
          OR (c.recommendation_type IN ('cross_sell','upsell_add_on') AND
              (c.local_confidence < 0.08 OR c.local_rank > 3))
          OR (c.recommendation_type='cross_sell' AND
              c.consequent_price > c.antecedent_price*1.10)
          OR (c.recommendation_type='upsell_add_on' AND
              c.consequent_price <= c.antecedent_price*1.10)""").fetchone()[0]
    require(invalid == 0, f"Invalid or unsubstantiated candidates: {invalid}")
    types = dict(con.execute("SELECT recommendation_type,COUNT(*) FROM candidate_recommendations GROUP BY 1").fetchall())
    locations = con.execute("SELECT COUNT(DISTINCT restaurant_code) FROM candidate_recommendations").fetchone()[0]
    return {"eligible_baskets": baskets, "distinct_item_presences": presences,
            "pair_occurrences": pair_occurrences, "screen_status_counts": screen_counts,
            "candidate_count": candidate_count, "candidate_type_counts": types,
            "locations_with_candidates": locations}


def execute(args):
    for source in (args.integration_report, args.basket_report, args.profit_report, args.quality_report):
        require(source.is_file(), f"Missing source report: {source}")
    for target in (args.output, args.reports):
        require(not target.exists(), f"Refusing to overwrite: {target}")
        for source in (args.integration, args.baskets, args.profitability, args.clean,
                       args.integration_report, args.basket_report, args.profit_report,
                       args.quality_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside an input source")
    require(args.output.resolve() != args.reports.resolve(), "Output and reports must differ")
    integration = json.loads(args.integration_report.read_text(encoding="utf-8"))
    basket = json.loads(args.basket_report.read_text(encoding="utf-8"))
    profit = json.loads(args.profit_report.read_text(encoding="utf-8"))
    quality = json.loads(args.quality_report.read_text(encoding="utf-8"))
    require(all(report.get("status") == "passed" for report in (integration,basket,profit,quality)),
            "A source report did not pass")
    cutoff = date.fromisoformat(basket["cutoff_exclusive"])
    require(profit["as_of_exclusive_local_date"] == cutoff.isoformat(),
            "Basket and profitability cutoffs differ")
    integration_hash = hash_file(args.integration_report)
    require(basket["lineage"]["integration_report_sha256"] == integration_hash
            and profit["integration_report_sha256"] == integration_hash,
            "Upstream integration lineage differs")
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts = {
        "order_coverage": register_directory(con,"order_coverage",args.integration/"order_coverage",
                                              integration["outputs"]["order_coverage"]["rows"]),
        "order_lines": register_directory(con,"order_lines",args.integration/"order_lines",
                                           integration["outputs"]["order_lines"]["rows"]),
        "local_performance": register_directory(con,"local_performance",
            args.profitability/"item_location_performance",
            profit["outputs"]["item_location_performance"]["rows"]),
        "menu_items": register_directory(con,"menu_items",args.clean/"menu_items",
                                          quality["tables"]["menu_items"]["accepted_rows"]),
        "global_pairs": register_file(con,"global_pairs",args.baskets/"frequent_pairs.parquet",
                                      basket["retained_pairs"]),
        "global_rules": register_file(con,"global_rules",args.baskets/"association_rules.parquet",
                                      basket["directed_rules"]),
    }
    require(con.execute("SELECT COUNT(*) FROM local_performance WHERE feature_as_of <> ?", [cutoff]).fetchone()[0] == 0,
            "Profitability rows have a different cutoff")
    require(con.execute("SELECT COUNT(*) FROM (SELECT restaurant_code,item_code FROM local_performance GROUP BY 1,2 HAVING COUNT(*)>1)").fetchone()[0] == 0,
            "Duplicate local performance keys")
    sql_hash = build(con, cutoff)
    checks = audit(con, basket)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    output_file = args.output / "recommendation_candidates.parquet"
    con.execute(f"COPY candidate_recommendations TO '{sql_path(output_file)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(output_file)]).fetchone()[0] == checks["candidate_count"],
            "Saved recommendation read-back differs")
    examples = [dict(zip(("restaurant_code","type","antecedent","consequent",
                          "local_pair_baskets","local_confidence","local_lift"), row))
                for row in con.execute("""SELECT restaurant_code,recommendation_type,
                    antecedent_item_code,consequent_item_code,local_pair_baskets,
                    local_confidence,local_lift FROM candidate_recommendations
                    ORDER BY local_pair_baskets DESC,recommendation_type,
                             restaurant_code LIMIT 20""").fetchall()]
    result = {"status":"passed", "cutoff_exclusive":cutoff.isoformat(),
              "source_counts":counts, **checks, "examples":examples,
              "output":str(output_file.resolve()),
              "lineage":{"integration_report_sha256":integration_hash,
                         "basket_report_sha256":hash_file(args.basket_report),
                         "profit_report_sha256":hash_file(args.profit_report),
                         "quality_report_sha256":hash_file(args.quality_report),
                         "sql_sha256":sql_hash},
              "publication_status":"review_only_live_stock_and_offer_economics_unverified"}
    report_file = args.reports / "recommendation_report.json"
    report_file.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report_file),**checks},indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration",type=Path,required=True)
    parser.add_argument("--integration-report",type=Path,required=True)
    parser.add_argument("--baskets",type=Path,required=True)
    parser.add_argument("--basket-report",type=Path,required=True)
    parser.add_argument("--profitability",type=Path,required=True)
    parser.add_argument("--profit-report",type=Path,required=True)
    parser.add_argument("--clean",type=Path,required=True)
    parser.add_argument("--quality-report",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
