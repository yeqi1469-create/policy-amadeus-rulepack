import unittest
from update_progress import check_progress, progress_caption


class ProgressTests(unittest.TestCase):
    def test_initial_unknown_time(self):
        self.assertIsNone(check_progress(0, 50, 0)["remaining_seconds"])
        self.assertIn("正在估算", progress_caption({"state": "checking"}))

    def test_measured_percentage_and_estimate(self):
        result = check_progress(25, 50, 60)
        self.assertEqual(result["progress_percent"], 47)
        self.assertEqual(result["remaining_seconds"], 60)

    def test_finalization_not_premature_complete(self):
        self.assertEqual(check_progress(50, 50, 60)["progress_percent"], 95)
        self.assertIn("规则校验", progress_caption({"state": "checking", **check_progress(50, 50, 60)}))

    def test_complete_means_check_finished_not_sources_accessible(self):
        self.assertEqual(progress_caption({"state": "partial", "checked_at": "today"}), "检查完成 · 100%")

    def test_minute_rounding(self):
        self.assertIn("2 分钟", progress_caption({"state": "checking", "remaining_seconds": 61}))
