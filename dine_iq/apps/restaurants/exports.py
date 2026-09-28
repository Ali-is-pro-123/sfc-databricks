"""Excel-compatible CSV exports built from the same scoped dashboard services."""

import csv
from datetime import date, datetime

from django.http import HttpResponse

from .customer_dashboard import build_customer_dashboard
from .dashboard_data import DashboardUnavailable
from .dual_dashboard import build_dual_dashboard
from .forecast_dashboard import build_forecast_dashboard
from .menu_dashboard import build_menu_dashboard
from .search_dashboard import build_search_dashboard
from .wastage_dashboard import build_wastage_dashboard


EXPORTS = {
    "menu": "Filtered menu item/location evidence",
    "search": "Filtered accepted-sales item/location results",
    "dual": "Filtered Spark/Python paired predictions",
    "customers": "Customer segment and RFM distribution",
    "forecast": "Historical and future demand",
    "wastage": "Wastage item, location and monthly summaries",
}


def spreadsheet_safe(value):
    """Prevent imported text from becoming an Excel or LibreOffice formula."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def build_export(dataset, allowed_codes, filters=None):
    """Return a bounded-schema CSV with every selected row, not a UI page."""
    codes = sorted(set(allowed_codes))
    if not codes:
        raise DashboardUnavailable("No accessible locations")
    filters = filters or {}
    if dataset == "menu":
        data = build_menu_dashboard(codes, filters)
        if data["empty"]:
            raise DashboardUnavailable("No scoped menu evidence")
        headers = ("location_code", "location_name", "item_code", "item_name", "category_code",
                   "performance_class", "movement_class", "sold_quantity", "revenue_pkr",
                   "direct_contribution_pkr", "direct_margin_percent", "rating_count",
                   "average_rating", "wasted_quantity", "waste_share_percent",
                   "window_start", "window_end")
        rows = [(r["restaurant_code"], r["restaurant_name"], r["item_code"], r["item_name"],
                 r["category_code"], r["location_menu_class"], r["movement_class"],
                 r["quantity_sold"], r["revenue"], r["contribution"],
                 r["direct_margin_percentage"], r["rating_count"], r["average_rating"],
                 r["wasted_quantity"], r["accounted_wastage_percentage"],
                 "2026-04-02", "2026-06-30") for r in data["items"]]
    elif dataset == "search":
        data = build_search_dashboard(codes, filters, result_limit=None)
        if data["empty"]:
            raise DashboardUnavailable("No scoped search evidence")
        headers = ("location_code", "item_code", "item_name", "category_name",
                   "performance_class_90_day", "accepted_lines", "sold_quantity",
                   "revenue_pkr", "observed_rating", "rating_count",
                   "pair_wasted_quantity_90_day", "sales_date_from", "sales_date_through")
        rows = [(r["restaurant_code"], r["item_code"], r["item_name"], r["category_name"],
                 r["performance_class"], r["lines"], r["quantity"], r["revenue"],
                 r["observed_rating"], r["rating_count"], r["pair_waste_90"],
                 data["start"], data["end"]) for r in data["results"]]
    elif dataset == "dual":
        data = build_dual_dashboard(codes, filters, export_all=True)
        if data["empty"]:
            raise DashboardUnavailable("No scoped paired predictions")
        headers = ("location_code", "item_code", "target_month", "actual_portions",
                   "spark_prediction", "python_prediction", "python_minus_spark",
                   "absolute_difference", "agreement_tolerance", "match_status",
                   "diagnostic_code", "spark_absolute_error", "python_absolute_error")
        rows = [(r["restaurant_code"], r["item_code"], r["cutoff"], r["actual_value"],
                 r["spark_result"], r["python_result"], r["numerical_difference_python_minus_spark"],
                 r["absolute_difference"], r["agreement_tolerance"], r["match_or_mismatch"],
                 r["disagreement_code"], r["spark_absolute_error"], r["python_absolute_error"])
                for r in data["records"]]
    elif dataset == "customers":
        data = build_customer_dashboard(codes)
        if data["empty"]:
            raise DashboardUnavailable("No scoped customer evidence")
        headers = ("distribution", "label", "customer_count", "population_count",
                   "location_count", "as_of_exclusive", "scope")
        scope = "network" if data["full_network"] else "accessible_visit_cohort"
        rows = [(kind, label, count, data["population"], data["location_count"],
                 "2026-07-01", scope)
                for kind, distribution in (("segment", data["segment_rows"]),
                                           ("rfm_tier", data["tier_rows"]))
                for label, count in distribution]
    elif dataset == "forecast":
        data = build_forecast_dashboard(codes)
        if data["empty"]:
            raise DashboardUnavailable("No scoped forecast evidence")
        headers = ("month", "record_type", "actual_sold_portions", "forecast_portions",
                   "planning_review", "location_count", "origin")
        rows = [(r["month"], "historical_actual", r["quantity"], "", "",
                 data["location_count"], "2026-07-01") for r in data["history"]]
        rows += [(r["month"], "future_forecast", "", r["quantity"],
                  "yes" if r["planning_review"] else "no", data["location_count"],
                  "2026-07-01") for r in data["future"]]
    elif dataset == "wastage":
        data = build_wastage_dashboard(codes)
        if data["empty"]:
            raise DashboardUnavailable("No scoped wastage evidence")
        headers = ("record_type", "code_or_month", "wasted_quantity", "waste_cost_pkr",
                   "location_count", "historical_cutoff")
        rows = [("item", r["code"], r["quantity"], r["cost"], data["location_count"],
                 "2026-07-01") for r in data["items"]]
        rows += [("location", r["code"], r["quantity"], r["cost"], data["location_count"],
                  "2026-07-01") for r in data["locations"]]
        rows += [("month", r["month"], r["quantity"], r["cost"], data["location_count"],
                  "2026-07-01") for r in data["trends"]]
    else:
        raise KeyError(dataset)
    return headers, rows


def csv_response(dataset, headers, rows):
    """Write a UTF-8 BOM so common Windows spreadsheet tools detect Unicode."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="dineiq-{dataset}-2026-06-30.csv"'
    response["Cache-Control"] = "private, no-store"
    response.write("\ufeff")
    writer = csv.writer(response, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([spreadsheet_safe(value) for value in row])
    return response
