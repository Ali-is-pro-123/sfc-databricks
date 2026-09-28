"""Wastage dashboard conservation and role-scope tests."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import LocationAccess, Restaurant
from .wastage_dashboard import build_wastage_dashboard


class WastageDashboardDataTests(SimpleTestCase):
    def setUp(self):
        if not (settings.PROJECT_ROOT / "parquet_data/step23-accepted-full/wastage_by_item_location.parquet").is_file():
            self.skipTest("Verified wastage snapshot is not available")

    def test_full_network_reconciles(self):
        dashboard = build_wastage_dashboard([f"R{number:07d}" for number in range(1, 25)])
        self.assertEqual(dashboard["wasted_quantity"], 200208)
        self.assertAlmostEqual(dashboard["waste_cost"], 51287250.55, places=2)
        self.assertEqual(dashboard["scored_pairs"], 4296)
        self.assertEqual(dashboard["unscored_pairs"], 24)
        self.assertEqual(len(dashboard["trends"]), 6)

    def test_single_location_never_returns_another_location(self):
        dashboard = build_wastage_dashboard(["R0000001"])
        self.assertEqual(dashboard["location_count"], 1)
        self.assertLess(dashboard["wasted_quantity"], 200208)
        self.assertTrue(all(row["code"] == "R0000001" for row in dashboard["locations"]))
        self.assertTrue(all(row["restaurant_code"] == "R0000001" for row in dashboard["risk_pairs"]))
        self.assertEqual(dashboard["scored_pairs"] + dashboard["unscored_pairs"], 180)


class WastageDashboardAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.second = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="wastage-manager", role=User.Role.RESTAURANT_MANAGER)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.first)

    def test_manager_scope_is_not_query_string_controlled(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("wastage_dashboard"), {"location": self.second.code})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"]["location_count"], 1)
        self.assertNotContains(response, "R0000002")

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("wastage_dashboard")).status_code, 302)
