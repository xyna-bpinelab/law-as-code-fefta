"""core.list_classifier.load_table_rows() の単体テスト（API不要）。

classify_item() 自体はTypeSafe APIへの実呼び出しが前提のため、ここでは
XMLからの行抽出ロジック（load_table_rows）のみを対象とする。
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.list_classifier import load_table_rows  # noqa: E402

XML_PATH = REPO_ROOT / "jurisdictions/jp/raw/cabinet_orders/324CO0000000378_20260605_令和八年政令第百九十四号.xml"


@unittest.skipUnless(XML_PATH.exists(), f"raw XML not found: {XML_PATH}")
class TestLoadTableRows(unittest.TestCase):
    def test_extracts_seventeen_rows_from_beppyo_1(self):
        rows = load_table_rows(XML_PATH, table_title="別表第一")
        self.assertEqual(len(rows), 17)

    def test_row_ids_and_labels_are_consistent(self):
        rows = load_table_rows(XML_PATH, table_title="別表第一")
        by_id = {r.row_id: r for r in rows}
        self.assertIn("1", by_id)
        self.assertEqual(by_id["1"].label, "一")
        # 「三の二」は独立した行として存在する枝番の実例
        self.assertIn("3_2", by_id)
        self.assertEqual(by_id["3_2"].label, "三の二")

    def test_descriptions_are_non_empty_and_truncated(self):
        rows = load_table_rows(XML_PATH, table_title="別表第一")
        for row in rows:
            self.assertTrue(row.description)
            self.assertLessEqual(len(row.description), 500)
            self.assertGreaterEqual(row.full_length, len(row.description))

    def test_unknown_table_title_raises(self):
        with self.assertRaises(ValueError):
            load_table_rows(XML_PATH, table_title="存在しない別表")


if __name__ == "__main__":
    unittest.main()
