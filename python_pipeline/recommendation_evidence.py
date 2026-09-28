"""Turn every review candidate into an auditable, human-readable explanation."""

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


def number(value, digits=1):
    require(value is not None, "Missing required evidence value")
    return f"{float(value):,.{digits}f}"


def explain(kind, evidence):
    """Keep observations distinct from the action a reviewer may consider."""
    if kind == "promote_hidden_opportunity":
        require(evidence["location_class"] == "Hidden Opportunity" and not evidence["provisional"],
                "Hidden opportunity evidence is inconsistent")
        lines = [f"Local menu class: Hidden Opportunity; direct margin {number(evidence['direct_margin_percentage'])}%.",
                 f"Average rating {number(evidence['average_rating'])}/5 from {int(evidence['rating_count'])} ratings.",
                 f"Accounted wastage {number(evidence['accounted_wastage_percentage'])}% and {int(evidence['order_frequency'])} accepted orders in the 90-day window."]
        limit = "A promotion may not increase profit; review capacity, discount cost and local demand before testing."
    elif kind == "review_preparation_quantity":
        lines = [f"Recorded waste: {number(evidence['wasted_quantity'], 0)} portions; accounted wastage {number(evidence['accounted_wastage_percentage'])}%.",
                 f"The dish sold {number(evidence['quantity_sold'], 0)} portions and its movement class is {evidence['movement_class']}."]
        limit = "The waste share uses accepted sales and waste, not a complete inventory reconciliation."
    elif kind == "review_price_sensitivity":
        require(evidence["sensitivity_class"] == "highly_price_sensitive", "Price class differs")
        lines = [f"Local price-sensitivity class: {evidence['sensitivity_class']} across {int(evidence['eligible_changes'])} eligible price changes.",
                 f"Peer-adjusted response index range {number(evidence['min_response_index'], 2)} to {number(evidence['max_response_index'], 2)}; {number(evidence['compared_portions'], 0)} compared portions."]
        limit = "The response index is descriptive and confounded; it is not causal elasticity or permission to change price."
    elif kind == "review_bundle":
        lines = [f"Local pair appeared in {int(evidence['local_pair_baskets'])} eligible baskets; confidence {number(100*evidence['local_confidence'])}% and lift {number(evidence['local_lift'], 2)}.",
                 f"Both items had positive 90-day direct contribution ({number(evidence['antecedent_contribution_90'], 2)} and {number(evidence['consequent_contribution_90'], 2)} PKR)."]
        limit = "Co-purchase does not prove bundle lift; live stock is not verified and discount margin needs review."
    elif kind == "review_low_performer":
        require(evidence["location_class"] == "Low Performer" and evidence["movement_class"] == "slow_moving"
                and not evidence["provisional"], "Low-performer evidence is inconsistent")
        lines = [f"Local class is Low Performer and movement class is slow_moving after {int(evidence['item_age_days'])} item-age days.",
                 f"It sold {number(evidence['quantity_sold'], 0)} portions with {number(evidence['direct_contribution'], 2)} PKR direct contribution."]
        limit = "Review customer demand, availability and strategic role before redesign or removal; no automatic deletion."
    elif kind == "review_segment_outreach":
        lines = [f"{int(evidence['high_review_customers']):,} of {int(evidence['customers']):,} segment customers ({number(100*evidence['high_review_share'])}%) have high review priority.",
                 f"Their combined recent 90-day accepted spend is {number(evidence['recent_90_spend'], 2)} PKR."]
        limit = "Risk bands are heuristic, not churn probabilities; check consent, fairness and campaign costs before outreach."
    elif kind == "review_promotion":
        flag_names = {"sales_up_contribution_down": "sales rose while contribution fell",
                      "customers_up_margin_down": "customer count rose while margin fell",
                      "eligible_waste_up": "eligible-item waste rose",
                      "low_post_discount_repeat": "observed post-discount repeat was low",
                      "possible_high_margin_cannibalization": "possible high-margin cannibalization"}
        flags = [label for key, label in flag_names.items() if evidence[key]]
        require(flags, "Promotion has no review flag")
        lines = [f"Potential-trap signals: {', '.join(flags)}.",
                 f"The tagged campaign has {int(evidence['tagged_campaign_orders']):,} accepted orders."]
        limit = "Before/after and overlap effects are observational; the flags do not prove campaign ineffectiveness."
    elif kind == "investigate_location_anomaly":
        lines = [f"The location had {int(evidence['flagged_days'])} flagged sales days in the latest 90 days: {int(evidence['drop_days'])} drops and {int(evidence['spike_days'])} spikes."]
        limit = "An anomaly is not proof of fraud or operational failure; check events, holidays and source quality."
    else:
        raise ValueError(f"No evidence renderer for {kind}")
    require(all(line and "None" not in line for line in lines), "Incomplete evidence text")
    return lines, limit


def execute(args):
    require(args.input.is_file() and args.source_report.is_file(), "Missing Step 37 source")
    require(not args.output.exists() and not args.reports.exists(), "Refusing to overwrite existing output")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    for target in (args.output, args.reports):
        require(not target.resolve().is_relative_to(args.input.resolve()) and
                not target.resolve().is_relative_to(args.source_report.resolve()),
                "Output cannot be inside a source")
    source = json.loads(args.source_report.read_text(encoding="utf-8"))
    require(source.get("status") == "passed" and Path(source["output"]).resolve() == args.input.resolve(),
            "Step 37 report does not identify this passed source")
    con = duckdb.connect()
    rows = con.execute("SELECT * FROM read_parquet(?)", [str(args.input)]).fetchall()
    names = [x[0] for x in con.description]
    require(len(rows) == source["checks"]["candidates"], "Step 37 candidate count differs")
    rendered = []
    identifiers = set()
    counts = {}
    for values in rows:
        row = dict(zip(names, values))
        evidence = json.loads(row["evidence_json"])
        lines, limitation = explain(row["recommendation_type"], evidence)
        identity = "|".join(str(row[key] or "") for key in
                            ("recommendation_type", "scope", "restaurant_code", "subject_code", "related_code"))
        candidate_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        require(candidate_id not in identifiers, "Duplicate recommendation identity")
        identifiers.add(candidate_id)
        counts[row["recommendation_type"]] = counts.get(row["recommendation_type"], 0) + 1
        rendered.append((candidate_id, row["recommendation_type"], row["scope"],
                         row["restaurant_code"], row["subject_code"], row["related_code"],
                         row["recommended_action"], json.dumps(lines, ensure_ascii=False),
                         limitation, row["source_steps"], row["evidence_json"],
                         source["as_of_exclusive"]))
    require(counts == source["checks"]["by_type"], "Evidence coverage differs by type")
    con.execute("""CREATE TABLE recommendation_evidence (
        candidate_id VARCHAR, recommendation_type VARCHAR, scope VARCHAR,
        restaurant_code VARCHAR, subject_code VARCHAR, related_code VARCHAR,
        recommended_action VARCHAR, reason_lines_json VARCHAR, limitation VARCHAR,
        source_steps VARCHAR, metrics_json VARCHAR, as_of_exclusive VARCHAR)""")
    con.executemany("INSERT INTO recommendation_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rendered)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    output = args.output / "recommendation_evidence.parquet"
    con.execute(f"COPY recommendation_evidence TO '{sql_path(output)}' (FORMAT PARQUET)")
    require(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(output)]).fetchone()[0] == len(rows),
            "Saved evidence count differs")
    report = {"status": "passed", "as_of_exclusive": source["as_of_exclusive"],
              "candidates_explained": len(rows), "by_type": counts, "output": str(output.resolve()),
              "lineage": {"step37_report_sha256": digest(args.source_report),
                          "step37_candidates_sha256": digest(args.input),
                          "renderer_sha256": digest(Path(__file__))},
              "limits": "Every candidate has descriptive evidence and a caveat. Reasons explain the review screen, not causal efficacy. No recommendation is executed or prioritized here."}
    report_file = args.reports / "recommendation_evidence_report.json"
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_file.resolve()), "candidates_explained": len(rows),
                      "by_type": counts}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
