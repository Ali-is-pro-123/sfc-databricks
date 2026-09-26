"""Compute presence-based item association rules from complete order baskets."""

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_view(con, name, path, expected):
    require((path / "_SUCCESS").is_file(), f"Missing Spark success marker: {name}")
    require(any(path.rglob("*.parquet")), f"Missing source Parquet: {name}")
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{sql_path(path)}/**/*.parquet')")
    observed = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    require(observed == expected, f"Source count differs from report: {name}")
    return observed


def build_baskets(con, cutoff, min_pair_orders):
    sql = (Path(__file__).parent / "sql" / "market_basket.sql").read_text(encoding="utf-8")
    parameters = [cutoff, min_pair_orders]
    index = 0
    for statement in sql.split(";"):
        if statement.strip():
            count = statement.count("?")
            con.execute(statement, parameters[index:index + count])
            index += count
    require(index == len(parameters), "Unexpected basket SQL parameters")
    return hashlib.sha256(sql.encode()).hexdigest()


def audit(con, cutoff, min_pair_orders):
    basket_count = con.execute("SELECT COUNT(*) FROM eligible_orders").fetchone()[0]
    require(basket_count > 0, "No eligible baskets")
    bad_lines = con.execute("""SELECT COUNT(*) FROM line_reconciliation WHERE
        actual_lines <> expected_lines OR ABS(actual_revenue-expected_revenue) > 0.001""").fetchone()[0]
    require(bad_lines == 0, f"Basket line/money reconciliation failed: {bad_lines}")
    require(con.execute("SELECT COUNT(*) FROM line_reconciliation").fetchone()[0] == basket_count,
            "An eligible basket has no joined lines")
    require(con.execute("SELECT COUNT(*) FROM basket_items WHERE item_code IS NULL").fetchone()[0] == 0,
            "Null item in eligible basket")
    unique_items = con.execute("SELECT COUNT(*) FROM basket_items").fetchone()[0]
    item_total = con.execute("SELECT SUM(item_baskets) FROM item_counts").fetchone()[0]
    require(unique_items == item_total, "Item presence does not reconcile")
    expected_pair_occurrences = con.execute("""SELECT SUM(item_count*(item_count-1)/2)
        FROM (SELECT order_code, COUNT(*) AS item_count FROM basket_items GROUP BY 1)""").fetchone()[0]
    observed_pair_occurrences = con.execute("SELECT COALESCE(SUM(pair_baskets),0) FROM pair_counts").fetchone()[0]
    require(int(expected_pair_occurrences or 0) == int(observed_pair_occurrences),
            "Pair occurrences do not reconcile to basket sizes")
    pairs = con.execute("SELECT COUNT(*) FROM frequent_pairs").fetchone()[0]
    rules = con.execute("SELECT COUNT(*) FROM association_rules").fetchone()[0]
    require(rules == 2 * pairs, "Both rule directions were not emitted")
    invalid = con.execute("""SELECT COUNT(*) FROM association_rules WHERE
        antecedent_item_code = consequent_item_code OR pair_baskets < ?
        OR pair_baskets > antecedent_baskets OR pair_baskets > consequent_baskets
        OR support <= 0 OR support > 1 OR confidence <= 0 OR confidence > 1
        OR lift <= 0 OR ABS(support-pair_baskets::DOUBLE/total_baskets)>0.000000001
        OR ABS(confidence-pair_baskets::DOUBLE/antecedent_baskets)>0.000000001
        OR ABS(lift-confidence/(consequent_baskets::DOUBLE/total_baskets))>0.000000001""",
        [min_pair_orders]).fetchone()[0]
    require(invalid == 0, f"Invalid association metrics: {invalid}")
    duplicated = con.execute("""SELECT COUNT(*) FROM (
        SELECT antecedent_item_code, consequent_item_code FROM association_rules
        GROUP BY 1,2 HAVING COUNT(*) > 1)""").fetchone()[0]
    require(duplicated == 0, "Duplicate directed rules")
    pair_count = con.execute("SELECT COUNT(*) FROM pair_counts").fetchone()[0]
    excluded = dict(con.execute("""SELECT CASE
        WHEN status <> 'completed' THEN 'cancelled'
        WHEN accepted_line_count = 0 THEN 'empty_basket'
        WHEN known_rejected_lines > 0 THEN 'known_partial_basket'
        WHEN CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) >= ? THEN 'on_or_after_cutoff'
        ELSE 'eligible' END AS reason, COUNT(*) FROM order_coverage GROUP BY 1""",
        [cutoff]).fetchall())
    require(excluded.get("eligible", 0) == basket_count, "Basket exclusion audit differs")
    return {"eligible_baskets": basket_count, "distinct_item_presences": unique_items,
            "all_unordered_pairs": pair_count, "all_pair_occurrences": int(observed_pair_occurrences),
            "retained_pairs": pairs, "directed_rules": rules,
            "excluded_order_counts": excluded}


def execute(args):
    require(args.min_pair_orders >= 1, "Minimum pair orders must be positive")
    require(args.integration_report.is_file(), "Missing integration report")
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite an output path")
    require(args.output.resolve() != args.reports.resolve(),
            "Output and report paths must differ")
    for target in (args.output, args.reports):
        for source in (args.integration, args.integration_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside source")
    report = json.loads(args.integration_report.read_text(encoding="utf-8"))
    require(report.get("status") == "passed", "Integration report did not pass")
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts = {name: source_view(con, name, args.integration / name,
                                report["outputs"][name]["rows"])
              for name in ("order_coverage", "order_lines")}
    max_date = con.execute("SELECT MAX(date) FROM order_lines").fetchone()[0]
    require(args.cutoff <= max_date + timedelta(days=1),
            "Cutoff exceeds source observation horizon")
    sql_hash = build_baskets(con, args.cutoff, args.min_pair_orders)
    checks = audit(con, args.cutoff, args.min_pair_orders)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    pairs_file = args.output / "frequent_pairs.parquet"
    rules_file = args.output / "association_rules.parquet"
    con.execute(f"COPY frequent_pairs TO '{sql_path(pairs_file)}' (FORMAT PARQUET)")
    con.execute(f"COPY association_rules TO '{sql_path(rules_file)}' (FORMAT PARQUET)")
    for path, expected in ((pairs_file, checks["retained_pairs"]),
                           (rules_file, checks["directed_rules"])):
        require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0] == expected,
                f"Saved Parquet read-back differs: {path}")
    strongest = [dict(zip(("antecedent", "consequent", "pair_baskets", "support", "confidence", "lift"), row))
                 for row in con.execute("""SELECT antecedent_item_code,consequent_item_code,
                     pair_baskets,support,confidence,lift FROM association_rules
                     ORDER BY lift DESC, pair_baskets DESC, antecedent_item_code,
                     consequent_item_code LIMIT 20""").fetchall()]
    result = {"status": "passed", "cutoff_exclusive": args.cutoff.isoformat(),
              "minimum_pair_baskets": args.min_pair_orders, "source_counts": counts,
              **checks, "top_lift_rules": strongest,
              "outputs": {"frequent_pairs": str(pairs_file.resolve()),
                          "association_rules": str(rules_file.resolve())},
              "lineage": {"integration_report": str(args.integration_report.resolve()),
                          "integration_report_sha256": hash_file(args.integration_report),
                          "sql_sha256": sql_hash},
              "limits": "Association is not causal promotion lift or a ready-to-publish bundle recommendation."}
    report_file = args.reports / "market_basket_report.json"
    report_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_file), **checks}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--integration-report", type=Path, required=True)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--min-pair-orders", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
