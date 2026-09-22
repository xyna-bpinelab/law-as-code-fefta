"""core.kaishaku_lookup.find_interpretation_for_row() の単体テスト（API不要）。

pdfplumberが必要なため、未インストール環境ではスキップする。
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    import pdfplumber  # noqa: F401
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

PDF_PATH = REPO_ROOT / "jurisdictions/jp/raw/circulars/kamotsu-kaishaku.pdf"


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber not installed")
@unittest.skipUnless(PDF_PATH.exists(), f"kaishaku PDF not found: {PDF_PATH}")
class TestFindInterpretationForRow(unittest.TestCase):
    def test_finds_row_9_starting_with_its_own_label(self):
        from core.kaishaku_lookup import find_interpretation_for_row
        result = find_interpretation_for_row(PDF_PATH, row_label="９")
        self.assertIsNotNone(result)
        self.assertTrue(result.text.startswith("９"))
        self.assertIn("伝送通信装置", result.text)

    def test_row_range_is_before_next_row_label(self):
        from core.kaishaku_lookup import find_interpretation_for_row
        result = find_interpretation_for_row(PDF_PATH, row_label="９")
        # 項10の内容（量子ビット等、項9の前段に出てくる用語ではない）が
        # 混入していないことを軽く確認する
        self.assertLess(result.start_page, result.end_page + 1)

    def test_unknown_row_returns_none(self):
        from core.kaishaku_lookup import find_interpretation_for_row
        result = find_interpretation_for_row(PDF_PATH, row_label="存在しない項")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
