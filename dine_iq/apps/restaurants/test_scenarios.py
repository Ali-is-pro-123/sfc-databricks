"""What-if calculations remain bounded, explicit and read-only."""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import LocationAccess, Restaurant
from .scenarios import ScenarioError, analyze_impact, simulate


class ScenarioCalculationTests(TestCase):
    def setUp(self):
        self.item = {"quantity_sold": 100, "revenue": Decimal("1000"),
                     "cost": Decimal("600"), "latest_unit_price": Decimal("10"),
                     "wasted_quantity": Decimal("20"), "waste_cost": Decimal("100"),
                     "recorded_prepared_quantity": Decimal("120"),
                     "discount_percentage": Decimal("0")}
        self.location = {"tagged_promo_orders": 10, "promo_revenue": Decimal("500"),
                         "promo_direct_contribution": Decimal("100"),
                         "revenue": Decimal("5000"), "contribution": Decimal("2000"),
                         "wasted_quantity": Decimal("25")}
        self.forecast = {"forecast_quantity": 120, "target_month": "2026-07-01",
                         "method": "validated model"}

    def run_scenario(self, name, change, demand=0):
        return simulate(name, self.item, self.location, self.forecast, change, demand)

    def test_all_eight_scenarios(self):
        cases = {
            "price_increase": (10, Decimal("1100")),
            "price_decrease": (10, Decimal("900")),
            "discount_change": (5, Decimal("950")),
            "promotion_frequency": (20, Decimal("12")),
            "remove_item": (0, Decimal("0")),
            "preparation_reduction": (10, Decimal("108")),
            "forecast_demand_increase": (25, Decimal("150")),
            "wastage_change": (50, Decimal("30")),
        }
        metric_index = {"price_increase": 1, "price_decrease": 1,
                        "discount_change": 1, "promotion_frequency": 0,
                        "remove_item": 0, "preparation_reduction": 0,
                        "forecast_demand_increase": 0, "wastage_change": 0}
        for name, (change, expected) in cases.items():
            with self.subTest(name=name):
                result = self.run_scenario(name, change)
                self.assertEqual(result["metrics"][metric_index[name]]["simulated"], expected)
                self.assertTrue(result["assumptions"] and result["caveat"])

    def test_demand_response_is_an_assumption_and_bounds_are_enforced(self):
        result = self.run_scenario("price_increase", 10, -10)
        self.assertEqual(result["metrics"][0]["simulated"], Decimal("90"))
        with self.assertRaises(ScenarioError):
            self.run_scenario("price_increase", 40)
        with self.assertRaises(ScenarioError):
            self.run_scenario("preparation_reduction", 50)
        with self.assertRaises(ScenarioError):
            self.run_scenario("discount_change", -5)
        with self.assertRaises(ScenarioError):
            simulate("forecast_demand_increase", self.item, self.location, None, 10, horizon_months=4)

    def test_impact_covers_indicators_without_inventing_future_money(self):
        for name in ("price_increase", "price_decrease", "discount_change",
                     "promotion_frequency", "remove_item", "preparation_reduction",
                     "forecast_demand_increase", "wastage_change"):
            with self.subTest(name=name):
                result = self.run_scenario(name, 0 if name == "remove_item" else 10)
                impact = analyze_impact(name, self.item, self.location, result)
                labels = {row["label"] for row in impact["indicators"]}
                self.assertTrue(any(label.startswith("Demand") for label in labels))
                self.assertIn("Revenue", labels)
                self.assertIn("Direct contribution", labels)
                self.assertIn("Recorded wastage", labels)
                self.assertIn("Direct margin (not net profit)", labels)
                if name == "forecast_demand_increase":
                    self.assertIsNone(next(row for row in impact["indicators"]
                                           if row["label"] == "Revenue")["simulated"])

    def test_waste_reduction_changes_proxy_not_direct_contribution(self):
        result = self.run_scenario("preparation_reduction", 10)
        impact = analyze_impact("preparation_reduction", self.item, self.location, result)
        by_label = {row["label"]: row for row in impact["indicators"]}
        self.assertEqual(by_label["Direct contribution"]["change"], Decimal(0))
        self.assertEqual(by_label["Contribution after recorded waste (proxy)"]["change"], Decimal("60"))

    def test_removed_item_has_undefined_simulated_margin(self):
        result = self.run_scenario("remove_item", 0)
        impact = analyze_impact("remove_item", self.item, self.location, result)
        margin = next(row for row in impact["indicators"]
                      if row["label"] == "Direct margin (not net profit)")
        self.assertIsNone(margin["simulated"])
        self.assertEqual(margin["status"], "Not estimated")


class ScenarioAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Restaurant.objects.create(code="R1", name="Central", city="Karachi")
        cls.b = Restaurant.objects.create(code="R2", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="manager-scenario", role=User.Role.RESTAURANT_MANAGER)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.a)

    def test_ungranted_location_cannot_be_simulated(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("restaurants:scenarios"),
                                   {"restaurant_code": "R2", "scenario": "price_increase", "run": "1"})
        self.assertEqual(response.status_code, 404)

    def test_estimate_page_labels_unavailable_future_impact(self):
        self.client.force_login(self.manager)
        forecast = {"forecast_quantity": 120, "target_month": "2026-07-01",
                    "method": "validated model"}
        context = {"choices": [("I1", "Rice Bowl")], "location": None,
                   "item": {"quantity_sold": 100, "revenue": Decimal("1000"),
                            "cost": Decimal("600"), "wasted_quantity": Decimal("10"),
                            "waste_cost": Decimal("50")}, "forecast": forecast}
        with patch("apps.restaurants.views.load_location_context", return_value=context):
            response = self.client.get(reverse("restaurants:scenarios"), {
                "restaurant_code": "R1", "item_code": "I1", "scenario": "forecast_demand_increase",
                "change_percent": "10", "horizon_months": "1", "run": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Simulated estimate")
        self.assertContains(response, "Not estimated")
        self.assertContains(response, "Direct margin (not net profit)")
