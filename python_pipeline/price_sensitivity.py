"""Classify descriptive, peer-adjusted price-response evidence."""

import argparse
import json
from pathlib import Path

import duckdb

from python_pipeline.demand import require, sql_path
from python_pipeline.wastage_analysis import digest


PAIR_CLASSES = ("highly_price_sensitive", "moderately_price_sensitive",
                "low_price_sensitivity", "mixed_evidence", "insufficient_evidence")
ITEM_CLASSES = (*PAIR_CLASSES[:3], "mixed_location_evidence", "insufficient_evidence")


def validate(con, source):
    expected = {"price_epochs": source["outputs"]["price_epochs"]["rows"],
                "price_transitions": source["outputs"]["price_transitions"]["rows"]}
    require(con.execute("SELECT COUNT(*) FROM price_epochs").fetchone()[0] == expected["price_epochs"]
            and con.execute("SELECT COUNT(*) FROM price_transitions").fetchone()[0] == expected["price_transitions"],
            "Step 25 source row counts differ")
    counts = {}
    for name, key in (("transition_evidence", "price_code"),
                      ("pair_sensitivity", "restaurant_code,item_code"),
                      ("item_sensitivity", "item_code")):
        row_count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        unique_count = con.execute(f"SELECT COUNT(*) FROM (SELECT {key} FROM {name} GROUP BY {key})").fetchone()[0]
        require(row_count == unique_count, f"Duplicate {name} key")
        counts[name] = int(row_count)
    require(counts["transition_evidence"] == expected["price_transitions"],
            "Transition evidence population differs")
    pair_count = con.execute("SELECT COUNT(*) FROM (SELECT DISTINCT restaurant_code,item_code FROM price_epochs)").fetchone()[0]
    item_count = con.execute("SELECT COUNT(*) FROM (SELECT DISTINCT item_code FROM price_epochs)").fetchone()[0]
    require(counts["pair_sensitivity"] == pair_count and counts["item_sensitivity"] == item_count,
            "Classification population differs")
    bad = con.execute("""SELECT COUNT(*) FROM transition_evidence WHERE
        eligible AND (response_index IS NULL OR NOT isfinite(response_index)
        OR peer_count<5 OR prior_sold_quantity<20 OR sold_quantity<20
        OR prior_exposure_days<30 OR exposure_days<30)""").fetchone()[0]
    require(bad == 0, "Eligible response evidence is invalid")
    bad_pair = con.execute("""SELECT COUNT(*) FROM pair_sensitivity WHERE
        (eligible_changes<2 AND sensitivity_class<>'insufficient_evidence')
        OR (sensitivity_class NOT IN (?,?,?,?,?))""", list(PAIR_CLASSES)).fetchone()[0]
    require(bad_pair == 0, "Invalid pair class or insufficient evidence")
    bad_item = con.execute("""SELECT COUNT(*) FROM item_sensitivity WHERE
        classified_locations<12 AND sensitivity_class<>'insufficient_evidence'""").fetchone()[0]
    require(bad_item == 0, "Item class lacks location support")
    return {"rows": counts,
            "eligible_transitions": con.execute("SELECT COUNT(*) FROM transition_evidence WHERE eligible").fetchone()[0],
            "pair_classes": dict(con.execute("SELECT sensitivity_class,COUNT(*) FROM pair_sensitivity GROUP BY 1").fetchall()),
            "item_classes": dict(con.execute("SELECT sensitivity_class,COUNT(*) FROM item_sensitivity GROUP BY 1").fetchall())}


def execute(args):
    require(args.price_report.is_file(), "Missing Step 25 report")
    require(not args.output.exists() and not args.reports.exists(),
            "Refusing to overwrite existing output")
    require(args.output.resolve() != args.reports.resolve(), "Output paths must differ")
    source = json.loads(args.price_report.read_text(encoding="utf-8"))
    require(source["status"] == "passed", "Step 25 report did not pass")
    for name, path in (("price_epochs", args.epochs),
                       ("price_transitions", args.transitions)):
        require(path.is_file() and
                path.resolve() == Path(source["outputs"][name]["path"]).resolve(),
                f"Step 25 {name} lineage differs")
    for target in (args.output,args.reports):
        for input_path in (args.epochs,args.transitions,args.price_report):
            require(not target.resolve().is_relative_to(input_path.resolve()),
                    "Output cannot be inside source")
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(f"CREATE VIEW price_epochs AS SELECT * FROM read_parquet('{sql_path(args.epochs)}')")
    con.execute(f"CREATE VIEW price_transitions AS SELECT * FROM read_parquet('{sql_path(args.transitions)}')")
    sql_file = Path(__file__).parent / "sql" / "price_sensitivity.sql"
    con.execute(sql_file.read_text(encoding="utf-8"))
    checks = validate(con,source)
    args.output.mkdir(parents=True)
    args.reports.mkdir(parents=True)
    outputs = {}
    for name in ("transition_evidence","pair_sensitivity","item_sensitivity"):
        path = args.output/f"{name}.parquet"
        con.execute(f"COPY {name} TO '{sql_path(path)}' (FORMAT PARQUET)")
        require(con.execute("SELECT COUNT(*) FROM read_parquet(?)",[str(path)]).fetchone()[0] == checks["rows"][name],
                f"Saved {name} count differs")
        outputs[name] = str(path.resolve())
    result = {"status":"passed","as_of_exclusive":source["as_of_exclusive"],
              "checks":checks,"outputs":outputs,
              "thresholds":{"minimum_price_increase_rate":0.03,"minimum_period_days":30,
                            "minimum_period_portions":20,"minimum_peers":5,
                            "maximum_discount_share_shift":0.15,
                            "minimum_pair_transitions":2,"minimum_item_locations":12,
                            "item_majority_share":0.60,
                            "response_index_low_below":0.5,
                            "response_index_high_at_least":1.5},
              "lineage":{"step25_report_sha256":digest(args.price_report),
                         "price_epochs_sha256":digest(args.epochs),
                         "price_transitions_sha256":digest(args.transitions),
                         "analysis_sql_sha256":digest(sql_file)},
              "limits":"Peer-adjusted descriptive response index, not causal price elasticity. Simultaneous price changes, seasonality and promotions remain confounders; classes are review-only."}
    report = args.reports/"price_sensitivity_report.json"
    report.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"report":str(report.resolve()),"checks":checks},indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs",type=Path,required=True)
    parser.add_argument("--transitions",type=Path,required=True)
    parser.add_argument("--price-report",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--reports",type=Path,required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
