"""Boundary and data-integrity checks for the survey pipeline."""

import csv
import tempfile
import unittest
from pathlib import Path

from run_analysis import SOURCE, classify_theme, load_and_validate, nps_group


class SurveyAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with SOURCE.open(newline="", encoding="utf-8") as stream:
            cls.rows = list(csv.DictReader(stream))

    def write_rows(self, rows):
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "survey.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return temp, path

    def test_nps_boundaries(self):
        self.assertEqual([nps_group(i) for i in (0, 6, 7, 8, 9, 10)],
                         ["Detractor", "Detractor", "Passive", "Passive", "Promoter", "Promoter"])

    def test_source_is_valid(self):
        records = load_and_validate(SOURCE)
        self.assertEqual(len(records), 1000)
        self.assertEqual(len({r["response_id"] for r in records}), 1000)

    def test_duplicate_id_rejected(self):
        rows = [dict(self.rows[0]), dict(self.rows[0])]
        temp, path = self.write_rows(rows)
        with temp:
            with self.assertRaisesRegex(ValueError, "duplicate response ID"):
                load_and_validate(path)

    def test_mismatched_band_rejected(self):
        row = dict(self.rows[0]); row["nps_group"] = "Promoter"
        temp, path = self.write_rows([row])
        with temp:
            with self.assertRaisesRegex(ValueError, "band disagrees"):
                load_and_validate(path)

    def test_out_of_range_satisfaction_rejected(self):
        row = dict(self.rows[0]); row["satisfaction"] = "6"
        temp, path = self.write_rows([row])
        with temp:
            with self.assertRaisesRegex(ValueError, "Out-of-range"):
                load_and_validate(path)

    def test_comment_theme(self):
        self.assertEqual(classify_theme('Could not find the "undo" button anywhere'), "Undo discoverability")
        self.assertEqual(classify_theme("Crashed on my file, twice"), "File crash")
        self.assertEqual(classify_theme(""), "Other")


if __name__ == "__main__":
    unittest.main()
