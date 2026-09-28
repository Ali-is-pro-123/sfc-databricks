"""Assign transparent business-review priorities to explained recommendations."""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


PRIORITIES = ("Low", "Medium", "High", "Critical")


def decide_priority(kind, metrics, context):
    """Rank review urgency from measured exposure, never promised uplift."""
    if kind == "promote_hidden_opportunity":
        amount = float(context["contribution"])
        priority = "High" if amount >= 20000 else "Medium" if amount >= 10000 else "Low"
        return priority, amount, "PKR", "90-day direct contribution of the local item", \
            "Higher existing contribution increases the scale worth reviewing; promotion uplift is unknown."
    if kind == "review_preparation_quantity":
        amount = float(context["waste_cost"])
        waste_pct = float(metrics["accounted_wastage_percentage"])
        priority = ("Critical" if amount >= 10000 and waste_pct >= 40 else
                    "High" if amount >= 5000 and waste_pct >= 25 else
                    "Medium" if amount >= 2000 else "Low")
        return priority, amount, "PKR", "accepted 90-day recorded waste cost for this item/location", \
            f"Recorded waste cost and {waste_pct:.1f}% accounted wastage drive review urgency; inventory gaps remain."
    if kind == "review_price_sensitivity":
        amount = float(context["revenue"])
        priority = "High" if amount >= 50000 else "Medium" if amount >= 20000 else "Low"
        return priority, amount, "PKR", "90-day accepted revenue of the local item", \
            "More revenue is exposed to a pricing decision; response is descriptive, not causal."
    if kind == "review_bundle":
        amount = float(metrics["local_pair_baskets"])
        lift = float(metrics["local_lift"])
        priority = "High" if amount >= 40 and lift >= 1.5 else "Medium" if amount >= 20 else "Low"
        return priority, amount, "baskets", "eligible local baskets containing the pair", \
            f"Observed pair volume and lift {lift:.2f} guide review; no incremental bundle sales are proven."
    if kind == "review_low_performer":
        contribution = float(metrics["direct_contribution"])
        amount = max(-contribution, 0.0)
        priority = "High" if amount >= 1000 else "Medium" if amount >= 500 else "Low"
        return priority, amount, "PKR", "90-day negative direct contribution, floored at zero", \
            "A larger direct loss raises review urgency; positive-contribution slow movers stay Low, not automatic removals."
    if kind == "review_segment_outreach":
        amount = float(metrics["high_review_customers"])
        priority = "High" if amount >= 10000 else "Medium" if amount >= 1000 else "Low"
        return priority, amount, "customers", "segment customers with high churn-review signal", \
            "The size of the review cohort drives urgency, not a calibrated churn probability."
    if kind == "review_promotion":
        amount = float(context["tagged_campaign_revenue"])
        flags = sum(bool(metrics[key]) for key in (
            "sales_up_contribution_down", "customers_up_margin_down", "eligible_waste_up",
            "low_post_discount_repeat", "possible_high_margin_cannibalization"))
        priority = "High" if amount >= 1000000 and flags >= 2 else "Medium" if amount >= 500000 else "Low"
        return priority, amount, "PKR", "tagged campaign revenue during its observed run", \
            f"Revenue exposure and {flags} potential-trap flags guide review; campaign failure is not established."
    if kind == "investigate_location_anomaly":
        amount = float(context["flagged_revenue"])
        days = int(metrics["flagged_days"])
        priority = "High" if days >= 10 else "Medium" if days >= 5 else "Low"
        return priority, amount, "PKR", "accepted revenue on flagged location days in the latest 90 days", \
            f"{days} anomalous days set review urgency; flagged-day revenue is context, not a loss estimate."
    raise ValueError(f"Unknown recommendation type: {kind}")


def read_report(path, cutoff=None):
    require(path.is_file(), f"Missing source report: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    require(report.get("status") == "passed", f"Source report did not pass: {path}")
    if cutoff is not None:
        value = report.get("as_of_exclusive", report.get("as_of_exclusive_local_date"))
        require(value == cutoff.isoformat(), f"Source cutoff differs: {path}")
    return report


def load_context(con, args, evidence_report):
    reports = {
        "menu": (args.menu_report, read_report(args.menu_report, args.as_of)),
        "waste": (args.waste_report, read_report(args.waste_report)),
        "promotions": (args.promotion_report, read_report(args.promotion_report, args.as_of)),
        "anomalies": (args.anomaly_report, read_report(args.anomaly_report, args.as_of)),
    }
    sources = {"menu": args.menu, "waste": args.waste,
               "promotions": args.promotions, "anomalies": args.anomalies}
    for name, path in sources.items():
        require(path.is_file(), f"Missing context Parquet: {name}")
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{sql_path(path)}')")
    require(con.execute("SELECT COUNT(*) FROM menu").fetchone()[0] ==
            reports["menu"][1]["outputs"]["location_menu_items"]["rows"],
            "Menu context count differs")
    require(con.execute("SELECT COUNT(*) FROM waste").fetchone()[0] ==
            reports["waste"][1]["outputs"]["wastage_daily"]["rows"],
            "Waste context count differs")
    require(con.execute("SELECT COUNT(*) FROM promotions").fetchone()[0] ==
            reports["promotions"][1]["outputs"]["promotion_traps"]["rows"],
            "Promotion context count differs")
    require(con.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0] ==
            reports["anomalies"][1]["checks"]["location_day_rows"],
            "Anomaly context count differs")
    menu = {(restaurant, item): {"revenue": float(revenue), "contribution": float(contribution)}
            for restaurant, item, revenue, contribution in con.execute(
                "SELECT restaurant_code,item_code,revenue,contribution FROM menu").fetchall()}
    waste = {(restaurant, item): {"waste_cost": float(cost)}
             for restaurant, item, cost in con.execute("""SELECT restaurant_code,item_code,SUM(waste_cost)
                 FROM waste WHERE business_date>=? AND business_date<? GROUP BY 1,2""",
                 [args.as_of-timedelta(days=90), args.as_of]).fetchall()}
    promotions = {code: {"tagged_campaign_revenue": float(revenue)}
                  for code, revenue in con.execute("SELECT promotion_code,tagged_campaign_revenue FROM promotions").fetchall()}
    anomalies = {restaurant: {"flagged_revenue": float(revenue)}
                 for restaurant, revenue in con.execute("""SELECT restaurant_code,SUM(net_revenue)
                     FROM anomalies WHERE local_date>=? AND local_date<?
                       AND (sudden_sales_spike OR sudden_sales_drop) GROUP BY 1""",
                     [args.as_of-timedelta(days=90), args.as_of]).fetchall()}
    require(len(menu) == reports["menu"][1]["outputs"]["location_menu_items"]["rows"],
            "Duplicate menu context keys")
    return menu, waste, promotions, anomalies, reports


def execute(args):
    require(args.evidence.is_file() and not args.output.exists() and not args.reports.exists(),
            "Missing evidence or existing output")
    for target in (args.output, args.reports):
        for source in (args.evidence, args.evidence_report, args.menu, args.menu_report,
                       args.waste, args.waste_report, args.promotions, args.promotion_report,
                       args.anomalies, args.anomaly_report):
            require(not target.resolve().is_relative_to(source.resolve()),
                    "Output cannot be inside a source")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    evidence_report = read_report(args.evidence_report, args.as_of)
    require(Path(evidence_report["output"]).resolve() == args.evidence.resolve(),
            "Step 38 report does not identify this evidence snapshot")
    con = duckdb.connect()
    con.execute("SET threads=4")
    menu, waste, promotions, anomalies, reports = load_context(con, args, evidence_report)
    cursor = con.execute("SELECT * FROM read_parquet(?)", [str(args.evidence)])
    names = [column[0] for column in cursor.description]
    rows = [dict(zip(names, values)) for values in cursor.fetchall()]
    require(len(rows) == evidence_report["candidates_explained"], "Evidence population differs")
    output_rows = []
    counts = {}
    for row in rows:
        kind, restaurant, subject = (row[key] for key in
                                     ("recommendation_type", "restaurant_code", "subject_code"))
        metrics = json.loads(row["metrics_json"])
        context = ({"promote_hidden_opportunity": menu.get((restaurant, subject)),
                    "review_price_sensitivity": menu.get((restaurant, subject)),
                    "review_preparation_quantity": waste.get((restaurant, subject)),
                    "review_promotion": promotions.get(subject),
                    "investigate_location_anomaly": anomalies.get(restaurant)}.get(kind, {}))
        require(context is not None, f"Missing impact context: {kind}/{subject}")
        priority, exposure, unit, basis, reason = decide_priority(kind, metrics, context)
        require(priority in PRIORITIES and exposure >= 0, "Invalid priority or exposure")
        counts[priority] = counts.get(priority, 0) + 1
        output_rows.append(tuple(row[name] for name in names) +
                           (priority, exposure, unit, basis, reason))
    require(sum(counts.values()) == len(rows), "Priority coverage differs")
    schema = ",".join(f"{name} VARCHAR" for name in names)
    con.execute(f"CREATE TABLE prioritized_recommendations ({schema}, priority VARCHAR, impact_exposure DOUBLE, impact_unit VARCHAR, impact_basis VARCHAR, priority_reason VARCHAR)")
    con.executemany(f"INSERT INTO prioritized_recommendations VALUES ({','.join('?' for _ in range(len(names)+5))})",
                    output_rows)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    output = args.output / "prioritized_recommendations.parquet"
    con.execute(f"COPY prioritized_recommendations TO '{sql_path(output)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(output)]).fetchone()[0] == len(rows),
            "Saved priority population differs")
    report = {"status": "passed", "as_of_exclusive": args.as_of.isoformat(),
              "candidates_prioritized": len(rows), "priority_counts": counts,
              "output": str(output.resolve()),
              "lineage": {"step38_report_sha256": digest(args.evidence_report),
                          "step38_evidence_sha256": digest(args.evidence),
                          **{name + "_report_sha256": digest(path) for name, (path, _) in reports.items()},
                          "policy_sha256": digest(Path(__file__))},
              "limits": "Priority is review urgency from current exposure and explicit heuristics, not expected savings, uplift or causal effect. Measures differ by action type and must not be summed across rows. No action is executed."}
    report_path = args.reports / "recommendation_priority_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path.resolve()), "candidates_prioritized": len(rows),
                      "priority_counts": counts}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("evidence", "evidence-report", "menu", "menu-report", "waste", "waste-report",
                 "promotions", "promotion-report", "anomalies", "anomaly-report", "output", "reports"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
