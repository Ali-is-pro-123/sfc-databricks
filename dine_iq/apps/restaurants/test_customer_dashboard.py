"""Customer dashboard reconciliation and location-boundary checks."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .customer_dashboard import build_customer_dashboard
from .models import LocationAccess, Restaurant


class CustomerDashboardDataTests(SimpleTestCase):
    def setUp(self):
        if not (settings.PROJECT_ROOT / "parquet_data/step15-full/customer_segments.parquet").is_file():
            self.skipTest("Verified customer snapshot is not available")

    def test_full_network_reconciles_to_published_reports(self):
        data = build_customer_dashboard([f"R{number:07d}" for number in range(1, 25)])
        self.assertTrue(data["full_network"])
        self.assertEqual(data["population"], 60000)
        self.assertEqual(data["eligible_visits"], 330045)
        self.assertEqual(data["high_value"], 806)
        self.assertEqual(data["high_review"], 21391)
        self.assertEqual(sum(count for _, count in data["segment_rows"]), 60000)
        self.assertEqual(sum(count for _, count in data["tier_rows"]), 60000)

    def test_single_location_is_recomputed_without_network_labels(self):
        data = build_customer_dashboard(["R0000001"])
        self.assertFalse(data["full_network"])
        self.assertIsNone(data["high_review"])
        self.assertLess(data["population"], 60000)
        self.assertEqual(sum(count for _, count in data["segment_rows"]), data["population"])
        self.assertEqual(sum(count for _, count in data["tier_rows"]), data["population"])
        self.assertNotIn("No Purchase Yet", [name for name, _ in data["segment_rows"]])


class CustomerDashboardAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.second = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="customer-manager", role=User.Role.RESTAURANT_MANAGER)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.first)

    def test_manager_cannot_expand_scope_with_query_string(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("customer_dashboard"), {"location": self.second.code})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["dashboard"]["full_network"])
        self.assertEqual(response.context["dashboard"]["location_count"], 1)
        self.assertNotContains(response, "Step 36 high review-priority signal")

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("customer_dashboard")).status_code, 302)
