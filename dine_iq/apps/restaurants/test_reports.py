"""Downloadable report coverage, source scope, and response safety."""

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .models import LocationAccess, Restaurant
from .reports import REPORTS, build_report


class ReportDataTests(SimpleTestCase):
    def setUp(self):
        if not (settings.PROJECT_ROOT / "processed_data/step14-full-verified/comparison_report.json").is_file():
            self.skipTest("Verified analytical reports are not available")

    def test_every_srs_report_family_builds(self):
        codes = [f"R{number:07d}" for number in range(1, 25)]
        for slug in REPORTS:
            with self.subTest(slug=slug):
                report = build_report(slug, codes)
                self.assertEqual(report["slug"], slug)
                self.assertEqual(report["location_count"], 24)
                self.assertTrue(report["sections"])
                self.assertTrue(report["notes"])

    def test_scoped_market_basket_is_recalculated(self):
        network = build_report("market-basket", [f"R{number:07d}" for number in range(1, 25)])
        local = build_report("market-basket", ["R0000001"])
        self.assertEqual(local["location_count"], 1)
        self.assertIn("recalculated", " ".join(local["notes"]))
        self.assertNotEqual(network["notes"][0], local["notes"][0])


class ReportDownloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.second = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="report-manager", role=User.Role.RESTAURANT_MANAGER)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.first)

    def test_download_is_offline_html_attachment_and_scoped(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("download_report", args=["location-performance"]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertContains(response, "DineIQ Karachi 1")
        self.assertNotContains(response, "DineIQ Lahore 2")
        self.assertNotContains(response, "cdn.jsdelivr.net")
        self.assertContains(response, "--orange: #c94e21")
        self.assertNotContains(response, "#0f6b52")

    def test_unknown_report_is_not_found(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("download_report", args=["unknown"])).status_code, 404)

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("report_center")).status_code, 302)
        self.assertEqual(self.client.get(reverse("download_report", args=["wastage"])).status_code, 302)
