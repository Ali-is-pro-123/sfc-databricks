"""Executive KPIs reconcile and never bypass location grants."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .dashboard_data import build_executive_dashboard
from .templatetags.analytics_display import compact_number
from .models import LocationAccess, Restaurant


class ExecutiveDashboardDataTests(SimpleTestCase):
    def setUp(self):
        source = settings.PROJECT_ROOT / "parquet_data" / "step33-verified-full" / "location_intelligence.parquet"
        if not source.is_file():
            self.skipTest("Verified full analytical data is not available")

    def test_full_totals_and_unique_customers(self):
        codes = [f"R{number:07d}" for number in range(1, 25)]
        data = build_executive_dashboard(codes, global_access=True)
        self.assertEqual(data["location_count"], 24)
        self.assertEqual(str(data["revenue"]), "125910828.14")
        self.assertEqual(data["completed_orders"], 73982)
        self.assertEqual(sum(row["orders"] for row in data["weekly_trend"]), data["completed_orders"])
        self.assertEqual(sum(row["revenue"] for row in data["weekly_trend"]), data["revenue"])
        self.assertLessEqual(data["repeat_customers"], data["active_customers"])
        self.assertGreater(data["forecast_demand"], 0)
        self.assertEqual(data["critical_recommendations"], 0)

    def test_scoped_locations_reconcile_without_other_revenue(self):
        one = build_executive_dashboard(["R0000001"])
        two = build_executive_dashboard(["R0000002"])
        combined = build_executive_dashboard(["R0000001", "R0000002"])
        self.assertEqual(combined["revenue"], one["revenue"] + two["revenue"])
        self.assertEqual(combined["completed_orders"], one["completed_orders"] + two["completed_orders"])
        self.assertLessEqual(combined["active_customers"], one["active_customers"] + two["active_customers"])
        self.assertEqual({row["code"] for row in combined["locations"]}, {"R0000001", "R0000002"})

    def test_compact_dashboard_numbers(self):
        self.assertEqual(compact_number("125910828.14"), "125.9M")
        self.assertEqual(compact_number(73982), "74.0K")
        self.assertEqual(compact_number(None), "—")


class ExecutiveDashboardAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.b = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="manager-dashboard", role=User.Role.RESTAURANT_MANAGER)
        cls.analyst = User.objects.create_user(username="analyst-dashboard", role=User.Role.ANALYST)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.a)

    def test_manager_sees_only_granted_location(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("executive_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "R0000001")
        self.assertNotContains(response, "R0000002")
        self.assertContains(response, "not net accounting profit")

    def test_analyst_sees_both_locations(self):
        self.client.force_login(self.analyst)
        response = self.client.get(reverse("executive_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "R0000001")
        self.assertContains(response, "R0000002")

    def test_login_is_required(self):
        response = self.client.get(reverse("executive_dashboard"))
        self.assertEqual(response.status_code, 302)
