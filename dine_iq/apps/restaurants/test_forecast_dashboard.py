"""Forecast dashboard lineage, population, and role-scope checks."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .forecast_dashboard import build_forecast_dashboard
from .models import LocationAccess, Restaurant


class ForecastDashboardDataTests(SimpleTestCase):
    def setUp(self):
        if not (settings.PROJECT_ROOT / "parquet_data/step20-full/item_location_forecast.parquet").is_file():
            self.skipTest("Verified forecast snapshot is not available")

    def test_full_network_forecast_and_backtest_reconcile(self):
        data = build_forecast_dashboard([f"R{number:07d}" for number in range(1, 25)])
        self.assertTrue(data["full_network"])
        self.assertEqual(len(data["history"]), 6)
        self.assertEqual(len(data["future"]), 3)
        self.assertEqual(len(data["backtest"]), 4)
        self.assertEqual(len(data["errors"]), 3)
        self.assertAlmostEqual(data["future"][0]["quantity"], 133225.3178, places=2)
        self.assertEqual(data["backtest"][-1]["actual"], 142995)
        self.assertEqual(data["history"][-1]["quantity"], 143687)
        self.assertTrue(data["backtest"][-1]["review"])

    def test_location_scope_suppresses_network_backtest(self):
        data = build_forecast_dashboard(["R0000001"])
        self.assertFalse(data["full_network"])
        self.assertEqual(data["location_count"], 1)
        self.assertEqual(data["future"][0]["pairs"], 180)
        self.assertEqual(data["backtest"], [])
        self.assertEqual(data["errors"], [])


class ForecastDashboardAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.second = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="forecast-manager", role=User.Role.RESTAURANT_MANAGER)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.first)

    def test_manager_cannot_request_other_location(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("forecast_dashboard"), {"location": self.second.code})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"]["location_count"], 1)
        self.assertNotContains(response, "Historical actual versus predicted")

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("forecast_dashboard")).status_code, 302)
