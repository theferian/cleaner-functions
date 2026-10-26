"""Pure logic tests for screenshot-derived Adaptive Reader calibration."""
import importlib.util
from pathlib import Path
import sys
import unittest

TOOL_DIR = Path(__file__).resolve().parents[1] / "tools" / "adaptive_document_reader"
sys.path.insert(0, str(TOOL_DIR))
from calibrate_letter_in_reader_v03 import (
    load_profile, target_regions, normalized_box, iou, calibration_audit,
)


class TestCalibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_profile(TOOL_DIR / "azd_outgoing_letter_calibration_v01.json")

    def test_profile_matches_approved_visual_target_scope(self):
        self.assertEqual(self.profile["quality"], "HUMAN_REFERENCE_UNREVIEWED")
        self.assertEqual(len(self.profile["target_pages"]), 1)
        targets, issue = target_regions(self.profile, 1, 595, 842)
        self.assertIsNone(issue)
        self.assertEqual(len(targets), 13)
        self.assertEqual(len({x["field_id"] for x in targets}), 13)

    def test_page_two_not_invented(self):
        targets, issue = target_regions(self.profile, 2, 595, 842)
        self.assertEqual(targets, [])
        self.assertIsNone(issue)

    def test_aspect_guard(self):
        targets, issue = target_regions(self.profile, 1, 1000, 600)
        self.assertEqual(targets, [])
        self.assertIn("PAGE_ASPECT_MISMATCH", issue)

    def test_every_bbox_is_page_bounded(self):
        targets, issue = target_regions(self.profile, 1, 595, 842)
        for target in targets:
            x1, y1, x2, y2 = target["bbox_normalized"]
            self.assertTrue(0 <= x1 < x2 <= 1)
            self.assertTrue(0 <= y1 < y2 <= 1)
            self.assertIsNone(target["confidence"])
            self.assertEqual(target["verification"], "UNVERIFIED_SCREENSHOT_CALIBRATION")

    def test_iou_and_geometry_comparison(self):
        targets, _ = target_regions(self.profile, 1, 595, 842)
        proposals = [{"bbox": t["bbox"], "layout_type": t["layout_type"]} for t in targets]
        audit = calibration_audit(self.profile, 1, 595, 842, proposals, [])
        self.assertEqual(audit["summary"]["native_geometry_hits_iou030"], 12)
        self.assertEqual(audit["summary"]["source_fields_verified"], 0)
        self.assertEqual(iou([0,0,2,2],[0,0,2,2]), 1.0)
        self.assertEqual(iou([0,0,1,1],[2,2,3,3]), 0.0)


if __name__ == "__main__":
    unittest.main()
