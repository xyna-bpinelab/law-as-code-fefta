"""law-as-code-fefta の決定木で使われる条件式（例:
``item.is_list_controlled == true`` や
``transaction.contract_value_jpy <= item.small_value_limit_jpy``）を
安全に評価するためのミニ言語エバリュエータ。

``eval()``/``exec()`` は一切使用しない。Python の ``ast`` モジュールで
一度構文木に変換した上で、許可した構文要素（比較・論理演算・ドット区切り
のフィールド参照・リテラル）だけを手動で解釈する。それ以外の構文
（関数呼び出し、属性代入、import 等）は ExpressionError として拒否される。
"""

from __future__ import annotations

import ast
from typing import Any

__all__ = ["ExpressionError", "evaluate"]


class ExpressionError(ValueError):
    """条件式の構文・評価エラー。"""


_COMPARATORS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}

# 条件式内で許可する構文ノードの型（それ以外は拒否する）
_ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Attribute,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.UnaryOp,
    ast.Not,
)


def _check_allowed(node: ast.AST) -> None:
    for child in ast.walk(node):
        if not isinstance(child, _ALLOWED_NODE_TYPES):
            raise ExpressionError(
                f"許可されていない構文要素です: {type(child).__name__}"
            )


def _dotted_path(node: ast.expr) -> list[str]:
    """Attribute チェーン (a.b.c) をパーツのリストに分解する。"""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    else:
        raise ExpressionError(f"不正な参照式です: {ast.dump(node)}")
    parts.reverse()
    return parts


def _resolve(node: ast.expr, facts: dict) -> Any:
    """Attribute/Name ノードを facts 辞書に対して解決する。
    単一トークンの ``true``/``false`` は真偽値リテラルとして扱う。"""
    parts = _dotted_path(node)
    if len(parts) == 1 and parts[0] in ("true", "false"):
        return parts[0] == "true"

    value: Any = facts
    for i, part in enumerate(parts):
        if not isinstance(value, dict) or part not in value:
            path = ".".join(parts[: i + 1])
            raise ExpressionError(f"factsに存在しないフィールドです: {path}")
        value = value[part]
    return value


def _eval(node: ast.AST, facts: dict) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, facts)

    if isinstance(node, ast.BoolOp):
        values = [_eval(v, facts) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ExpressionError(f"未対応の論理演算子です: {node.op}")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval(node.operand, facts)

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ExpressionError("連鎖比較（a < b < c）はサポートしていません")
        left = _eval(node.left, facts)
        right = _eval(node.comparators[0], facts)
        op_type = type(node.ops[0])
        if op_type not in _COMPARATORS:
            raise ExpressionError(f"未対応の比較演算子です: {op_type.__name__}")
        return _COMPARATORS[op_type](left, right)

    if isinstance(node, (ast.Attribute, ast.Name)):
        return _resolve(node, facts)

    if isinstance(node, ast.Constant):
        return node.value

    raise ExpressionError(f"未対応の構文要素です: {ast.dump(node)}")


def evaluate(expr: str, facts: dict) -> bool:
    """条件式文字列を facts（入れ子dict）に対して評価し、bool を返す。

    facts は ``{"item": {...}, "company": {...}, "destination": {...},
    "transaction": {...}}`` のような入れ子辞書。式中の ``item.foo`` は
    ``facts["item"]["foo"]`` に対応する。

    Raises:
        ExpressionError: 構文エラー、未許可の構文、参照先フィールド欠落、
            型不一致の比較 など。
    """
    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"式の構文エラー: {expr!r} ({e})") from e

    _check_allowed(parsed)

    try:
        result = _eval(parsed, facts)
    except ExpressionError:
        raise
    except TypeError as e:
        raise ExpressionError(f"式の評価中に型エラー: {expr!r} ({e})") from e

    return bool(result)
