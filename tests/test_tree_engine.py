"""law-as-code-fefta の決定木エンジン（core.tree_engine）の結合テスト。

jurisdictions/jp/processed/inclusive_license_tree.json と exemption_tree.json
それぞれについて、全ての終端結果（results）に実際に到達できることを
MockJevClient（APIキー不要）で検証する。

実行方法:
    python3 -m unittest discover -s tests
    # または
    pytest tests/
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.jev_client import MockJevClient  # noqa: E402
from core.tree_engine import TreeEngineError, load_tree_by_name, run_tree  # noqa: E402


class TestInclusiveLicenseTree(unittest.TestCase):
    """jurisdictions/jp/processed/inclusive_license_tree.json の全7結果を検証する。"""

    @classmethod
    def setUpClass(cls):
        cls.tree = load_tree_by_name("inclusive_license_tree")

    def _run(self, facts):
        return run_tree(self.tree, facts, jev_client=MockJevClient())

    def test_not_list_controlled(self):
        facts = {"item": {"is_list_controlled": False}}
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_NOT_LIST_CONTROLLED")

    def test_very_sensitive_requires_individual_license(self):
        facts = {"item": {"is_list_controlled": True, "is_kokushi_kawamono": True}}
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_INDIVIDUAL_LICENSE_REQUIRED_VERY_SENSITIVE")

    def test_sensitive_without_special_general_requires_individual(self):
        facts = {
            "item": {"is_list_controlled": True, "is_kokushi_kawamono": False, "is_sensitive_list": True},
            "company": {"has_special_general_license": False},
            "destination": {"is_embargoed_country": False},
            "transaction": {"is_suspicious": False},
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_INDIVIDUAL_LICENSE_REQUIRED_SENSITIVE")

    def test_sensitive_with_special_general_license_applicable(self):
        facts = {
            "item": {"is_list_controlled": True, "is_kokushi_kawamono": False, "is_sensitive_list": True},
            "company": {"has_special_general_license": True},
            "destination": {"is_embargoed_country": False},
            "transaction": {"is_suspicious": False},
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_SPECIAL_GENERAL_LICENSE_APPLICABLE")

    def test_general_license_applicable(self):
        facts = {
            "item": {"is_list_controlled": True, "is_kokushi_kawamono": False, "is_sensitive_list": False},
            "company": {"has_registered_cp": True},
            "destination": {"is_group_a_country": True},
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_GENERAL_LICENSE_APPLICABLE")

    def test_specific_inclusive_license_applicable(self):
        facts = {
            "item": {"is_list_controlled": True, "is_kokushi_kawamono": False, "is_sensitive_list": False},
            "company": {"has_registered_cp": False},
            "destination": {"is_group_a_country": False, "is_permitted_region_for_specific": True},
            "transaction": {"is_continuous_business": True},
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_SPECIFIC_INCLUSIVE_LICENSE_APPLICABLE")

    def test_individual_license_required_fallthrough(self):
        facts = {
            "item": {"is_list_controlled": True, "is_kokushi_kawamono": False, "is_sensitive_list": False},
            "company": {"has_registered_cp": False},
            "destination": {"is_group_a_country": False, "is_permitted_region_for_specific": False},
            "transaction": {"is_continuous_business": False},
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_INDIVIDUAL_LICENSE_REQUIRED")

    def test_trace_records_every_visited_node(self):
        facts = {"item": {"is_list_controlled": False}}
        result = self._run(facts)
        # root(N000_START) を通過した1ステップのみのはず
        self.assertEqual(len(result.trace), 1)
        self.assertEqual(result.trace[0].node_id, "N000_START")
        self.assertEqual(result.trace[0].branch, "false")


class TestExemptionTree(unittest.TestCase):
    """jurisdictions/jp/processed/exemption_tree.json の全6結果を検証する。"""

    @classmethod
    def setUpClass(cls):
        cls.tree = load_tree_by_name("exemption_tree")

    def _run(self, facts):
        return run_tree(self.tree, facts, jev_client=MockJevClient())

    def _base_item(self, **overrides):
        item = {
            "is_list_controlled": True,
            "category_number": 5,
            "is_kokushi_kawamono": False,
            "is_wmd_related": False,
            "small_value_limit_jpy": 100000,
            "is_small_value_excluded": False,
            "spec_changed": False,
        }
        item.update(overrides)
        return item

    def test_not_list_controlled(self):
        facts = {"item": {"is_list_controlled": False}}
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_EXEMPTION_NOT_APPLICABLE_NOT_LISTED")

    def test_high_risk_item_excluded_any_single_flag(self):
        # E100 は OR 結合: 3条件のうち category_number==1 だけが真でも除外される
        facts = {"item": self._base_item(category_number=1)}
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_EXEMPTION_NOT_APPLICABLE_HIGH_RISK")

    def test_high_risk_item_excluded_via_kokushi_kawamono(self):
        facts = {"item": self._base_item(is_kokushi_kawamono=True)}
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_EXEMPTION_NOT_APPLICABLE_HIGH_RISK")

    def test_small_value_exemption_applicable(self):
        facts = {
            "item": self._base_item(),
            "destination": {"is_small_value_excluded_country": False},
            "transaction": {"contract_value_jpy": 50000, "is_split_shipment": False},
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_EXEMPTION_APPLICABLE_SMALL_VALUE")

    def test_repair_exemption_applicable(self):
        facts = {
            "item": self._base_item(),
            "destination": {"is_small_value_excluded_country": False},
            "transaction": {
                "contract_value_jpy": 500000,  # 少額特例の上限を超過させる
                "is_split_shipment": False,
                "reason": "REPAIR_RETURN",
                "is_free_of_charge": True,
            },
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_EXEMPTION_APPLICABLE_REPAIR")

    def test_baggage_exemption_applicable(self):
        facts = {
            "item": self._base_item(),
            "destination": {"is_small_value_excluded_country": False},
            "transaction": {
                "contract_value_jpy": 500000,
                "is_split_shipment": False,
                "reason": "OTHER",
                "is_free_of_charge": False,
                "is_personal_baggage": True,
                "for_personal_use": True,
            },
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_EXEMPTION_APPLICABLE_BAGGAGE")

    def test_no_exemption_applicable_fallthrough(self):
        facts = {
            "item": self._base_item(),
            "destination": {"is_small_value_excluded_country": False},
            "transaction": {
                "contract_value_jpy": 500000,
                "is_split_shipment": False,
                "reason": "OTHER",
                "is_free_of_charge": False,
                "is_personal_baggage": False,
                "for_personal_use": False,
            },
        }
        result = self._run(facts)
        self.assertEqual(result.result_id, "RESULT_EXEMPTION_NOT_APPLICABLE")

    def test_e300_false_branch_continues_to_e400_not_a_terminal_result(self):
        """E300のfalse分岐は結果ではなく次のノード(E400)へ継続することをトレースで確認する。"""
        facts = {
            "item": self._base_item(),
            "destination": {"is_small_value_excluded_country": False},
            "transaction": {
                "contract_value_jpy": 500000,
                "is_split_shipment": False,
                "reason": "OTHER",
                "is_free_of_charge": False,
                "is_personal_baggage": True,
                "for_personal_use": True,
            },
        }
        result = self._run(facts)
        visited_ids = [s.node_id for s in result.trace]
        self.assertIn("E300_REPAIR_EXEMPTION_CHECK", visited_ids)
        self.assertIn("E400_BAGGAGE_EXEMPTION_CHECK", visited_ids)


class TestEngineErrorHandling(unittest.TestCase):
    def test_unknown_evaluator_raises(self):
        tree = {
            "tree_id": "t",
            "nodes": {"root": {"id": "X", "evaluator": "mystery", "next": {}}},
            "results": {},
        }
        with self.assertRaises(TreeEngineError):
            run_tree(tree, {}, jev_client=MockJevClient())

    def test_missing_next_branch_raises(self):
        tree = {
            "tree_id": "t",
            "nodes": {"root": {"id": "X", "evaluator": "hard_rule", "condition": "item.flag == true", "next": {"true": "RESULT_A"}}},
            "results": {"RESULT_A": {}},
        }
        with self.assertRaises(TreeEngineError):
            run_tree(tree, {"item": {"flag": False}}, jev_client=MockJevClient())


if __name__ == "__main__":
    unittest.main()
