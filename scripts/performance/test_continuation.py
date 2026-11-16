"""Continuation must preserve completed rounds and reject ambiguous history."""
import unittest

from run import pending_rounds


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.manifest = dict(batch="original", pilot=False, matrix=[
            dict(scenario="P3", vus=20, repeat=3, order=27),
            dict(scenario="P4", vus=5, repeat=1, order=28),
            dict(scenario="P5U", vus=5, repeat=1, order=37)],
            completed=["original-P3-vu20-r3"])

    def test_only_unfinished_rounds_are_selected_in_original_order(self):
        result = pending_rounds(self.manifest)
        self.assertEqual([row["scenario"] for row in result], ["P4", "P5U"])
        self.assertEqual([row["order"] for row in result], [28, 37])
        self.assertEqual(len(self.manifest["completed"]), 1)

    def test_unknown_or_duplicate_completion_is_rejected(self):
        for completed in [["other-P3-vu20-r3"], ["original-P3-vu20-r3"] * 2]:
            with self.subTest(completed=completed):
                self.manifest["completed"] = completed
                with self.assertRaises(ValueError):
                    pending_rounds(self.manifest)

    def test_completed_matrix_cannot_be_started_again(self):
        self.manifest["matrix"] = self.manifest["matrix"][:1]
        with self.assertRaises(ValueError):
            pending_rounds(self.manifest)


if __name__ == "__main__":
    unittest.main()
