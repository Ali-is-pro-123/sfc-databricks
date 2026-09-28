from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from pathlib import Path
from urllib.parse import urlencode

from .access import visible_restaurants
from .dashboard_data import DashboardUnavailable, build_executive_dashboard
from .customer_dashboard import build_customer_dashboard
from .wastage_dashboard import build_wastage_dashboard
from .forecast_dashboard import build_forecast_dashboard
from .dual_dashboard import build_dual_dashboard
from .search_dashboard import build_search_dashboard
from .reports import REPORTS, build_report
from .exports import EXPORTS, build_export, csv_response
from .menu_dashboard import build_menu_dashboard
from .models import PricingHistory
from .scenarios import SCENARIOS, ScenarioError, analyze_impact, load_location_context, simulate


@login_required
def executive_dashboard(request):
    """Summarize only verified analytics for restaurants visible to this user."""
    from apps.accounts.models import User

    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    global_access = request.user.is_superuser or request.user.role in (
        User.Role.ADMINISTRATOR, User.Role.ANALYST)
    try:
        dashboard = build_executive_dashboard(allowed_codes, global_access)
    except DashboardUnavailable:
        return render(request, "restaurants/executive_dashboard.html",
                      {"unavailable": True}, status=503)
    return render(request, "restaurants/executive_dashboard.html", {"dashboard": dashboard})


@login_required
def download_csv(request, dataset):
    """Export selected analytical rows using the same role and filter boundaries."""
    if dataset not in EXPORTS:
        raise Http404("Unknown export")
    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    if not allowed_codes:
        return HttpResponseForbidden("No locations are available for export")
    filters = {key: request.GET.get(key, "") for key in request.GET}
    try:
        headers, rows = build_export(dataset, allowed_codes, filters)
    except DashboardUnavailable:
        return HttpResponse("Verified export source is unavailable", status=503)
    return csv_response(dataset, headers, rows)


@login_required
def report_center(request):
    """List the available verified, location-scoped report families."""
    return render(request, "restaurants/report_center.html", {"reports": REPORTS.items()})


@login_required
def download_report(request, slug):
    """Generate an offline HTML report without exposing source files or other locations."""
    if slug not in REPORTS:
        raise Http404("Unknown report")
    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    try:
        report = build_report(slug, allowed_codes)
    except DashboardUnavailable:
        return render(request, "restaurants/report_center.html", {
            "reports": REPORTS.items(), "unavailable": True}, status=503)
    html = render_to_string("restaurants/report_document.html", {"report": report})
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="dineiq-{slug}-2026-06-30.html"'
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return response


@login_required
def analytics_search(request):
    """Search verified accepted sales without trusting a requested location scope."""
    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    filters = {name: request.GET.get(name, "") for name in (
        "start", "end", "location", "item", "category", "segment", "channel",
        "promotion", "class", "min_price", "max_price", "min_rating",
        "min_waste", "max_waste")}
    try:
        dashboard = build_search_dashboard(allowed_codes, filters)
    except DashboardUnavailable:
        return render(request, "restaurants/search_dashboard.html", {"unavailable": True}, status=503)
    return render(request, "restaurants/search_dashboard.html", {
        "dashboard": dashboard, "export_query": request.GET.urlencode()})


@login_required
def dual_pipeline_dashboard(request):
    """Expose paired held-out predictions without widening location access."""
    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    filters = {name: request.GET.get(name, "") for name in
               ("location", "month", "status", "q", "sort", "page")}
    try:
        dashboard = build_dual_dashboard(allowed_codes, filters)
    except DashboardUnavailable:
        return render(request, "restaurants/dual_dashboard.html", {"unavailable": True}, status=503)
    if dashboard["empty"]:
        return render(request, "restaurants/dual_dashboard.html", {"dashboard": dashboard})
    filter_query = urlencode({key: value for key, value in {
        "location": dashboard["selected_location"], "month": dashboard["selected_month"],
        "status": dashboard["selected_status"], "q": dashboard["query"],
        "sort": dashboard["sort"],
    }.items() if value})
    return render(request, "restaurants/dual_dashboard.html", {
        "dashboard": dashboard, "filter_query": filter_query})


@login_required
def forecast_intelligence_dashboard(request):
    """Compare accepted demand with future forecasts in the user's scope."""
    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    try:
        dashboard = build_forecast_dashboard(allowed_codes)
    except DashboardUnavailable:
        return render(request, "restaurants/forecast_dashboard.html", {"unavailable": True}, status=503)
    return render(request, "restaurants/forecast_dashboard.html", {"dashboard": dashboard})


@login_required
def wastage_intelligence_dashboard(request):
    """Show accepted wastage and separately marked exploratory July risk."""
    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    try:
        dashboard = build_wastage_dashboard(allowed_codes)
    except DashboardUnavailable:
        return render(request, "restaurants/wastage_dashboard.html", {"unavailable": True}, status=503)
    return render(request, "restaurants/wastage_dashboard.html", {"dashboard": dashboard})


@login_required
def customer_intelligence_dashboard(request):
    """Show customer cohorts without exposing other locations' behavior."""
    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    try:
        dashboard = build_customer_dashboard(allowed_codes)
    except DashboardUnavailable:
        return render(request, "restaurants/customer_dashboard.html", {"unavailable": True}, status=503)
    return render(request, "restaurants/customer_dashboard.html", {"dashboard": dashboard})


@login_required
def menu_intelligence_dashboard(request):
    """Expose local menu evidence only for restaurants visible to the user."""
    allowed_codes = list(visible_restaurants(request.user).values_list("code", flat=True))
    filters = {name: request.GET.get(name, "") for name in
               ("location", "class", "category", "movement", "q", "sort")}
    try:
        dashboard = build_menu_dashboard(allowed_codes, filters)
    except DashboardUnavailable:
        return render(request, "restaurants/menu_dashboard.html", {"unavailable": True}, status=503)
    if dashboard["empty"]:
        return render(request, "restaurants/menu_dashboard.html", {"dashboard": dashboard})
    filter_query = urlencode({key: value for key, value in {
        "location": dashboard["selected_location"],
        "class": dashboard["selected_class"],
        "category": dashboard["selected_category"],
        "movement": dashboard["selected_movement"],
        "q": dashboard["query"],
        "sort": dashboard["sort"],
    }.items() if value})
    return render(request, "restaurants/menu_dashboard.html", {
        "dashboard": dashboard,
        "page_obj": Paginator(dashboard["items"], 25).get_page(request.GET.get("page")),
        "filter_query": filter_query,
    })


@login_required
def what_if_scenarios(request):
    """Run bounded read-only simulations for locations the user can access."""
    locations = list(visible_restaurants(request.user).order_by("name", "pk"))
    codes = {location.code for location in locations}
    restaurant_code = request.GET.get("restaurant_code") or (locations[0].code if locations else "")
    if restaurant_code and restaurant_code not in codes:
        raise Http404("Location not available")
    selected_scenario = request.GET.get("scenario", "price_increase")
    item_code = request.GET.get("item_code", "")
    change_percent = request.GET.get("change_percent", "10")
    demand_change_percent = request.GET.get("demand_change_percent", "0")
    try:
        horizon_months = int(request.GET.get("horizon_months", "1"))
    except ValueError:
        horizon_months = 0
    result = None
    error = None
    context = {"choices": [], "location": None, "item": None, "forecast": None}
    if restaurant_code:
        try:
            context = load_location_context(restaurant_code, item_code or None, horizon_months)
            if request.GET.get("run") == "1":
                if selected_scenario not in SCENARIOS:
                    raise ScenarioError("Choose a supported scenario.")
                if selected_scenario != "promotion_frequency" and not context["item"]:
                    raise ScenarioError("Choose an item available at this location.")
                result = simulate(selected_scenario, context["item"], context["location"],
                                  context["forecast"], change_percent, demand_change_percent,
                                  horizon_months)
                result["impact"] = analyze_impact(selected_scenario, context["item"],
                                                  context["location"], result)
        except ScenarioError as problem:
            error = str(problem)
    return render(request, "restaurants/scenarios.html", {
        "locations": locations, "restaurant_code": restaurant_code,
        "scenarios": SCENARIOS, "selected_scenario": selected_scenario,
        "item_code": item_code, "change_percent": change_percent,
        "demand_change_percent": demand_change_percent,
        "horizon_months": horizon_months, "choices": context["choices"],
        "result": result, "error": error,
    })


@login_required
def recommendation_evidence(request):
    """Show only recommendations the signed-in user is allowed to inspect."""
    import json
    import duckdb

    from apps.accounts.models import User

    evidence_path = Path(getattr(settings, "RECOMMENDATION_PRIORITY_PATH",
                                 settings.PROJECT_ROOT / "parquet_data" / "step39-full" /
                                 "prioritized_recommendations.parquet"))
    if not evidence_path.is_file():
        return render(request, "restaurants/recommendations.html", {
            "unavailable": True, "page_obj": Paginator([], 20).get_page(1),
            "types": [], "priorities": [],
        }, status=503)
    global_access = request.user.is_superuser or request.user.role in (
        User.Role.ADMINISTRATOR, User.Role.ANALYST)
    allowed_locations = set(visible_restaurants(request.user).values_list("code", flat=True))
    con = duckdb.connect()
    try:
        cursor = con.execute("""SELECT candidate_id,recommendation_type,scope,
            restaurant_code,subject_code,related_code,recommended_action,
            reason_lines_json,limitation,source_steps,as_of_exclusive,
            priority,impact_exposure,impact_unit,impact_basis,priority_reason
            FROM read_parquet(?) ORDER BY
              CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2
                            WHEN 'Medium' THEN 3 ELSE 4 END,
              impact_exposure DESC,recommendation_type,restaurant_code,subject_code""",
            [str(evidence_path)])
        names = [column[0] for column in cursor.description]
        visible = []
        for values in cursor.fetchall():
            row = dict(zip(names, values))
            if row["restaurant_code"] not in allowed_locations and not (
                    global_access and row["restaurant_code"] is None):
                continue
            row["reason_lines"] = json.loads(row.pop("reason_lines_json"))
            visible.append(row)
    finally:
        con.close()
    types = sorted({row["recommendation_type"] for row in visible})
    priorities = [name for name in ("Critical", "High", "Medium", "Low")
                  if any(row["priority"] == name for row in visible)]
    selected_type = request.GET.get("type", "")
    selected_priority = request.GET.get("priority", "")
    if selected_type in types:
        visible = [row for row in visible if row["recommendation_type"] == selected_type]
    else:
        selected_type = ""
    if selected_priority in priorities:
        visible = [row for row in visible if row["priority"] == selected_priority]
    else:
        selected_priority = ""
    return render(request, "restaurants/recommendations.html", {
        "page_obj": Paginator(visible, 20).get_page(request.GET.get("page")),
        "types": types, "selected_type": selected_type,
        "priorities": priorities, "selected_priority": selected_priority,
    })


@login_required
def location_list(request):
    locations = visible_restaurants(request.user).order_by("name", "pk")
    return render(request, "restaurants/list.html", {
        "page_obj": Paginator(locations, 25).get_page(request.GET.get("page")),
    })


@login_required
def location_detail(request, pk):
    location = get_object_or_404(visible_restaurants(request.user), pk=pk)
    # Select only the last effective price for each item, never future prices.
    prices = PricingHistory.objects.filter(restaurant=location, effective_at__lte=timezone.now())
    latest = prices.filter(item_id=OuterRef("item_id")).order_by("-effective_at").values("pk")[:1]
    current = prices.filter(pk=Subquery(latest)).select_related("item", "item__category").order_by("item__name", "pk")
    return render(request, "restaurants/detail.html", {
        "location": location,
        "page_obj": Paginator(current, 25).get_page(request.GET.get("page")),
    })
