"""Cross-filter and location-boundary tests for the analytics explorer."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import LocationAccess, Restaurant
from .search_dashboard import build_search_dashboard


class SearchDashboardDataTests(SimpleTestCase):
    def setUp(self):
        if not (settings.PROJECT_ROOT / "parquet_data/step34-full/location_menu_items.parquet").is_file():
            self.skipTest("Verified menu snapshot is not available")

    def test_full_history_line_count_reconciles(self):
        data = build_search_dashboard([f"R{number:07d}" for number in range(1, 25)],
                                      {"start": "2025-01-01", "end": "2026-06-30"})
        self.assertTrue(data["full_network"])
        self.assertEqual(data["line_count"], 988946)
        self.assertEqual(data["location_count"], 24)

    def test_combined_filters_narrow_without_expanding_scope(self):
        base = build_search_dashboard(["R0000001"])
        filtered = build_search_dashboard(["R0000001"], {
            "location": "R0000002", "category": base["category_options"][0][0],
            "channel": base["channel_options"][0][0], "promotion": "any",
            "min_price": "500", "min_rating": "4", "min_waste": "1"})
        self.assertFalse(filtered["full_network"])
        self.assertEqual(filtered["location"], "")
        self.assertEqual(filtered["location_count"], 1)
        self.assertLessEqual(filtered["line_count"], base["line_count"])
        self.assertTrue(all(row["restaurant_code"] == "R0000001" for row in filtered["results"]))
        self.assertNotIn("No Purchase Yet", filtered["segment_options"])

    def test_invalid_dates_reset_to_bounded_default(self):
        data = build_search_dashboard(["R0000001"], {"start": "1900-01-01", "end": "bad"})
        self.assertEqual(data["start"], "2026-04-02")
        self.assertEqual(data["end"], "2026-06-30")


class SearchDashboardAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.second = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="search-manager", role=User.Role.RESTAURANT_MANAGER)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.first)

    def test_manager_cannot_search_other_location(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("analytics_search"), {"location": self.second.code})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"]["location_count"], 1)
        self.assertNotContains(response, 'value="R0000002"')
        self.assertTrue(all(row["restaurant_code"] == "R0000001"
                            for row in response.context["dashboard"]["results"]))

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("analytics_search")).status_code, 302)
