import unittest
from pathlib import Path

from core.matrix_lookup import find_entry, find_sheet_name, load_matrix_entries

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX_XLSX = REPO_ROOT / "jurisdictions/jp/raw/matrix/kamotsu_matrix_20260214.xlsx"


@unittest.skipUnless(MATRIX_XLSX.exists(), "マトリクス表xlsxが未取得のためスキップ")
class TestMatrixLookup(unittest.TestCase):
    def test_find_sheet_name_handles_zenkaku_and_hankaku(self):
        import openpyxl
        wb = openpyxl.load_workbook(MATRIX_XLSX, data_only=True, read_only=True)
        # 3項・8項は半角表記のシート名、他は全角表記（実データの表記ゆれ）
        self.assertEqual(find_sheet_name(wb, "3"), "3項　化学兵器")
        self.assertEqual(find_sheet_name(wb, "8"), "8項　電子計算機")
        self.assertEqual(find_sheet_name(wb, "9"), "９項　通信")
        self.assertEqual(find_sheet_name(wb, "3_2"), "３の２項　生物兵器")
        self.assertIsNone(find_sheet_name(wb, "99"))

    def test_load_matrix_entries_row9_boundaries_match_known_subitems(self):
        entries = load_matrix_entries(MATRIX_XLSX, "9")
        item_ids = {e.item_id for e in entries if e.item_id is not None}
        expected = {"1", "2", "3", "4", "5", "5_2", "5_3", "5_4", "5_5", "6", "7", "8", "9", "10", "11"}
        self.assertEqual(item_ids, expected)

    def test_repealed_items_have_no_useful_text(self):
        entries = load_matrix_entries(MATRIX_XLSX, "9")
        for item_id in ("4", "9"):
            entry = find_entry(entries, item_id)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.item_text, "削除")

    def test_row9_item1_has_ministerial_text_and_terms(self):
        entries = load_matrix_entries(MATRIX_XLSX, "9")
        entry = find_entry(entries, "1")
        self.assertIsNotNone(entry)
        self.assertIn("貨物等省令第８条第二号", entry.ministerial_refs)
        self.assertIn("核爆発", entry.ministerial_text)
        term_names = {t for t, _ in entry.terms}
        self.assertIn("電子式交換装置", term_names)

    def test_row2_covers_all_52_items(self):
        entries = load_matrix_entries(MATRIX_XLSX, "2")
        item_ids = {e.item_id for e in entries if e.item_id is not None}
        self.assertEqual(len(item_ids), 54)
        self.assertIn("35_2", item_ids)

    def test_unknown_row_returns_empty(self):
        entries = load_matrix_entries(MATRIX_XLSX, "999")
        self.assertEqual(entries, [])

    def test_entry_to_dict(self):
        entries = load_matrix_entries(MATRIX_XLSX, "9")
        entry = find_entry(entries, "1")
        d = entry.to_dict()
        self.assertEqual(d["item_id"], "1")
        self.assertIn("terms", d)
        self.assertTrue(all({"term", "definition"} <= set(t.keys()) for t in d["terms"]))


if __name__ == "__main__":
    unittest.main()
