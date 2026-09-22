"""core.kaishaku_lookup の単体テスト（API不要）。

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
    @classmethod
    def setUpClass(cls):
        from core.kaishaku_lookup import find_interpretation_for_row
        cls.row9 = find_interpretation_for_row(PDF_PATH, row_label="９")

    def test_finds_row_9(self):
        self.assertIsNotNone(self.row9)
        self.assertGreater(len(self.row9.terms), 40)

    def test_first_term_is_not_dropped_by_boundary_off_by_one(self):
        # 項番号セルの文字位置が同一行の用語欄よりわずかに下にずれるため、
        # マージンなしだと先頭の用語（伝送通信装置）が前の項に誤って
        # 分類されてしまっていた実データ由来のリグレッションテスト。
        terms = [t.term for t in self.row9.terms]
        self.assertIn("伝送通信装置", terms)
        self.assertEqual(terms[0], "伝送通信装置")

    def test_multi_page_definition_is_concatenated(self):
        # 「伝送通信装置」の解釈はページをまたいで続く（用語欄が空の行が
        # 直前の用語の定義に結合されているはず）
        entry = next(t for t in self.row9.terms if t.term == "伝送通信装置")
        self.assertIn("終端装置", entry.definition)
        self.assertIn("水中通信装置", entry.definition)  # 次ページ側の続き

    def test_unknown_row_returns_none(self):
        from core.kaishaku_lookup import find_interpretation_for_row
        result = find_interpretation_for_row(PDF_PATH, row_label="存在しない項")
        self.assertIsNone(result)

    def test_match_terms_for_text_finds_direct_substring(self):
        from core.kaishaku_lookup import match_terms_for_text
        matched = match_terms_for_text(self.row9, "電子式交換装置")
        terms = [t.term for t in matched]
        self.assertIn("電子式交換装置", terms)

    def test_match_terms_for_text_finds_reverse_substring(self):
        # 号のテキスト「フェーズドアレーアンテナ」は、用語
        # 「電子的に走査が可能なフェーズドアレーアンテナ」の部分文字列
        # （逆方向）としてマッチする必要がある
        from core.kaishaku_lookup import match_terms_for_text
        matched = match_terms_for_text(self.row9, "フェーズドアレーアンテナ")
        terms = [t.term for t in matched]
        self.assertIn("電子的に走査が可能なフェーズドアレーアンテナ", terms)

    def test_match_terms_for_text_no_match_for_unrelated_text(self):
        from core.kaishaku_lookup import match_terms_for_text
        matched = match_terms_for_text(self.row9, "全く関係のない架空の号テキスト")
        self.assertEqual(matched, [])


if __name__ == "__main__":
    unittest.main()
