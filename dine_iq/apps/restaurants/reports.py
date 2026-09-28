"""Verified, location-scoped narrative reports for offline HTML download."""

from pathlib import Path

import duckdb
from django.conf import settings

from .customer_dashboard import build_customer_dashboard
from .dashboard_data import DashboardUnavailable, _read_report, build_executive_dashboard
from .dual_dashboard import build_dual_dashboard
from .forecast_dashboard import build_forecast_dashboard
from .menu_dashboard import build_menu_dashboard
from .wastage_dashboard import build_wastage_dashboard


REPORTS = {
    "menu-performance": "Menu performance",
    "profitability": "Profitability",
    "customer-segmentation": "Customer segmentation",
    "market-basket": "Market-basket analysis",
    "demand-forecast": "Demand forecast",
    "wastage": "Wastage",
    "promotions": "Promotions",
    "pricing": "Pricing",
    "location-performance": "Location performance",
    "anomalies": "Anomalies",
    "recommendations": "Recommendations",
    "spark-python": "Spark versus Python",
}


def _section(title, columns, rows, note=""):
    return {"title": title, "columns": columns, "rows": rows, "note": note}


def _path(root, relative):
    path = root / relative
    if not path.is_file():
        raise DashboardUnavailable(f"Report source is missing: {path.name}")
    return path.as_posix().replace("'", "''")


def _scoped_source(root, codes, relative, expected=None):
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(f"CREATE VIEW source AS SELECT * FROM read_parquet('{_path(root, relative)}')")
    if expected is not None and con.execute("SELECT COUNT(*) FROM source").fetchone()[0] != expected:
        con.close()
        raise DashboardUnavailable("Report source row count differs")
    con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
    con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in codes])
    return con


def _market_basket(root, codes):
    report = _read_report(root / "processed_data/step17-full/market_basket_report.json",
                          "cutoff_exclusive", "2026-07-01")
    integration = _read_report(root / "processed_data/step06-full/integration_report.json",
                               "status", "passed")
    coverage_folder = root / "parquet_data/step06-full/order_coverage"
    if not (coverage_folder / "_SUCCESS").is_file():
        raise DashboardUnavailable("Market-basket coverage source is missing")
    scope_con = duckdb.connect()
    try:
        scope_con.execute(f"CREATE VIEW coverage AS SELECT * FROM read_parquet('{coverage_folder.as_posix()}/**/*.parquet')")
        if scope_con.execute("SELECT COUNT(*) FROM coverage").fetchone()[0] != integration["outputs"]["order_coverage"]["rows"]:
            raise DashboardUnavailable("Market-basket coverage count differs")
        source_codes = {row[0] for row in scope_con.execute("SELECT DISTINCT restaurant_code FROM coverage").fetchall()}
    finally:
        scope_con.close()
    full_network = source_codes <= set(codes)
    if full_network:
        con = duckdb.connect()
        try:
            con.execute(f"CREATE VIEW rules AS SELECT * FROM read_parquet('{_path(root, 'parquet_data/step17-full/association_rules.parquet')}')")
            if con.execute("SELECT COUNT(*) FROM rules").fetchone()[0] != report["directed_rules"]:
                raise DashboardUnavailable("Market-basket rule count differs")
            rows = con.execute("""SELECT antecedent_item_code,consequent_item_code,pair_baskets,
                ROUND(100*support,2),ROUND(100*confidence,2),ROUND(lift,2)
                FROM rules ORDER BY lift DESC,pair_baskets DESC,antecedent_item_code LIMIT 15""").fetchall()
            baskets = report["eligible_baskets"]
        finally:
            con.close()
    else:
        con = duckdb.connect()
        try:
            for name in ("order_coverage", "order_lines"):
                folder = root / "parquet_data/step06-full" / name
                if not (folder / "_SUCCESS").is_file():
                    raise DashboardUnavailable("Market-basket integration source is missing")
                con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{folder.as_posix()}/**/*.parquet')")
                if con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] != integration["outputs"][name]["rows"]:
                    raise DashboardUnavailable("Market-basket integration count differs")
            con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
            con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in codes])
            con.execute("""CREATE TEMP TABLE baskets AS SELECT c.order_code FROM order_coverage c
                JOIN allowed_locations a USING (restaurant_code)
                WHERE c.status='completed' AND c.accepted_line_count>0 AND c.known_rejected_lines=0
                  AND CAST(timezone(c.timezone,timezone('UTC',c.ordered_at)) AS DATE)<DATE '2026-07-01'""")
            baskets = con.execute("SELECT COUNT(*) FROM baskets").fetchone()[0]
            con.execute("""CREATE TEMP TABLE presence AS SELECT DISTINCT b.order_code,l.item_code
                FROM baskets b JOIN order_lines l USING (order_code)""")
            rows = con.execute("""WITH item_counts AS (
                  SELECT item_code,COUNT(*) AS baskets FROM presence GROUP BY 1
                ), pairs AS (
                  SELECT a.item_code AS left_item,b.item_code AS right_item,COUNT(*) AS pair_baskets
                  FROM presence a JOIN presence b ON a.order_code=b.order_code AND a.item_code<b.item_code
                  GROUP BY 1,2 HAVING COUNT(*)>=30
                ), directed AS (
                  SELECT p.left_item AS antecedent,p.right_item AS consequent,p.pair_baskets,
                    x.baskets AS antecedent_baskets,y.baskets AS consequent_baskets FROM pairs p
                    JOIN item_counts x ON p.left_item=x.item_code JOIN item_counts y ON p.right_item=y.item_code
                  UNION ALL
                  SELECT p.right_item,p.left_item,p.pair_baskets,y.baskets,x.baskets FROM pairs p
                    JOIN item_counts x ON p.left_item=x.item_code JOIN item_counts y ON p.right_item=y.item_code
                ) SELECT antecedent,consequent,pair_baskets,
                    ROUND(100*pair_baskets::DOUBLE/?,2),
                    ROUND(100*pair_baskets::DOUBLE/antecedent_baskets,2),
                    ROUND(pair_baskets::DOUBLE*?/(antecedent_baskets*consequent_baskets),2)
                  FROM directed ORDER BY 6 DESC,pair_baskets DESC,antecedent LIMIT 15""",
                [baskets, baskets]).fetchall()
        finally:
            con.close()
    notes = [f"{baskets:,} eligible complete baskets; minimum 30 pair baskets.",
             "Support and confidence describe co-purchase, not causal cross-sell impact."]
    if not full_network:
        notes.append("Rules were recalculated for accessible locations; they are not filtered network-wide rules.")
    return notes, [
        _section("Highest-lift directed rules", ("Antecedent", "Consequent", "Pair baskets", "Support %", "Confidence %", "Lift"), rows)]


def build_report(slug, allowed_codes, root=None):
    """Return only verified report content visible to the caller's locations."""
    if slug not in REPORTS:
        raise KeyError(slug)
    codes = sorted(set(allowed_codes))
    if not codes:
        raise DashboardUnavailable("No accessible locations")
    root = Path(root or settings.PROJECT_ROOT)
    notes = []
    sections = []
    scope_count = len(codes)
    if slug in ("menu-performance", "profitability"):
        data = build_menu_dashboard(codes, root=root)
        if data["empty"]:
            raise DashboardUnavailable("No scoped menu evidence")
        scope_count = data["location_count"]
        if slug == "menu-performance":
            sections.append(_section("Menu class distribution", ("Class", "Pairs"),
                                     [(name, data["class_counts"][name]) for name in data["menu_classes"]]))
            top = sorted(data["items"], key=lambda x: x["revenue"], reverse=True)[:15]
            sections.append(_section("Highest-revenue item/location pairs",
                                     ("Location", "Item", "Class", "Sold", "Revenue PKR"),
                                     [(r["restaurant_code"], r["item_name"], r["location_menu_class"],
                                       r["quantity_sold"], f'{r["revenue"]:.2f}') for r in top]))
            notes.append("Classes are peer-relative 90-day review signals, not automatic menu decisions.")
        else:
            sections.append(_section("90-day direct economics", ("Measure", "Value"),
                                     [("Revenue PKR", f'{data["revenue"]:.2f}'),
                                      ("Direct contribution PKR", f'{data["direct_contribution"]:.2f}'),
                                      ("Direct margin %", f'{data["direct_margin_percentage"]:.2f}')]))
            top = sorted(data["items"], key=lambda x: x["contribution"], reverse=True)[:15]
            sections.append(_section("Highest direct-contribution pairs", ("Location", "Item", "Contribution PKR"),
                                     [(r["restaurant_code"], r["item_name"], f'{r["contribution"]:.2f}') for r in top]))
            notes.append("Direct contribution excludes overhead, financing, tax and platform fees; it is not net profit.")
    elif slug == "customer-segmentation":
        data = build_customer_dashboard(codes, root=root)
        if data["empty"]:
            raise DashboardUnavailable("No scoped customer evidence")
        scope_count = data["location_count"]
        sections = [_section("Behavioral segments", ("Segment", "Customers"), data["segment_rows"]),
                    _section("RFM distribution", ("Tier", "Customers"), data["tier_rows"])]
        notes.append("Local scopes recompute segments from visits at accessible locations; network labels are not filtered into local reports.")
        notes.append("Promotion use is observational, not causal sensitivity. Churn bands are review signals.")
    elif slug == "market-basket":
        menu = build_menu_dashboard(codes, root=root)
        if menu["empty"]:
            raise DashboardUnavailable("No scoped menu evidence")
        scope_count = menu["location_count"]
        notes, sections = _market_basket(root, codes)
    elif slug == "demand-forecast":
        data = build_forecast_dashboard(codes, root=root)
        if data["empty"]:
            raise DashboardUnavailable("No scoped forecast evidence")
        scope_count = data["location_count"]
        sections = [_section("Historical accepted sold portions", ("Month", "Actual"),
                             [(r["month"], f'{r["quantity"]:.0f}') for r in data["history"]]),
                    _section("Future forecast portions", ("Month", "Forecast", "Planning review"),
                             [(r["month"], f'{r["quantity"]:.0f}', "Yes" if r["planning_review"] else "No")
                              for r in data["future"]])]
        if data["full_network"]:
            sections.append(_section("Held-out one-month backtest", ("Month", "Actual", "Predicted", "WAPE %"),
                                     [(r["month"], f'{r["actual"]:.0f}', f'{r["predicted"]:.0f}', f'{r["wape"]:.1f}')
                                      for r in data["backtest"]]))
        notes.append("Future July-September actuals are unavailable. Forecasts are review-only, not inventory or staffing instructions.")
    elif slug == "wastage":
        data = build_wastage_dashboard(codes, root=root)
        if data["empty"]:
            raise DashboardUnavailable("No scoped wastage evidence")
        scope_count = data["location_count"]
        sections = [_section("Historical accepted wastage", ("Measure", "Value"),
                             [("Wasted portions", f'{data["wasted_quantity"]:.0f}'),
                              ("Recorded cost PKR", f'{data["waste_cost"]:.2f}'),
                              ("Waste share of outflow %", f'{data["waste_share"]:.2f}')]),
                    _section("Highest-cost items", ("Item", "Portions", "Cost PKR"),
                             [(r["code"], f'{r["quantity"]:.0f}', f'{r["cost"]:.2f}') for r in data["items"]]),
                    _section("Recent monthly trend", ("Month", "Portions", "Cost PKR"),
                             [(r["month"], f'{r["quantity"]:.0f}', f'{r["cost"]:.2f}') for r in data["trends"]])]
        notes.append("Inventory reconciliation is incomplete. July risk scores are exploratory and not waste quantities.")
    elif slug == "location-performance":
        data = build_executive_dashboard(codes, root=root)
        if data["empty"]:
            raise DashboardUnavailable("No scoped location evidence")
        scope_count = data["location_count"]
        sections = [_section("Accessible location performance", ("Location", "Orders", "Revenue PKR", "Direct contribution PKR"),
                             [(r["name"], r["orders"], f'{r["revenue"]:.2f}',
                               f'{r["direct_contribution"]:.2f}') for r in data["locations"]])]
        notes.append("Historical 90-day accepted metrics; direct contribution is not net accounting profit.")
    elif slug == "spark-python":
        data = build_dual_dashboard(codes, root=root)
        if data["empty"]:
            raise DashboardUnavailable("No scoped paired predictions")
        scope_count = data["location_count"]
        sections = [_section("Held-out comparison summary", ("Measure", "Value"),
                             [("Paired records", data["rows"]), ("Agreement %", f'{data["agreement"]:.2f}'),
                              ("Disagreements", data["disagreements"]),
                              ("Spark MAE", f'{data["spark_mae"]:.2f}'),
                              ("Python MAE", f'{data["python_mae"]:.2f}')]),
                    _section("By target month", ("Month", "Pairs", "Agreement %", "Spark MAE", "Python MAE"),
                             [(r["month"], r["rows"], f'{r["agreement"]:.2f}',
                               f'{r["spark_mae"]:.2f}', f'{r["python_mae"]:.2f}') for r in data["by_month"]])]
        notes.append("Match uses max(2 portions, 20% of actual) tolerance; agreement is not accuracy or deployment approval.")
    else:
        notes, sections = _specialized_report(slug, root, codes)
    return {"slug": slug, "title": REPORTS[slug], "location_count": scope_count,
            "as_of": "2026-07-01 (exclusive)", "sections": sections, "notes": notes}


def _specialized_report(slug, root, codes):
    """Read location-bearing verified facts for the remaining report families."""
    if slug == "promotions":
        report = _read_report(root / "processed_data/step27-full/promotion_effectiveness_report.json",
                              "as_of_exclusive", "2026-07-01")
        con = _scoped_source(root, codes, "parquet_data/step27-full/campaign_order_facts.parquet",
                             report["outputs"]["campaign_order_facts"]["rows"])
        try:
            rows = con.execute("""SELECT promotion_code,COUNT(*),ROUND(SUM(net_revenue),2),
                ROUND(SUM(discount_amount),2),ROUND(SUM(direct_contribution),2)
                FROM source JOIN allowed_locations USING (restaurant_code)
                GROUP BY 1 ORDER BY 3 DESC,promotion_code LIMIT 20""").fetchall()
        finally:
            con.close()
        return ["Campaign-tagged completed orders only. Contribution and repeat behavior are descriptive, not causal promotion lift."], [
            _section("Campaign-tagged orders", ("Promotion", "Orders", "Revenue PKR", "Discount PKR", "Direct contribution PKR"), rows)]
    if slug == "pricing":
        report = _read_report(root / "processed_data/step25-full/price_intelligence_report.json",
                              "as_of_exclusive", "2026-07-01")
        con = _scoped_source(root, codes, "parquet_data/step25-full/price_transitions.parquet",
                             report["totals"]["price_transition_rows"])
        try:
            count = con.execute("SELECT COUNT(*) FROM source JOIN allowed_locations USING (restaurant_code)").fetchone()[0]
            rows = con.execute("""SELECT restaurant_code,item_code,ROUND(100*price_change_rate,1),
                ROUND(unit_price,2),ROUND(sold_per_exposure_day,2),notable_demand_change
                FROM source JOIN allowed_locations USING (restaurant_code)
                WHERE price_change_rate IS NOT NULL
                ORDER BY ABS(price_change_rate) DESC,restaurant_code,item_code LIMIT 20""").fetchall()
        finally:
            con.close()
        return [f"{count:,} observed price transitions in accessible locations.",
                "Demand change near a price event is descriptive, not a causal price-elasticity estimate."], [
            _section("Largest observed price changes", ("Location", "Item", "Price change %", "New unit price PKR", "Sold/day", "Notable demand change"), rows)]
    if slug == "anomalies":
        report = _read_report(root / "processed_data/step31-full/sales_anomalies_report.json",
                              "as_of_exclusive", "2026-07-01")
        con = _scoped_source(root, codes, "parquet_data/step31-full/location_day_anomalies.parquet",
                             report["checks"]["location_day_rows"])
        try:
            counts = con.execute("""SELECT COUNT(*) FILTER (WHERE sudden_sales_spike),
                COUNT(*) FILTER (WHERE sudden_sales_drop) FROM source
                JOIN allowed_locations USING (restaurant_code)""").fetchone()
            rows = con.execute("""SELECT restaurant_code,local_date,orders,ROUND(net_revenue,2),
                CASE WHEN sudden_sales_spike THEN 'Spike' ELSE 'Drop' END
                FROM source JOIN allowed_locations USING (restaurant_code)
                WHERE sudden_sales_spike OR sudden_sales_drop
                ORDER BY local_date DESC,restaurant_code LIMIT 20""").fetchall()
        finally:
            con.close()
        return [f"{counts[0]} spike flags and {counts[1]} drop flags in accessible locations.",
                "Flags are statistical review signals, not confirmed operational errors."], [
            _section("Recent flagged location-days", ("Location", "Date", "Orders", "Revenue PKR", "Flag"), rows)]
    if slug == "recommendations":
        report = _read_report(root / "processed_data/step39-full/recommendation_priority_report.json",
                              "as_of_exclusive", "2026-07-01")
        con = _scoped_source(root, codes, "parquet_data/step39-full/prioritized_recommendations.parquet",
                             report["candidates_prioritized"])
        try:
            counts = con.execute("""SELECT priority,COUNT(*) FROM source
                JOIN allowed_locations USING (restaurant_code) GROUP BY 1 ORDER BY 1""").fetchall()
            rows = con.execute("""SELECT priority,recommendation_type,restaurant_code,subject_code,
                recommended_action FROM source JOIN allowed_locations USING (restaurant_code)
                ORDER BY CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1
                    WHEN 'Medium' THEN 2 ELSE 3 END,impact_exposure DESC LIMIT 20""").fetchall()
        finally:
            con.close()
        return ["Only location-scoped candidates are included; network-only candidates are omitted to protect scope.",
                "Priority expresses review urgency, not expected savings. No action is executed."], [
            _section("Priority distribution", ("Priority", "Candidates"), counts),
            _section("Leading review candidates", ("Priority", "Type", "Location", "Subject", "Suggested review"), rows)]
    raise KeyError(slug)
