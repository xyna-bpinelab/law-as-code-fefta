"""core.ministerial_spec_lookup.find_spec_for_row() の単体テスト（API不要）。

貨物等省令の条文は「輸出貿易管理令（以下「輸出令」という。）別表第一の
◯の項の経済産業省令で定める仕様のものは...」のように正式名称＋略称定義が
埋め込まれる場合と、2回目以降の参照のように単に「輸出令別表第一の◯の項の
...」となる場合の両方があるため、両パターンで正しく検索できることを検証する。
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.ministerial_spec_lookup import find_spec_for_row  # noqa: E402

XML_PATH = REPO_ROOT / "jurisdictions/jp/raw/ministerial_orders/403M50000400049_20260214_令和七年経済産業省令第七十二号.xml"


@unittest.skipUnless(XML_PATH.exists(), f"raw XML not found: {XML_PATH}")
class TestFindSpecForRow(unittest.TestCase):
    def test_first_article_with_full_name_and_abbreviation_definition(self):
        # 第一条: 「輸出貿易管理令（以下「輸出令」という。）別表第一の二の項の...」
        spec = find_spec_for_row(XML_PATH, row_label="二")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.article_title, "第一条")

    def test_later_article_with_plain_abbreviation(self):
        # 第八条: 「輸出令別表第一の九の項の...」（略称のみ、定義の再掲なし）
        spec = find_spec_for_row(XML_PATH, row_label="九")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.article_title, "第八条")
        self.assertGreater(len(spec.full_text), 1000)
        self.assertGreater(spec.item_count, 0)

    def test_row_number_with_zero_digit(self):
        # 「一〇」(=10) のように位取り表記に「〇」を含む項番号
        spec = find_spec_for_row(XML_PATH, row_label="一〇")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.article_title, "第九条")

    def test_row_without_ministerial_delegation_returns_none(self):
        # 「一」(武器) は経済産業省令への委任がないため対応条文なし
        spec = find_spec_for_row(XML_PATH, row_label="一")
        self.assertIsNone(spec)

    def test_unknown_row_returns_none(self):
        spec = find_spec_for_row(XML_PATH, row_label="存在しない項")
        self.assertIsNone(spec)


if __name__ == "__main__":
    unittest.main()
