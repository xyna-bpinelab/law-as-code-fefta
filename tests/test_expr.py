"""core.expr（条件式ミニ言語エバリュエータ）の単体テスト。

実行方法:
    python3 -m unittest discover -s tests
    # または pytest がインストールされていれば
    pytest tests/
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.expr import ExpressionError, evaluate  # noqa: E402


class TestExprBasics(unittest.TestCase):
    def test_bool_literal_true(self):
        self.assertTrue(evaluate("item.flag == true", {"item": {"flag": True}}))

    def test_bool_literal_false(self):
        self.assertTrue(evaluate("item.flag == false", {"item": {"flag": False}}))
        self.assertFalse(evaluate("item.flag == false", {"item": {"flag": True}}))

    def test_numeric_comparators(self):
        facts = {"transaction": {"v": 100}, "item": {"limit": 200}}
        self.assertTrue(evaluate("transaction.v <= item.limit", facts))
        self.assertTrue(evaluate("transaction.v < item.limit", facts))
        self.assertFalse(evaluate("transaction.v > item.limit", facts))
        self.assertFalse(evaluate("transaction.v >= item.limit", facts))
        self.assertTrue(evaluate("transaction.v == 100", facts))
        self.assertTrue(evaluate("transaction.v != item.limit", facts))

    def test_string_equality(self):
        facts = {"transaction": {"reason": "REPAIR_RETURN"}}
        self.assertTrue(evaluate("transaction.reason == 'REPAIR_RETURN'", facts))
        self.assertFalse(evaluate("transaction.reason == 'FREE_REPLACEMENT'", facts))

    def test_or_combination(self):
        facts = {"transaction": {"reason": "FREE_REPLACEMENT"}}
        expr = "transaction.reason == 'REPAIR_RETURN' or transaction.reason == 'FREE_REPLACEMENT'"
        self.assertTrue(evaluate(expr, facts))

    def test_and_combination(self):
        facts = {"a": {"x": True}, "b": {"y": False}}
        self.assertFalse(evaluate("a.x == true and b.y == true", facts))

    def test_missing_fact_raises(self):
        with self.assertRaises(ExpressionError):
            evaluate("item.does_not_exist == true", {"item": {}})

    def test_missing_top_level_key_raises(self):
        with self.assertRaises(ExpressionError):
            evaluate("item.flag == true", {})

    def test_syntax_error_raises(self):
        with self.assertRaises(ExpressionError):
            evaluate("item.flag ==", {"item": {"flag": True}})

    def test_disallowed_function_call_rejected(self):
        with self.assertRaises(ExpressionError):
            evaluate("__import__('os').system('echo hi') == true", {})

    def test_disallowed_assignment_like_syntax_rejected(self):
        with self.assertRaises(ExpressionError):
            evaluate("(item.flag := true)", {"item": {"flag": True}})


if __name__ == "__main__":
    unittest.main()
