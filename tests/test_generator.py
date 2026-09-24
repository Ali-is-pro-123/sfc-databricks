"""Verify reproducibility, output integrity, and synthetic business relationships."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from data_generator.config import Config
from data_generator.engine import generate
from data_generator.evidence import evidence
from data_generator.storage import checksum, write_json
from data_generator.validate import validate


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="dineiq-generator-tests-")
        cls.root = Path(cls.workspace.name)
        cls.config = Config(end="2025-05-01", corruption_rate=.1)
        cls.dataset = cls.root / "baseline"
        cls.manifest = generate(cls.config, cls.dataset)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def test_independent_validation_and_all_issue_types(self):
        result = validate(self.dataset)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["corruption_issues"]), 13)
        self.assertFalse(result["srs_scale_met"])

    def test_seed_reproduces_every_data_file(self):
        other = generate(self.config, self.root / "repeat")
        self.assertEqual(self.manifest["files"], other["files"])
        self.assertEqual(checksum(self.dataset / "evaluation/corruption.jsonl"),
                         checksum(self.root / "repeat/evaluation/corruption.jsonl"))

    def test_corruption_is_independent_of_clean_generation(self):
        other = generate(Config(end="2025-05-01", corruption_rate=0), self.root / "no-corruption")
        clean = lambda manifest: {k: v for k, v in manifest["files"].items() if k.startswith("clean_reference/")}
        self.assertEqual(clean(self.manifest), clean(other))
        self.assertEqual(other["issues"], {})

    def test_different_seed_changes_data(self):
        other = generate(Config(seed=43, end="2025-05-01"), self.root / "different")
        self.assertNotEqual(self.manifest["files"], other["files"])

    def test_existing_directory_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):
            generate(self.config, self.dataset)

    def test_invalid_configuration_rejected(self):
        for kwargs in ({"profile": "bad"}, {"corruption_rate": -.1}, {"corruption_rate": .2},
                       {"end": "2025-01-03"}, {"start": "2027-01-01"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Config(**kwargs)

    def test_business_scenarios_exist_without_labels_in_features(self):
        metrics = json.loads((self.dataset / "evaluation/business_metrics.json").read_text())["items"]
        loss, hidden = metrics["M0000001"], metrics["M0000002"]
        self.assertLess(loss["contribution_cents"], 0)
        self.assertGreater(loss["quantity"], hidden["quantity"] * 5)
        self.assertGreater(hidden["contribution_cents"], 0)
        self.assertEqual(hidden.get("wasted_quantity", 0), 0)
        sample = json.loads((self.dataset / "samples.json").read_text())
        for records in sample.values():
            for row in records:
                self.assertNotIn("latent_segment", row)
                self.assertNotIn("scenario", row)

    def test_snapshot_counts_and_profiles(self):
        self.assertEqual(self.manifest["counts"]["clean_reference/order_items"], 10500)
        self.assertEqual(self.manifest["counts"]["clean_reference/ratings"], 1200)
        self.assertEqual(self.manifest["counts"]["clean_reference/wastage"], 750)

    def test_evidence_is_computed_from_records(self):
        report = evidence(self.dataset)
        self.assertTrue(report["checks"]["loss_making_popular_item"])
        self.assertTrue(report["checks"]["low_volume_high_margin_item"])
        self.assertTrue(report["checks"]["new_item_history"])
        self.assertGreater(report["measures"]["bundle_orders"], 350)

    def test_modified_file_is_rejected_and_failure_recorded(self):
        target = self.dataset / "raw/restaurants/part-000.csv"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"altered\n")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                validate(self.dataset)
            report = json.loads((self.dataset / "validation.json").read_text())
            self.assertEqual(report["status"], "failed")
        finally:
            target.write_bytes(original)

    def test_manifest_integrity_is_not_the_only_validation(self):
        # Rehash a semantically broken record to ensure FK checks independently fail.
        target = self.dataset / "clean_reference/menu_items/part-000.csv"
        original = target.read_bytes()
        manifest_path = self.dataset / "manifest.json"
        original_manifest = manifest_path.read_bytes()
        try:
            with target.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                fields, records = reader.fieldnames, list(reader)
            records[0]["category_code"] = "UNKNOWN"
            with target.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(records)
            changed = json.loads(original_manifest)
            changed["files"][target.relative_to(self.dataset).as_posix()]["sha256"] = checksum(target)
            write_json(manifest_path, changed)
            with self.assertRaisesRegex(ValueError, "Broken FK"):
                validate(self.dataset)
        finally:
            target.write_bytes(original)
            manifest_path.write_bytes(original_manifest)
