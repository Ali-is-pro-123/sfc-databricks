"""Score recency, frequency and monetary value for every known customer."""

import argparse
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_scores(con, as_of):
    quantiles = con.execute("""SELECT quantile_cont(monetary_180, [0.25,0.50,0.75,0.90])
        FROM customer_source WHERE visits_180 > 0 AND monetary_180 > 0""").fetchone()[0]
    require(quantiles is not None and len(quantiles) == 4,
            "No active purchasers for monetary thresholds")
    require(all(left <= right for left, right in zip(quantiles, quantiles[1:])),
            "Monetary thresholds are not monotonic")
    con.execute("""CREATE TEMP TABLE rfm_thresholds AS
        SELECT ?::DATE AS as_of_exclusive, ?::DOUBLE AS p25, ?::DOUBLE AS p50,
               ?::DOUBLE AS p75, ?::DOUBLE AS p90""", [as_of, *quantiles])
    sql = (Path(__file__).parent / "sql" / "rfm_scores.sql").read_text(encoding="utf-8")
    con.execute(sql)
    return dict(zip(("p25", "p50", "p75", "p90"), (float(x) for x in quantiles))), hashlib.sha256(sql.encode()).hexdigest()


def execute(args):
    require(args.input.is_file() and args.source_report.is_file(), "Missing Step 15 source")
    for target in (args.output, args.reports):
        require(not target.exists(), f"Refusing to overwrite: {target}")
        require(not target.resolve().is_relative_to(args.input.resolve()),
                "Output cannot be inside source")
    require(args.output.resolve() != args.reports.resolve(), "Output and report paths must differ")
    source_report = json.loads(args.source_report.read_text(encoding="utf-8"))
    require(source_report.get("status") == "passed", "Step 15 source did not pass")
    require(Path(source_report["output"]).resolve() == args.input.resolve(),
            "Step 15 report does not identify this snapshot")
    as_of = date.fromisoformat(source_report["as_of_exclusive"])
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(f"CREATE VIEW customer_source AS SELECT * FROM read_parquet('{sql_path(args.input)}')")
    count = con.execute("SELECT COUNT(*) FROM customer_source").fetchone()[0]
    require(count == source_report["included_customers"], "Customer row count changed")
    duplicates = con.execute("""SELECT COUNT(*) FROM (
        SELECT customer_code FROM customer_source GROUP BY 1 HAVING COUNT(*) > 1)""").fetchone()[0]
    require(duplicates == 0, "Duplicate source customer key")
    checks = con.execute("""SELECT COUNT(*) FROM customer_source WHERE
        customer_code IS NULL OR joined_on >= ? OR last_visit >= ?
        OR lifetime_visits < 0 OR visits_180 < 0 OR visits_180 > lifetime_visits
        OR lifetime_monetary < 0 OR monetary_180 < 0
        OR monetary_180 > lifetime_monetary + 0.001
        OR (lifetime_visits = 0 AND (last_visit IS NOT NULL OR recency_days IS NOT NULL
            OR lifetime_monetary <> 0 OR visits_180 <> 0 OR monetary_180 <> 0))
        OR (lifetime_visits > 0 AND (last_visit IS NULL OR recency_days <> date_diff('day',last_visit,?)))""",
        [as_of, as_of, as_of]).fetchone()[0]
    require(checks == 0, f"Invalid source RFM measures: {checks}")
    source_totals = con.execute("""SELECT SUM(lifetime_visits), SUM(lifetime_monetary)
        FROM customer_source""").fetchone()
    require(source_totals[0] == source_report["eligible_visits"] and
            abs(Decimal(str(source_totals[1])) - Decimal(source_report["eligible_revenue"])) < Decimal("0.01"),
            "RFM source totals do not reconcile to Step 15 report")
    segment_counts = dict(con.execute("SELECT segment, COUNT(*) FROM customer_source GROUP BY 1").fetchall())
    require(segment_counts == source_report["segment_counts"], "Source segment counts changed")
    thresholds, sql_hash = create_scores(con, as_of)
    scored_count = con.execute("SELECT COUNT(*) FROM rfm_scores").fetchone()[0]
    require(scored_count == count, "A customer was lost while scoring")
    invalid_scores = con.execute("""SELECT COUNT(*) FROM rfm_scores WHERE
        r_score NOT BETWEEN 0 AND 5 OR f_score NOT BETWEEN 0 AND 5 OR m_score NOT BETWEEN 0 AND 5
        OR rfm_total <> r_score+f_score+m_score
        OR (lifetime_visits=0 AND (rfm_code <> '000' OR rfm_tier <> 'No Purchase History'))
        OR (lifetime_visits>0 AND (r_score=0 OR f_score=0 OR m_score=0))""").fetchone()[0]
    require(invalid_scores == 0, f"Invalid RFM score rows: {invalid_scores}")
    tier_counts = dict(con.execute("SELECT rfm_tier, COUNT(*) FROM rfm_scores GROUP BY 1").fetchall())
    rfm_codes = dict(con.execute("SELECT rfm_code, COUNT(*) FROM rfm_scores GROUP BY 1 ORDER BY 1").fetchall())
    cross_tab = [{"behavioral_segment": segment, "rfm_tier": tier, "customers": amount}
                 for segment, tier, amount in con.execute("""SELECT behavioral_segment,rfm_tier,COUNT(*)
                     FROM rfm_scores GROUP BY 1,2 ORDER BY 1,2""").fetchall()]
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    scored_file = args.output / "rfm_scores.parquet"
    con.execute(f"COPY rfm_scores TO '{sql_path(scored_file)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(scored_file)]).fetchone()[0] == count,
            "Saved RFM read-back failed")
    report = {"status": "passed", "as_of_exclusive": as_of.isoformat(),
              "population": count, "eligible_visits": int(source_totals[0]),
              "lifetime_monetary": str(round(float(source_totals[1]), 2)),
              "monetary_positive_active_quantiles": thresholds,
              "tier_counts": tier_counts, "rfm_code_counts": rfm_codes,
              "behavioral_segment_by_rfm_tier": cross_tab,
              "output": str(scored_file.resolve()),
              "lineage": {"step15_report": str(args.source_report.resolve()),
                          "step15_report_sha256": hash_file(args.source_report),
                          "step15_snapshot": str(args.input.resolve()),
                          "step15_snapshot_sha256": hash_file(args.input),
                          "scoring_sql_sha256": sql_hash},
              "limits": "Descriptive point-in-time score; no causal or predictive claim."}
    report_file = args.reports / "rfm_report.json"
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_file), "population": count,
                      "thresholds": thresholds, "tier_counts": tier_counts}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
