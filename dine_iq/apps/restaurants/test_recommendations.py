"""Recommendation evidence is visible only within the user's location scope."""

import tempfile
from pathlib import Path

import duckdb
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from .models import LocationAccess, Restaurant


class RecommendationEvidenceViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Restaurant.objects.create(code="R1", name="Central", city="Karachi")
        cls.b = Restaurant.objects.create(code="R2", name="North", city="Lahore")
        cls.manager = User.objects.create_user(username="manager-evidence", role=User.Role.RESTAURANT_MANAGER)
        cls.analyst = User.objects.create_user(username="analyst-evidence", role=User.Role.ANALYST)
        LocationAccess.objects.create(user=cls.manager, restaurant=cls.a)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "evidence.parquet"
        con = duckdb.connect()
        con.execute("""CREATE TABLE evidence AS SELECT * FROM (VALUES
            ('one','review_bundle','item_pair_location','R1','I1','I2','Review local bundle',
             '["R1 evidence"]','No automatic change','Step 18','2026-07-01',
             'High',30.0,'baskets','observed pairs','Thirty baskets observed'),
            ('two','review_bundle','item_pair_location','R2','I3','I4','Review other bundle',
             '["R2 evidence"]','No automatic change','Step 18','2026-07-01',
             'Medium',20.0,'baskets','observed pairs','Twenty baskets observed'),
            ('three','review_segment_outreach','customer_segment',NULL,'At-Risk',NULL,'Review outreach',
             '["Global evidence"]','Consent required','Steps 15, 36','2026-07-01',
             'Low',100.0,'customers','review cohort','Cohort review only'))
            t(candidate_id,recommendation_type,scope,restaurant_code,subject_code,related_code,
              recommended_action,reason_lines_json,limitation,source_steps,as_of_exclusive,
              priority,impact_exposure,impact_unit,impact_basis,priority_reason)""")
        con.execute(f"COPY evidence TO '{self.path.as_posix()}' (FORMAT PARQUET)")
        con.close()

    def test_manager_sees_only_granted_location(self):
        self.client.force_login(self.manager)
        with override_settings(RECOMMENDATION_PRIORITY_PATH=self.path):
            response = self.client.get(reverse("restaurants:recommendations"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "R1 evidence")
        self.assertNotContains(response, "R2 evidence")
        self.assertNotContains(response, "Global evidence")

    def test_analyst_sees_location_and_global_evidence(self):
        self.client.force_login(self.analyst)
        with override_settings(RECOMMENDATION_PRIORITY_PATH=self.path):
            response = self.client.get(reverse("restaurants:recommendations"))
        self.assertEqual(response.status_code, 200)
        for phrase in ("R1 evidence", "R2 evidence", "Global evidence"):
            self.assertContains(response, phrase)

    def test_priority_filter_keeps_location_scope(self):
        self.client.force_login(self.manager)
        with override_settings(RECOMMENDATION_PRIORITY_PATH=self.path):
            response = self.client.get(reverse("restaurants:recommendations"), {"priority": "High"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "R1 evidence")
        self.assertNotContains(response, "R2 evidence")
        self.assertNotContains(response, "Global evidence")
