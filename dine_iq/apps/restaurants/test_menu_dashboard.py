"""Menu dashboard totals, filters and role boundaries."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .menu_dashboard import build_menu_dashboard
from .models import LocationAccess, Restaurant


class MenuDashboardDataTests(SimpleTestCase):
    def setUp(self):
        path = settings.PROJECT_ROOT / "parquet_data" / "step34-full" / "location_menu_items.parquet"
        if not path.is_file():
            self.skipTest("Verified menu snapshot is not available")

    def test_full_menu_class_and_movement_totals(self):
        codes = [f"R{number:07d}" for number in range(1, 25)]
        data = build_menu_dashboard(codes)
        self.assertEqual(data["pair_count"], 4320)
        self.assertEqual(data["item_count"], 180)
        self.assertEqual(data["class_counts"], {
            "Profit Driver": 202, "Volume Driver": 810,
            "Hidden Opportunity": 1229, "Low Performer": 2079})
        self.assertEqual(data["slow_moving_count"], 853)
        self.assertEqual(str(data["revenue"]), "125910828.14")
        self.assertEqual(data["rating_count"], 26705)

    def test_filters_do_not_change_scope_summary(self):
        codes = ["R0000001", "R0000002"]
        base = build_menu_dashboard(codes)
        filtered = build_menu_dashboard(codes, {"location": "R0000001",
                                                "class": "Low Performer",
                                                "movement": "slow_moving"})
        self.assertEqual(filtered["pair_count"], base["pair_count"])
        self.assertEqual(filtered["revenue"], base["revenue"])
        self.assertTrue(all(row["restaurant_code"] == "R0000001" and
                            row["location_menu_class"] == "Low Performer" and
                            row["movement_class"] == "slow_moving"
                            for row in filtered["items"]))
        self.assertLessEqual(filtered["filtered_count"], base["pair_count"])


class MenuDashboardAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.b = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="manager-menu-dashboard", role=User.Role.RESTAURANT_MANAGER)
        cls.analyst = User.objects.create_user(username="analyst-menu-dashboard", role=User.Role.ANALYST)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.a)

    def test_manager_sees_only_granted_location(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("menu_dashboard"), {"location": "R0000002"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "R0000001")
        self.assertNotContains(response, "R0000002")
        self.assertTrue(all(row["restaurant_code"] == "R0000001"
                            for row in response.context["page_obj"]))

    def test_analyst_can_filter_second_location(self):
        self.client.force_login(self.analyst)
        response = self.client.get(reverse("menu_dashboard"), {"location": "R0000002"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard"]["selected_location"], "R0000002")
        self.assertTrue(all(row["restaurant_code"] == "R0000002"
                            for row in response.context["page_obj"]))

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("menu_dashboard")).status_code, 302)
