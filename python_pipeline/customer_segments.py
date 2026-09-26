"""Create explainable point-in-time customer segments from accepted visits."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def choose_segment(row, as_of, high_value_threshold):
    visits = row["lifetime_visits"]
    if visits == 0:
        if row["joined_on"] >= as_of - timedelta(days=60):
            return "New Customers", "Registered within 60 days; no eligible completed visit yet."
        return "No Purchase Yet", "Registered more than 60 days ago; no eligible completed visit."
    if row["first_visit"] >= as_of - timedelta(days=60):
        return "New Customers", "First eligible completed visit was within 60 days."
    if visits >= 2 and row["visits_90"] == 0:
        return "At-Risk Customers", "Repeat customer with no eligible visit in the last 90 days."
    if row["visits_180"] >= 3 and row["promotion_order_share"] >= 0.5:
        return "Promotion-Driven Customers", "At least half of recent visits used a promotion or discount."
    if row["visits_180"] >= 6 and row["monetary_180"] >= high_value_threshold:
        return "High-Value Loyal Customers", "At least six recent visits and spend at or above the active 75th percentile."
    if row["visits_180"] >= 6:
        return "Frequent Customers", "At least six eligible visits in the last 180 days."
    return "Occasional Customers", "Eligible purchasing history without a higher-priority segment signal."


def register(con, name, folder, expected):
    require((folder / "_SUCCESS").is_file(), f"Missing successful source: {name}")
    require(any(folder.rglob("*.parquet")), f"Missing Parquet source: {name}")
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{sql_path(folder)}/**/*.parquet')")
    count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    require(count == expected, f"{name} row count differs from passed report")
    return count


def execute(args):
    require(args.as_of.day >= 1, "Invalid cutoff")
    for target in (args.output, args.reports):
        require(not target.exists(), f"Refusing to overwrite: {target}")
        for source in (args.integration, args.clean, args.integration_report, args.quality_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside a source")
    require(args.integration_report.is_file() and args.quality_report.is_file(), "Missing source report")
    integration = json.loads(args.integration_report.read_text(encoding="utf-8"))
    quality = json.loads(args.quality_report.read_text(encoding="utf-8"))
    require(integration.get("status") == quality.get("status") == "passed", "Source report did not pass")
    con = duckdb.connect()
    con.execute("SET threads=4")
    counts = {
        "customers": register(con, "customers", args.clean / "customers",
                              quality["tables"]["customers"]["accepted_rows"]),
        "order_coverage": register(con, "order_coverage", args.integration / "order_coverage",
                                   integration["outputs"]["order_coverage"]["rows"]),
        "order_lines": register(con, "order_lines", args.integration / "order_lines",
                                integration["outputs"]["order_lines"]["rows"]),
    }
    source_max = con.execute("SELECT MAX(date) FROM order_lines").fetchone()[0]
    require(args.as_of <= source_max + timedelta(days=1),
            "Cutoff exceeds observed data horizon; inactivity would be untrustworthy")
    sql = (Path(__file__).parent / "sql" / "customer_segments.sql").read_text(encoding="utf-8")
    parameter_count = 0
    for statement in sql.split(";"):
        if statement.strip():
            count = statement.count("?")
            con.execute(statement, [args.as_of] * count)
            parameter_count += count
    require(parameter_count == 8, "Unexpected SQL cutoff parameter count")
    eligible_count = con.execute("SELECT COUNT(*) FROM eligible_orders").fetchone()[0]
    visits = con.execute("SELECT COUNT(*), SUM(revenue), SUM(line_count) FROM visit_facts").fetchone()
    expected = con.execute("SELECT SUM(accepted_basket_revenue), SUM(accepted_line_count) FROM eligible_orders").fetchone()
    require(visits[0] == eligible_count, "Eligible order-to-visit cardinality differs")
    require(abs(float(visits[1] or 0) - float(expected[0] or 0)) < 0.01 and visits[2] == expected[1],
            "Visit money or lines do not reconcile to order coverage")
    invalid = con.execute("""SELECT COUNT(*) FROM visit_facts WHERE
        line_count <> expected_line_count OR ABS(revenue-expected_revenue)>0.001""").fetchone()[0]
    require(invalid == 0, f"Individual basket reconciliation failed: {invalid}")
    feature_count = con.execute("SELECT COUNT(*) FROM customer_features").fetchone()[0]
    expected_customers = con.execute("SELECT COUNT(*) FROM customers WHERE joined_on < ?", [args.as_of]).fetchone()[0]
    require(feature_count == expected_customers, "Customer dimension not fully represented")
    duplicate = con.execute("SELECT COUNT(*) FROM (SELECT customer_code FROM customer_features GROUP BY 1 HAVING COUNT(*)>1)").fetchone()[0]
    require(duplicate == 0, "Duplicate customer feature rows")
    frequency = con.execute("SELECT SUM(lifetime_visits), SUM(lifetime_monetary) FROM customer_features").fetchone()
    require(frequency[0] == eligible_count and abs(float(frequency[1])-float(visits[1])) < 0.01,
            "Customer-level visit totals do not reconcile")
    threshold = con.execute("""SELECT quantile_cont(monetary_180, 0.75)
        FROM customer_features WHERE visits_180 > 0""").fetchone()[0]
    require(threshold is not None, "No active customers for spend threshold")
    cursor = con.execute("SELECT * FROM customer_features ORDER BY customer_code")
    names = [column[0] for column in cursor.description]
    customers = [dict(zip(names, row)) for row in cursor.fetchall()]
    assignments = [(row["customer_code"], *choose_segment(row, args.as_of, threshold))
                   for row in customers]
    segments = Counter(segment for _, segment, _ in assignments)
    require(sum(segments.values()) == feature_count, "Not every customer received one segment")
    con.execute("CREATE TEMP TABLE assignments(customer_code VARCHAR, segment VARCHAR, segment_reason VARCHAR)")
    con.executemany("INSERT INTO assignments VALUES (?,?,?)", assignments)
    con.execute("""CREATE TEMP VIEW customer_segments AS SELECT f.*, a.segment, a.segment_reason
        FROM customer_features f JOIN assignments a USING (customer_code)""")
    excluded = dict(con.execute("""SELECT
        CASE WHEN status <> 'completed' THEN 'cancelled'
             WHEN customer_code IS NULL THEN 'anonymous'
             WHEN accepted_line_count = 0 THEN 'empty_basket'
             WHEN known_rejected_lines > 0 THEN 'known_partial_basket'
             WHEN CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) >= ? THEN 'on_or_after_cutoff'
             ELSE 'eligible' END AS reason, COUNT(*)
        FROM order_coverage GROUP BY 1""", [args.as_of]).fetchall())
    require(excluded.get("eligible", 0) == eligible_count, "Exclusion audit differs from eligible count")
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    output_file = args.output / "customer_segments.parquet"
    con.execute(f"COPY customer_segments TO '{sql_path(output_file)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(output_file)]).fetchone()[0] == feature_count,
            "Saved segment read-back count differs")
    report = {"status": "passed", "as_of_exclusive": args.as_of.isoformat(),
              "source_counts": counts, "eligible_visits": eligible_count,
              "eligible_lines": int(visits[2]), "eligible_revenue": str(visits[1]),
              "included_customers": feature_count, "excluded_order_counts": excluded,
              "high_value_active_spend_p75": float(threshold),
              "segment_counts": dict(segments), "output": str(output_file.resolve()),
              "lineage": {"integration_report": str(args.integration_report.resolve()),
                          "integration_report_sha256": sha256(args.integration_report),
                          "quality_report": str(args.quality_report.resolve()),
                          "quality_report_sha256": sha256(args.quality_report),
                          "sql_sha256": hashlib.sha256(sql.encode()).hexdigest()},
              "limitations": ["Observed promotion-use share is not causal sensitivity.",
                              "Known partial, empty and cancelled baskets are excluded.",
                              "Synthetic data does not establish live segment validity."]}
    report_file = args.reports / "segmentation_report.json"
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_file), "eligible_visits": eligible_count,
                      "included_customers": feature_count, "segment_counts": dict(segments)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--integration-report", type=Path, required=True)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
