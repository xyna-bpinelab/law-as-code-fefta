import unittest

from core.spec_extractor import (
    build_clause_tree,
    detect_combinator,
    evaluate_criterion,
    extract_spec_criteria,
)


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


class TestDetectCombinator(unittest.TestCase):
    def test_izureka_is_or(self):
        self.assertEqual(detect_combinator("次のイからホまでのいずれかに該当するもの"), "OR")

    def test_subete_is_and(self):
        self.assertEqual(detect_combinator("次の１から３までの全てに該当するもの"), "AND")
        self.assertEqual(detect_combinator("次の一から四までのすべてに該当する線形増幅器を用いたもの"), "AND")

    def test_oyobi_without_mataha_is_and(self):
        self.assertEqual(detect_combinator("次の１及び２に該当するもの"), "AND")

    def test_mataha_without_oyobi_is_or(self):
        self.assertEqual(detect_combinator("次の（一）又は（二）に該当するもの"), "OR")

    def test_ambiguous_both_particles_returns_none(self):
        self.assertIsNone(detect_combinator(
            "次のイ及びロに該当するもの又はその部分品"
        ))

    def test_no_signal_returns_none(self):
        self.assertIsNone(detect_combinator("零下５５度より低い温度で使用することができるように設計したもの"))


class TestBuildClauseTree(unittest.TestCase):
    def test_flat_kana_siblings_no_lead_sentence(self):
        lines = [
            "イ　核爆発による過渡的な電子的効果を防止することができるように設計したもの",
            "ロ　ガンマ線による影響を防止することができるように設計したもの",
            "ハ　零下５５度より低い温度で使用することができるように設計したもの",
        ]
        tree = build_clause_tree(lines)
        self.assertEqual(len(tree), 3)
        self.assertEqual([n.marker for n in tree], ["イ", "ロ", "ハ"])
        self.assertEqual(tree[2].own_criteria[0].threshold, -55.0)
        for n in tree:
            self.assertEqual(n.children, [])

    def test_lead_sentence_with_or_children(self):
        lines = [
            "伝送通信装置又はその部分品若しくは附属品であって、次のいずれかに該当するもの",
            "イ　　無線送信機又は無線受信機であって、次のいずれかに該当するもの",
            "ロ　デジタル信号処理機能を有するものであって、符号化速度が７００ビット毎秒未満のもの",
        ]
        tree = build_clause_tree(lines)
        self.assertEqual(len(tree), 1)
        root = tree[0]
        self.assertIsNone(root.marker)
        self.assertEqual(root.combinator, "OR")
        self.assertEqual(len(root.children), 2)
        self.assertEqual([c.marker for c in root.children], ["イ", "ロ"])
        self.assertEqual(root.children[1].own_criteria[0].threshold, 700.0)

    def test_nested_and_group_under_paren_marker(self):
        lines = [
            "（一）　　1．5メガヘルツ以上87.5メガヘルツ以下の周波数範囲で使用することができるものであって、次の1及び2に該当するもの",
            "　　　　1　最適送信周波数を自動的に予測及び選択することができるもの",
            "　　　　2　次の一から四までのすべてに該当する線形増幅器を用いたもの",
            "　　　　　一　2つ以上の信号を同時に増幅することができるもの",
            "　　　　　二　1オクターブ以上の瞬時帯域幅を有するもの",
        ]
        tree = build_clause_tree(lines)
        self.assertEqual(len(tree), 1)
        paren_node = tree[0]
        self.assertEqual(paren_node.marker, "（一）")
        self.assertEqual(paren_node.combinator, "AND")
        self.assertEqual(len(paren_node.children), 2)
        item2 = paren_node.children[1]
        self.assertEqual(item2.marker, "2")
        self.assertEqual(item2.combinator, "AND")
        self.assertEqual(len(item2.children), 2)
        self.assertEqual([c.marker for c in item2.children], ["一", "二"])

    def test_repealed_and_annotation_lines_excluded(self):
        lines = [
            "＊対応する貨物等省令は、第８条第１項第一号及び第二号",
            "削除",
            "（削る）",
            "イ　実体のある行",
        ]
        tree = build_clause_tree(lines)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0].marker, "イ")

    def test_to_dict_round_trips_nested_structure(self):
        lines = [
            "伝送通信装置であって、次のいずれかに該当するもの",
            "イ　テスト条件",
        ]
        tree = build_clause_tree(lines)
        d = tree[0].to_dict()
        self.assertEqual(d["combinator"], "OR")
        self.assertEqual(len(d["children"]), 1)
        self.assertEqual(d["children"][0]["marker"], "イ")


if __name__ == "__main__":
    unittest.main()
