"""law-as-code-fefta の決定木（jurisdictions/jp/processed/*_tree.json）を
root から終端の results エントリまで辿る実行エンジン。

- ``evaluator: "hard_rule"`` ノードは core.expr で直接評価する。
- ``evaluator: "hybrid_jev"`` ノードは対応する
  ``jurisdictions/jp/jev_prompts/{node_id}.jev.json`` を読み込み、
  渡された :class:`~core.jev_client.JevClient` に判定を委譲する。

全ステップの通過記録（トレース）を保持するため、判定結果に至った経緯を
人間が事後検証できる。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import expr as expr_mod
from .jev_client import JevClient, MockJevClient

REPO_ROOT = Path(__file__).resolve().parent.parent
JEV_PROMPTS_DIR = REPO_ROOT / "jurisdictions/jp/jev_prompts"
TREES_DIR = REPO_ROOT / "jurisdictions/jp/processed"

__all__ = [
    "TreeEngineError",
    "TraceStep",
    "EngineResult",
    "load_tree",
    "load_tree_by_name",
    "load_jev_prompt",
    "run_tree",
]


class TreeEngineError(RuntimeError):
    pass


@dataclass
class TraceStep:
    node_id: str
    title: Optional[str]
    evaluator: str
    expression: Optional[str]
    value: Any
    branch: str
    next_id: str
    jev_detail: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "evaluator": self.evaluator,
            "expression": self.expression,
            "value": self.value,
            "branch": self.branch,
            "next_id": self.next_id,
            "jev_detail": self.jev_detail,
        }


@dataclass
class EngineResult:
    tree_id: str
    trace: list[TraceStep] = field(default_factory=list)
    result_id: str = ""
    result_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tree_id": self.tree_id,
            "trace": [s.to_dict() for s in self.trace],
            "result_id": self.result_id,
            "result_data": self.result_data,
        }

    def pretty_print(self) -> str:
        lines = [f"=== {self.tree_id} ==="]
        for step in self.trace:
            expr_part = f" [{step.expression}]" if step.expression else ""
            title_part = f" {step.title}" if step.title else ""
            lines.append(
                f"- {step.node_id}{title_part} ({step.evaluator}){expr_part}"
                f" = {step.value} --{step.branch}--> {step.next_id}"
            )
            if step.jev_detail:
                lines.append(f"    jev: {step.jev_detail.get('reasoning')}")
        lines.append(f"=== RESULT: {self.result_id} ===")
        lines.append(json.dumps(self.result_data, ensure_ascii=False, indent=2))
        return "\n".join(lines)


def load_tree(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_tree_by_name(name: str) -> dict:
    """例: load_tree_by_name("inclusive_license_tree") で
    jurisdictions/jp/processed/inclusive_license_tree.json を読み込む。"""
    path = TREES_DIR / f"{name}.json"
    if not path.exists():
        raise TreeEngineError(f"ツールファイルが見つかりません: {path}")
    return load_tree(path)


def load_jev_prompt(node_id: str) -> dict:
    path = JEV_PROMPTS_DIR / f"{node_id}.jev.json"
    if not path.exists():
        raise TreeEngineError(f"Jevプロンプトが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _evaluate_hard_rule(node: dict, node_id: str, facts: dict) -> tuple[Any, str]:
    """hard_rule ノードを評価し、(評価値, 表示用の式文字列) を返す。"""
    if "check_property" in node:
        prop = node["check_property"]
        value = bool(expr_mod.evaluate(f"{prop} == true", facts))
        return value, f"{prop} == true"

    if "condition" in node:
        cond = node["condition"]
        return expr_mod.evaluate(cond, facts), cond

    if "conditions" in node:
        conditions = node["conditions"]
        logic = node.get("logic", "AND")
        values = [expr_mod.evaluate(c, facts) for c in conditions]
        value = all(values) if logic == "AND" else any(values)
        expr_str = f" {logic} ".join(conditions)
        return value, expr_str

    raise TreeEngineError(f"ノード {node_id} に評価可能な条件がありません")


def run_tree(tree: dict, facts: dict, jev_client: Optional[JevClient] = None,
             max_steps: int = 100) -> EngineResult:
    """決定木を root から辿り、終端の results に到達するまで評価する。

    Args:
        tree: load_tree()/load_tree_by_name() で読み込んだツリー定義。
        facts: 判定対象の入力データ（例: {"item": {...}, "company": {...},
            "destination": {...}, "transaction": {...}}）。
        jev_client: hybrid_jev ノードの判定に使うクライアント。省略時は
            MockJevClient（APIキー不要、ツリー自身のconditionsで判定）。
        max_steps: 循環参照等による無限ループを防ぐ上限ステップ数。

    Returns:
        EngineResult: 通過した全ノードのトレースと最終結果。

    Raises:
        TreeEngineError: 未知のノード参照、循環参照、未対応のevaluator、
            hybrid_jevの応答とツリー定義のnext不一致など。
    """
    jev_client = jev_client or MockJevClient()
    nodes = tree["nodes"]
    results = tree["results"]

    current_id = "root"
    trace: list[TraceStep] = []
    visited: set[str] = set()

    for _ in range(max_steps):
        if current_id in results:
            return EngineResult(
                tree_id=tree["tree_id"],
                trace=trace,
                result_id=current_id,
                result_data=results[current_id],
            )

        if current_id not in nodes:
            raise TreeEngineError(f"未知のノードIDへの遷移です: {current_id}")
        if current_id in visited:
            raise TreeEngineError(f"循環参照を検出しました（{current_id} に再訪問）")
        visited.add(current_id)

        node = nodes[current_id]
        node_id = node.get("id", current_id)
        evaluator = node["evaluator"]

        if evaluator == "hard_rule":
            value, expr_str = _evaluate_hard_rule(node, node_id, facts)
            branch = "true" if value else "false"
            if branch not in node["next"]:
                raise TreeEngineError(f"ノード {node_id} の next に {branch} 分岐がありません")
            next_id = node["next"][branch]
            trace.append(TraceStep(node_id, node.get("title"), evaluator, expr_str, value, branch, next_id))
            current_id = next_id
            continue

        if evaluator == "hybrid_jev":
            prompt_spec = load_jev_prompt(node_id)
            jev_result = jev_client.evaluate(prompt_spec, facts)
            branch = "true" if jev_result["result"] else "false"
            expected_next = node["next"][branch]
            next_id = jev_result.get("next", expected_next)
            if next_id != expected_next:
                raise TreeEngineError(
                    f"ノード {node_id}: Jevの応答next({next_id!r}) がツリー定義の"
                    f" next({expected_next!r}) と不一致です"
                )
            expr_display = node.get("jev_context_prompt") or "; ".join(node.get("conditions", []))
            trace.append(TraceStep(
                node_id, node.get("title"), evaluator, expr_display,
                jev_result.get("probability", jev_result["result"]),
                branch, next_id, jev_detail=jev_result,
            ))
            current_id = next_id
            continue

        raise TreeEngineError(f"未対応のevaluatorです: {evaluator!r} (node={node_id})")

    raise TreeEngineError(f"max_steps({max_steps})を超過しました。循環参照の疑いがあります。")
