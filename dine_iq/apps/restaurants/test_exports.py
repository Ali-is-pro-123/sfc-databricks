"""CSV export scope, completeness, and spreadsheet-safety checks."""

import csv
from io import StringIO

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from .exports import EXPORTS, build_export, spreadsheet_safe
from .models import LocationAccess, Restaurant


class ExportDataTests(SimpleTestCase):
    def setUp(self):
        if not (settings.PROJECT_ROOT / "parquet_data/step34-full/location_menu_items.parquet").is_file():
            self.skipTest("Verified export sources are not available")

    def test_every_export_builds_in_local_scope(self):
        for dataset in EXPORTS:
            with self.subTest(dataset=dataset):
                headers, rows = build_export(dataset, ["R0000001"])
                self.assertTrue(headers)
                self.assertTrue(rows)
                self.assertTrue(all(len(row) == len(headers) for row in rows))

    def test_exports_include_all_filtered_rows_not_first_page(self):
        self.assertEqual(len(build_export("menu", ["R0000001"])[1]), 180)
        self.assertEqual(len(build_export("search", ["R0000001"])[1]), 180)
        self.assertEqual(len(build_export("dual", ["R0000001"])[1]), 716)

    def test_spreadsheet_formula_text_is_escaped(self):
        for value in ("=1+1", "+cmd", "-cmd", "@SUM(1)", "  =1+1", "\t=1+1"):
            self.assertTrue(spreadsheet_safe(value).startswith("'"))
        self.assertEqual(spreadsheet_safe("Normal item"), "Normal item")
        self.assertEqual(spreadsheet_safe(-2.5), -2.5)


class ExportAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = Restaurant.objects.create(code="R0000001", name="Central", city="Karachi")
        cls.second = Restaurant.objects.create(code="R0000002", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="export-manager", role=User.Role.RESTAURANT_MANAGER)
        cls.no_access = User.objects.create_user(username="export-no-grant", role=User.Role.RESTAURANT_MANAGER)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.first)

    def _rows(self, response):
        return list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))

    def test_filtered_search_export_is_excel_compatible_and_scoped(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("download_csv", args=["search"]), {
            "location": "R0000002", "item": "M0000001"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].endswith('.csv"'))
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        rows = self._rows(response)
        self.assertGreater(len(rows), 1)
        self.assertTrue(all(row[0] == "R0000001" for row in rows[1:]))
        self.assertTrue(all(row[1] == "M0000001" for row in rows[1:]))
        self.assertNotIn("customer_code", rows[0])

    def test_dual_filters_are_preserved(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("download_csv", args=["dual"]), {
            "month": "2026-06", "status": "mismatch"})
        self.assertEqual(response.status_code, 200)
        rows = self._rows(response)
        self.assertTrue(all(row[0] == "R0000001" and row[2] == "2026-06-01"
                            and row[9] == "mismatch" for row in rows[1:]))

    def test_no_grant_cannot_export(self):
        self.client.force_login(self.no_access)
        self.assertEqual(self.client.get(reverse("download_csv", args=["menu"])).status_code, 403)

    def test_login_and_dataset_whitelist(self):
        self.assertEqual(self.client.get(reverse("download_csv", args=["menu"])).status_code, 302)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("download_csv", args=["unknown"])).status_code, 404)
