"""core.predicate_extractor.extract_subitems() の単体テスト（API不要）。

除外節の切り出し（単純な行参照、括弧ネストを含む号参照、機械解析できない
未対応パターンの識別）が実データに対して正しく動くことを検証する。
classify_subitems() 自体はTypeSafe APIへの実呼び出しが前提のためここでは
対象外（プロトタイプのライブ検証はscripts/classify_predicates.pyで実施）。
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.predicate_extractor import extract_subitems  # noqa: E402

XML_PATH = REPO_ROOT / "jurisdictions/jp/raw/cabinet_orders/324CO0000000378_20260605_令和八年政令第百九十四号.xml"


@unittest.skipUnless(XML_PATH.exists(), f"raw XML not found: {XML_PATH}")
class TestExtractSubitems(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = extract_subitems(XML_PATH, row_label="二")
        cls.by_id = {it.item_id: it for it in cls.items}

    def test_extracts_fifty_four_items(self):
        # 号（一）〜（五十二）に加え、枝番（十の二）（三十五の二）を含め54件
        self.assertEqual(len(self.items), 54)

    def test_simple_row_exclusion(self):
        # （四）人造黒鉛（四の項の中欄に掲げるものを除く。）
        item = self.by_id["4"]
        self.assertEqual(item.excludes_rows, ["4"])
        self.assertEqual(item.excludes_self_items, [])
        self.assertIsNone(item.raw_exclusion)
        self.assertNotIn("除く", item.text)

    def test_nested_paren_self_item_exclusion(self):
        # （七）...（（三十一）に掲げるものを除く。） - 括弧ネストの実例
        item = self.by_id["7"]
        self.assertEqual(item.excludes_self_items, ["31"])
        self.assertEqual(item.excludes_rows, [])
        self.assertNotIn("除く", item.text)

    def test_combined_self_and_row_exclusion(self):
        # （三十五の二）...（（三十五）及び三の項の中欄に掲げるものを除く。）
        item = self.by_id["35_2"]
        self.assertEqual(item.excludes_self_items, ["35"])
        self.assertEqual(item.excludes_rows, ["3"])

    def test_unresolvable_exclusion_flagged_as_raw(self):
        # （二十九）遠心力式釣合い試験機（一面釣合い試験機を除く。）
        # 項/号への参照ではないため機械解析できず、raw_exclusionに残る
        item = self.by_id["29"]
        self.assertEqual(item.excludes_rows, [])
        self.assertEqual(item.excludes_self_items, [])
        self.assertIsNotNone(item.raw_exclusion)
        self.assertIn("除く", item.raw_exclusion)

    def test_nested_sub_list_merged_into_parent(self):
        # （十二）は「次に掲げるもの」に続き全角数字の細目(１２)が続く
        item = self.by_id["12"]
        self.assertIn("数値制御を行うことができる工作機械", item.text)
        self.assertIn("測定装置", item.text)

    def test_item_without_exclusion_has_none(self):
        item = self.by_id["1"]
        self.assertEqual(item.excludes_rows, [])
        self.assertEqual(item.excludes_self_items, [])
        self.assertIsNone(item.raw_exclusion)

    def test_unknown_row_raises(self):
        with self.assertRaises(ValueError):
            extract_subitems(XML_PATH, row_label="存在しない行")


if __name__ == "__main__":
    unittest.main()
