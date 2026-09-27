"""Bounded, read-only what-if calculations on verified analytical snapshots."""

import json
from decimal import Decimal
from pathlib import Path

import duckdb
from django.conf import settings


AS_OF = "2026-07-01"
SCENARIOS = {
    "price_increase": "Increase menu price",
    "price_decrease": "Reduce menu price",
    "discount_change": "Change discount percentage points",
    "promotion_frequency": "Increase promotion frequency",
    "remove_item": "Remove a menu item",
    "preparation_reduction": "Reduce preparation quantity",
    "forecast_demand_increase": "Increase predicted demand",
    "wastage_change": "Change wastage assumption",
}


class ScenarioError(ValueError):
    """The requested simulation lacks a safe baseline or valid assumption."""


def _decimal(value):
    if value is None:
        raise ScenarioError("A required baseline value is unavailable.")
    return Decimal(str(value))


def _percent(value, lower, upper, label):
    try:
        result = _decimal(value)
    except (ValueError, ArithmeticError) as error:
        raise ScenarioError(f"Enter a valid {label}.") from error
    if not result.is_finite() or not lower <= result <= upper:
        raise ScenarioError(f"{label.capitalize()} must be between {lower}% and {upper}%.")
    return result


def _metric(label, baseline, simulated, unit):
    return {"label": label, "baseline": baseline, "simulated": simulated,
            "change": simulated - baseline, "unit": unit}


def simulate(scenario, item, location, forecast, change_percent, demand_change_percent=0,
             horizon_months=1):
    """Return transparent estimates; never mutate source data or infer elasticity."""
    if scenario not in SCENARIOS:
        raise ScenarioError("Choose a supported scenario.")
    if scenario == "forecast_demand_increase":
        if horizon_months not in (1, 2, 3) or forecast is None:
            raise ScenarioError("A verified 1–3 month item/location forecast is required.")
        pct = _percent(change_percent, Decimal("0.1"), Decimal("100"), "demand increase")
        baseline = _decimal(forecast["forecast_quantity"])
        simulated = baseline * (1 + pct / 100)
        return {"scenario": SCENARIOS[scenario], "metrics": [
            _metric("Predicted demand", baseline, simulated, "portions")],
            "assumptions": [f"Forecast month: {forecast['target_month']}; method: {forecast['method']}.",
                            f"User-entered demand increase: {pct}% relative to the saved forecast."],
            "caveat": "This changes a forecast assumption, not observed demand. Forecast error and capacity constraints remain; no revenue is inferred.",
            "as_of": AS_OF}
    if scenario == "promotion_frequency":
        if location is None:
            raise ScenarioError("This location has no verified 90-day baseline.")
        pct = _percent(change_percent, Decimal("0.1"), Decimal("100"), "promotion-frequency increase")
        tagged = _decimal(location["tagged_promo_orders"])
        if tagged <= 0:
            raise ScenarioError("This location has no tagged campaign orders for a promotional baseline.")
        extra_orders = tagged * pct / 100
        promo_revenue = _decimal(location["promo_revenue"])
        promo_contribution = _decimal(location["promo_direct_contribution"])
        baseline_revenue = _decimal(location["revenue"])
        baseline_contribution = _decimal(location["contribution"])
        return {"scenario": SCENARIOS[scenario], "metrics": [
            _metric("Tagged promotion orders", tagged, tagged + extra_orders, "orders"),
            _metric("Location revenue", baseline_revenue,
                    baseline_revenue + extra_orders * promo_revenue / tagged, "PKR"),
            _metric("Location direct contribution", baseline_contribution,
                    baseline_contribution + extra_orders * promo_contribution / tagged, "PKR")],
            "assumptions": [f"User-entered additional tagged-order frequency: {pct}%.",
                            "Each extra tagged order has the observed 90-day average revenue and direct contribution."],
            "caveat": "Extra promotion orders are assumed incremental; cannibalization, campaign spend, discount changes and capacity are not modeled.",
            "as_of": AS_OF}
    if item is None:
        raise ScenarioError("Choose an item available at this location.")
    quantity = _decimal(item["quantity_sold"])
    revenue = _decimal(item["revenue"])
    cost = _decimal(item["cost"])
    contribution = revenue - cost
    waste = _decimal(item["wasted_quantity"])
    waste_cost = _decimal(item["waste_cost"])
    if scenario in ("price_increase", "price_decrease", "discount_change"):
        if quantity <= 0:
            raise ScenarioError("Price and discount scenarios require observed sold portions.")
        demand_pct = _percent(demand_change_percent, Decimal("-50"), Decimal("50"),
                              "assumed demand change")
        pct = _percent(change_percent, Decimal("-30") if scenario == "discount_change" else Decimal("0.1"),
                       Decimal("30"), "price/discount change")
        if scenario == "discount_change" and pct == 0:
            raise ScenarioError("Enter a nonzero discount change.")
        if scenario == "discount_change":
            new_discount = _decimal(item["discount_percentage"]) + pct
            if not Decimal(0) <= new_discount <= Decimal(60):
                raise ScenarioError("Assumed discount must stay between 0% and 60%.")
        latest_price = _decimal(item["latest_unit_price"])
        if latest_price <= 0:
            raise ScenarioError("No positive latest menu price is available.")
        signed_price_change = (-pct if scenario == "price_decrease" else pct)
        unit_adjustment = latest_price * signed_price_change / 100
        if scenario == "discount_change":
            unit_adjustment = -latest_price * pct / 100
        new_quantity = quantity * (1 + demand_pct / 100)
        new_net_unit = revenue / quantity + unit_adjustment
        if new_net_unit < 0:
            raise ScenarioError("The assumed discount would make estimated net unit revenue negative.")
        new_revenue = new_quantity * new_net_unit
        new_cost = new_quantity * cost / quantity
        return {"scenario": SCENARIOS[scenario], "metrics": [
            _metric("Sold portions", quantity, new_quantity, "portions"),
            _metric("Accepted revenue", revenue, new_revenue, "PKR"),
            _metric("Direct contribution", contribution, new_revenue - new_cost, "PKR")],
            "assumptions": [f"User-entered price/discount change: {pct}% (discount uses percentage points of latest list price).",
                            f"User-entered demand change: {demand_pct}%.",
                            "Historical average net unit revenue and direct cost per portion are the starting point."],
            "caveat": "Demand response is user supplied, not estimated elasticity. Taxes, platform fees, promotion interactions and fixed costs are excluded.",
            "as_of": AS_OF}
    if scenario == "remove_item":
        return {"scenario": SCENARIOS[scenario], "metrics": [
            _metric("Sold portions", quantity, Decimal(0), "portions"),
            _metric("Accepted revenue", revenue, Decimal(0), "PKR"),
            _metric("Direct contribution", contribution, Decimal(0), "PKR"),
            _metric("Recorded item waste", waste, Decimal(0), "portions")],
            "assumptions": ["No customer substitutes another menu item and all item-specific sales and recorded waste stop.",
                            "The 90-day historical baseline is repeated solely for comparison."],
            "caveat": "This is an extreme no-substitution scenario, not a recommendation to remove the item. Lost customers and fixed costs are unmodeled.",
            "as_of": AS_OF}
    if scenario == "preparation_reduction":
        pct = _percent(change_percent, Decimal("0.1"), Decimal("50"), "preparation reduction")
        prepared = _decimal(item["recorded_prepared_quantity"])
        if prepared <= 0 or waste <= 0:
            raise ScenarioError("Recorded preparation and waste are required for this scenario.")
        reduced = prepared * pct / 100
        if reduced > waste:
            raise ScenarioError("Reduction exceeds recorded waste; unchanged sales cannot be assumed.")
        estimated_waste_cost = waste_cost * (waste - reduced) / waste
        return {"scenario": SCENARIOS[scenario], "metrics": [
            _metric("Recorded prepared portions", prepared, prepared - reduced, "portions"),
            _metric("Recorded wasted portions", waste, waste - reduced, "portions"),
            _metric("Recorded waste cost", waste_cost, estimated_waste_cost, "PKR")],
            "assumptions": [f"User-entered reduction: {pct}% of recorded prepared portions.",
                            "Only recorded waste is reduced; accepted sales are held unchanged."],
            "caveat": "Preparation coverage and inventory gaps remain; reducing preparation may cause stockouts in practice.",
            "as_of": AS_OF}
    pct = _percent(change_percent, Decimal("-50"), Decimal("100"), "wastage change")
    if waste <= 0:
        raise ScenarioError("Recorded waste is required for a wastage-assumption scenario.")
    factor = 1 + pct / 100
    return {"scenario": SCENARIOS[scenario], "metrics": [
        _metric("Recorded wasted portions", waste, waste * factor, "portions"),
        _metric("Recorded waste cost", waste_cost, waste_cost * factor, "PKR")],
        "assumptions": [f"User-entered relative change in recorded waste: {pct}%.",
                        "Sold portions and waste cost per wasted portion stay constant."],
        "caveat": "The changed wastage rate is an assumption, not an observed outcome; inventory reconciliation and capacity are not modeled.",
        "as_of": AS_OF}


def analyze_impact(scenario, item, location, result):
    """Display modeled, held-constant and unavailable indicators separately."""
    if scenario not in SCENARIOS:
        raise ScenarioError("Choose a supported scenario.")
    measures = {metric["label"]: metric for metric in result["metrics"]}
    rows = []

    def add(label, baseline, simulated, unit, status, explanation):
        rows.append({"label": label, "baseline": baseline, "simulated": simulated,
                     "change": simulated - baseline if baseline is not None and simulated is not None else None,
                     "unit": unit, "status": status, "explanation": explanation})

    def from_step40(label, source_label, status="Estimated", explanation="Uses the explicit Step 40 assumption."):
        metric = measures[source_label]
        add(label, metric["baseline"], metric["simulated"], metric["unit"], status, explanation)

    if scenario == "forecast_demand_increase":
        from_step40("Demand (future forecast)", "Predicted demand", explanation="Saved forecast plus user-entered demand assumption; not observed sales.")
        for label, unit in (("Revenue", "PKR"), ("Direct contribution", "PKR"),
                            ("Recorded wastage", "portions"), ("Direct margin (not net profit)", "%")):
            add(label, None, None, unit, "Not estimated",
                "Future item price, unit cost, promotion mix and waste are not forecast here.")
        return {"basis": "Saved future item/location forecast, not a historical actual",
                "indicators": rows}

    if scenario == "promotion_frequency":
        from_step40("Demand (tagged orders)", "Tagged promotion orders",
                    explanation="Extra orders are assumed incremental at observed campaign-basket economics.")
        from_step40("Revenue", "Location revenue")
        from_step40("Direct contribution", "Location direct contribution")
        add("Recorded wastage", _decimal(location["wasted_quantity"]), None, "portions",
            "Not estimated", "Promotion-driven waste change is unknown; no causal waste model exists.")
        revenue = measures["Location revenue"]
        contribution = measures["Location direct contribution"]
    else:
        if item is None:
            raise ScenarioError("Item baseline is required for impact analysis.")
        quantity = _decimal(item["quantity_sold"])
        baseline_revenue = _decimal(item["revenue"])
        baseline_contribution = baseline_revenue - _decimal(item["cost"])
        baseline_waste = _decimal(item["wasted_quantity"])
        baseline_waste_cost = _decimal(item["waste_cost"])
        if scenario in ("price_increase", "price_decrease", "discount_change"):
            from_step40("Demand (sold portions)", "Sold portions")
            from_step40("Revenue", "Accepted revenue")
            from_step40("Direct contribution", "Direct contribution")
            add("Recorded wastage", baseline_waste, baseline_waste, "portions", "Held constant",
                "Price/discount simulation does not estimate a waste response.")
            simulated_waste_cost = baseline_waste_cost
        elif scenario == "remove_item":
            from_step40("Demand (sold portions)", "Sold portions")
            from_step40("Revenue", "Accepted revenue")
            from_step40("Direct contribution", "Direct contribution")
            from_step40("Recorded wastage", "Recorded item waste")
            simulated_waste_cost = Decimal(0)
        elif scenario == "preparation_reduction":
            add("Demand (sold portions)", quantity, quantity, "portions", "Held constant",
                "The requested preparation reduction is no greater than recorded waste.")
            add("Revenue", baseline_revenue, baseline_revenue, "PKR", "Held constant",
                "Accepted sales are assumed unchanged; stockouts are not modeled.")
            add("Direct contribution", baseline_contribution, baseline_contribution, "PKR",
                "Held constant", "Direct contribution excludes recorded waste cost.")
            from_step40("Recorded wastage", "Recorded wasted portions")
            simulated_waste_cost = measures["Recorded waste cost"]["simulated"]
        else:
            add("Demand (sold portions)", quantity, quantity, "portions", "Held constant",
                "Changing the waste assumption does not change accepted sales.")
            add("Revenue", baseline_revenue, baseline_revenue, "PKR", "Held constant",
                "Accepted sales are assumed unchanged.")
            add("Direct contribution", baseline_contribution, baseline_contribution, "PKR",
                "Held constant", "Direct contribution excludes recorded waste cost.")
            from_step40("Recorded wastage", "Recorded wasted portions")
            simulated_waste_cost = measures["Recorded waste cost"]["simulated"]
        revenue = next(row for row in rows if row["label"] == "Revenue")
        contribution = next(row for row in rows if row["label"] == "Direct contribution")
        add("Contribution after recorded waste (proxy)",
            baseline_contribution - baseline_waste_cost,
            contribution["simulated"] - simulated_waste_cost, "PKR", "Estimated proxy",
            "Subtracts accepted recorded waste cost from direct contribution; not accounting profit.")

    baseline_margin = (100 * contribution["baseline"] / revenue["baseline"]
                       if revenue["baseline"] > 0 else None)
    simulated_margin = (100 * contribution["simulated"] / revenue["simulated"]
                        if revenue["simulated"] > 0 else None)
    margin_status = ("Not estimated" if simulated_margin is None else
                     "Held constant" if scenario in ("preparation_reduction", "wastage_change")
                     else "Estimated")
    add("Direct margin (not net profit)", baseline_margin, simulated_margin, "%",
        margin_status,
        "Direct contribution divided by accepted revenue; undefined when simulated revenue is zero.")
    return {"basis": "Accepted 90-day historical baseline ending 2026-06-30",
            "indicators": rows}


def source_paths():
    root = settings.PROJECT_ROOT
    return {
        "performance": Path(getattr(settings, "SCENARIO_PERFORMANCE_PATH",
                                    root / "parquet_data" / "step09-full" / "item_location_performance")),
        "location": Path(getattr(settings, "SCENARIO_LOCATION_PATH",
                                 root / "parquet_data" / "step33-verified-full" / "location_intelligence.parquet")),
        "forecast": Path(getattr(settings, "SCENARIO_FORECAST_PATH",
                                 root / "parquet_data" / "step20-full" / "item_location_forecast.parquet")),
    }


def verified_sources(paths):
    root = settings.PROJECT_ROOT
    report_paths = ((root / "processed_data" / "step09-full" / "profitability_report.json",
                "as_of_exclusive_local_date", AS_OF),
               (root / "processed_data" / "step33-verified-full" / "location_intelligence_report.json",
                "as_of_exclusive", AS_OF),
               (root / "processed_data" / "step20-full" / "forecast_report.json",
                "origin", AS_OF))
    reports = []
    for path, field, expected in report_paths:
        if not path.is_file():
            raise ScenarioError(f"Missing verified source report: {path.name}.")
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("status") != "passed" or report.get(field) != expected:
            raise ScenarioError(f"Verified source cutoff or status differs: {path.name}.")
        reports.append(report)
    if not paths["performance"].is_dir() or not (paths["performance"] / "_SUCCESS").is_file():
        raise ScenarioError("Verified item performance is unavailable.")
    if not paths["location"].is_file() or not paths["forecast"].is_file():
        raise ScenarioError("Verified location or forecast data is unavailable.")
    if reports[0].get("window_days") != 90 or reports[1].get("window_days") != 90:
        raise ScenarioError("Source analysis windows differ.")
    con = duckdb.connect()
    try:
        expected = (reports[0]["outputs"]["item_location_performance"]["rows"],
                    reports[1]["output"]["rows"], reports[2]["forecast_rows"])
        patterns = (str(paths["performance"].as_posix()) + "/**/*.parquet",
                    str(paths["location"]), str(paths["forecast"]))
        actual = tuple(con.execute("SELECT COUNT(*) FROM read_parquet(?)", [pattern]).fetchone()[0]
                       for pattern in patterns)
        if actual != expected:
            raise ScenarioError("Verified source row counts differ from their reports.")
    finally:
        con.close()


def load_location_context(restaurant_code, item_code=None, horizon_months=1):
    """Read one authorized location's baselines; authorization stays in the view."""
    paths = source_paths()
    verified_sources(paths)
    con = duckdb.connect()
    try:
        pattern = str(paths["performance"].as_posix()) + "/**/*.parquet"
        choices = con.execute("""SELECT item_code,item_name FROM read_parquet(?)
            WHERE restaurant_code=? ORDER BY item_name,item_code""",
            [pattern, restaurant_code]).fetchall()
        location_cursor = con.execute("""SELECT * FROM read_parquet(?) WHERE restaurant_code=?""",
                                      [str(paths["location"]), restaurant_code])
        location_names = [column[0] for column in location_cursor.description]
        location_values = location_cursor.fetchone()
        location = dict(zip(location_names, location_values)) if location_values else None
        item = None
        forecast = None
        if item_code:
            item_cursor = con.execute("""SELECT * FROM read_parquet(?)
                WHERE restaurant_code=? AND item_code=?""", [pattern, restaurant_code, item_code])
            item_names = [column[0] for column in item_cursor.description]
            item_values = item_cursor.fetchone()
            item = dict(zip(item_names, item_values)) if item_values else None
            forecast_cursor = con.execute("""SELECT * FROM read_parquet(?)
                WHERE restaurant_code=? AND item_code=? AND horizon_months=?""",
                [str(paths["forecast"]), restaurant_code, item_code, horizon_months])
            forecast_names = [column[0] for column in forecast_cursor.description]
            forecast_values = forecast_cursor.fetchone()
            forecast = dict(zip(forecast_names, forecast_values)) if forecast_values else None
        return {"choices": choices, "location": location, "item": item,
                "forecast": forecast}
    finally:
        con.close()
