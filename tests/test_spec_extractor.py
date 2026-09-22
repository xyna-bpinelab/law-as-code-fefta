import unittest

from core.spec_extractor import evaluate_criterion, extract_spec_criteria


class TestExtractSpecCriteria(unittest.TestCase):
    def test_arabic_halfwidth_threshold(self):
        criteria = extract_spec_criteria(["帯域幅が500メガヘルツを超えるもの"])
        self.assertEqual(len(criteria), 1)
        c = criteria[0]
        self.assertTrue(c.resolved)
        self.assertEqual(c.comparator, ">")
        self.assertEqual(c.threshold, 500.0)
        self.assertEqual(c.unit, "メガヘルツ")
        self.assertEqual(c.parameter_label, "帯域幅")

    def test_arabic_fullwidth_with_decimal(self):
        criteria = extract_spec_criteria(["コードレス電話機端末の実効距離が４００メートル未満のもの"])
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0].threshold, 400.0)
        self.assertEqual(criteria[0].comparator, "<")

    def test_kanji_digitseq_not_positional(self):
        # 「五六」= 56（数字列表記。位取りなら「五十六」となるはず）
        criteria = extract_spec_criteria(["対称鍵の長さが五六ビットを超えるもの"])
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0].threshold, 56.0)
        self.assertEqual(criteria[0].unit, "ビット")

    def test_kanji_digitseq_three_digits(self):
        criteria = extract_spec_criteria(["五一二ビットを超える整数の素因数分解"])
        self.assertEqual(criteria[0].threshold, 512.0)

    def test_zeroka_prefix_negates_threshold(self):
        criteria = extract_spec_criteria(["零下５５度より低い温度で使用することができるように設計したもの"])
        self.assertEqual(len(criteria), 1)
        c = criteria[0]
        self.assertTrue(c.resolved)
        self.assertEqual(c.threshold, -55.0)
        self.assertEqual(c.comparator, "<")
        self.assertEqual(c.unit, "度")

    def test_unit_annotation_paren_does_not_become_threshold(self):
        criteria = extract_spec_criteria([
            "無線周波数の出力が０．１ワット（２０ディービーエム）以下で、かつ、"
            "同時に接続できるデバイスが三二以下のもの"
        ])
        self.assertEqual(len(criteria), 2)
        self.assertEqual(criteria[0].threshold, 0.1)
        self.assertEqual(criteria[0].unit, "ワット")
        self.assertEqual(criteria[1].threshold, 32.0)

    def test_unresolvable_line_flagged_not_resolved(self):
        criteria = extract_spec_criteria([
            "核爆発による過渡的な電子的効果又はパルスによる影響を防止することができるように設計したもの"
        ])
        self.assertEqual(len(criteria), 1)
        self.assertFalse(criteria[0].resolved)
        self.assertIsNone(criteria[0].threshold)

    def test_repealed_lines_are_skipped(self):
        criteria = extract_spec_criteria(["削除", "（削る）", "  "])
        self.assertEqual(criteria, [])

    def test_percent_threshold(self):
        criteria = extract_spec_criteria(["瞬時帯域幅を中心周波数で除した値が20パーセント以上のもの"])
        self.assertEqual(criteria[0].comparator, ">=")
        self.assertEqual(criteria[0].threshold, 20.0)


class TestEvaluateCriterion(unittest.TestCase):
    def _numeric(self, comparator, threshold):
        criteria = extract_spec_criteria([f"値が{int(threshold)}メートル{ {'>=':'以上','<=':'以下','>':'を超える','<':'未満'}[comparator] }のもの"])
        return criteria[0]

    def test_gte_boundary(self):
        c = self._numeric(">=", 10)
        self.assertTrue(evaluate_criterion(c, 10))
        self.assertTrue(evaluate_criterion(c, 11))
        self.assertFalse(evaluate_criterion(c, 9))

    def test_lt_boundary(self):
        c = self._numeric("<", 10)
        self.assertFalse(evaluate_criterion(c, 10))
        self.assertTrue(evaluate_criterion(c, 9))

    def test_missing_value_is_none(self):
        c = self._numeric(">=", 10)
        self.assertIsNone(evaluate_criterion(c, None))
        self.assertIsNone(evaluate_criterion(c, ""))

    def test_unresolved_criterion_uses_boolean_value_directly(self):
        criteria = extract_spec_criteria(["核爆発による影響を防止することができるように設計したもの"])
        c = criteria[0]
        self.assertFalse(c.resolved)
        self.assertTrue(evaluate_criterion(c, True))
        self.assertFalse(evaluate_criterion(c, False))
        self.assertIsNone(evaluate_criterion(c, None))


if __name__ == "__main__":
    unittest.main()
