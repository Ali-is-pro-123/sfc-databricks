"""Scoped Spark/Python comparison dashboard checks."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .dual_dashboard import build_dual_dashboard
from .models import LocationAccess, Restaurant


class DualDashboardDataTests(SimpleTestCase):
    def setUp(self):
        if not (settings.PROJECT_ROOT / "processed_data/step14-full-verified/record_comparison.csv").is_file():
            self.skipTest("Verified paired records are not available")

    def test_full_network_reconciles_to_step_14(self):
        data = build_dual_dashboard([f"R{number:07d}" for number in range(1, 25)])
        self.assertEqual(data["rows"], 17180)
        self.assertEqual(data["matched"], 15239)
        self.assertEqual(data["disagreements"], 1941)
        self.assertAlmostEqual(data["agreement"], 88.701979, places=5)
        self.assertEqual(sum(row["rows"] for row in data["by_month"]), data["rows"])

    def test_location_and_table_filters_do_not_change_scope_summary(self):
        base = build_dual_dashboard(["R0000001"])
        filtered = build_dual_dashboard(["R0000001"], {
            "location": "R0000002", "month": "2026-06", "status": "mismatch", "sort": "difference"})
        self.assertEqual(filtered["rows"], base["rows"])
        self.assertEqual(filtered["agreement"], base["agreement"])
        self.assertEqual(filtered["selected_location"], "")
        self.assertTrue(all(row["restaurant_code"] == "R0000001" and
                            row["match_or_mismatch"] == "mismatch" for row in filtered["records"]))
        self.assertLessEqual(filtered["filtered_count"], base["rows"])


class DualDashboardAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.second = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="dual-manager", role=User.Role.RESTAURANT_MANAGER)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.first)

    def test_manager_cannot_expand_location_filter(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("dual_dashboard"), {"location": self.second.code})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"]["location_count"], 1)
        self.assertNotContains(response, "R0000002")

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("dual_dashboard")).status_code, 302)
