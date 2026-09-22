"""hybrid_jev ノードの判定を行うクライアント群。

``jurisdictions/jp/jev_prompts/*.jev.json`` は TypeSafe AI
(https://docs.typesafe.ai/) の Noul プリミティブ（yes/no を確率で返す
System One モデル ``jev-latest``）向けに書かれている。

- :class:`MockJevClient` — 実際のAPI呼び出しを行わず、プロンプト仕様に
  埋め込まれた ``evaluation_conditions``（ツリー本体の hard_rule 相当の
  条件式）を core.expr で直接評価する。APIキー不要で、決定木エンジン
  自体の分岐ロジックをテストするために使う。あくまで「プロンプト作成者が
  意図した条件」をなぞるだけで、Jevによる実際の自然言語判断の代わりには
  ならない。
- :class:`TypeSafeJevClient` — ``typesafe-sdk`` を使って実際に TypeSafe
  AI の ``system_one`` APIを呼び出す。``TYPESAFE_API_KEY`` 環境変数（また
  はコンストラクタ引数）が必要。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from . import expr as expr_mod

__all__ = ["JevClient", "MockJevClient", "TypeSafeJevClient", "JevClientError"]


class JevClientError(RuntimeError):
    pass


def _select_state(prompt_spec: dict, facts: dict) -> dict:
    """prompt_spec['state_fields'] で指定されたトップレベルキーだけを
    facts から抜き出す。Jevに渡すstateを、判定に無関係な情報を含めず
    最小限にするため。"""
    fields = prompt_spec.get("state_fields")
    if not fields:
        return facts
    state = {}
    for key in fields:
        if key in facts:
            state[key] = facts[key]
    return state


class JevClient(ABC):
    """hybrid_jev ノードの1問（Noul）を評価するクライアントの共通インタフェース。"""

    @abstractmethod
    def evaluate(self, prompt_spec: dict, facts: dict) -> dict:
        """prompt_spec（*.jev.json の内容）と facts（決定木に渡された
        入力全体）を受け取り、次の形の dict を返す:

            {
                "result": bool,       # Noul確率をdecision_thresholdで二値化した結果
                "probability": float, # Jevが返した生の確率値（0-1）。Mockではresultと同じ1.0/0.0
                "reasoning": str,     # 判定根拠の短い説明
                "next": str,          # prompt_spec['next_mapping'][branch] と一致するノード/結果ID
            }
        """


class MockJevClient(JevClient):
    """APIキー不要。プロンプト仕様の evaluation_conditions を
    core.expr で直接評価する決定的（非LLM）クライアント。"""

    def evaluate(self, prompt_spec: dict, facts: dict) -> dict:
        conditions = prompt_spec.get("evaluation_conditions")
        if not conditions:
            raise JevClientError(
                f"{prompt_spec.get('node_id')}: evaluation_conditions が定義されていません"
            )
        logic = prompt_spec.get("logic", "AND")
        values = [expr_mod.evaluate(c, facts) for c in conditions]
        result = all(values) if logic == "AND" else any(values)
        branch = "true" if result else "false"
        next_id = prompt_spec["next_mapping"][branch]
        return {
            "result": result,
            "probability": 1.0 if result else 0.0,
            "reasoning": (
                "MockJevClient: evaluation_conditions を直接評価（実際のJev呼び出しなし）。"
                f" logic={logic}, values={values}"
            ),
            "next": next_id,
        }


class TypeSafeJevClient(JevClient):
    """TypeSafe AI (https://docs.typesafe.ai/) の system_one API を使い、
    prompt_spec['question']（type: "noul"）を実際にJevへ問い合わせる。

    使い方::

        from typesafe_sdk import TypeSafeClient
        client = TypeSafeJevClient()  # 環境変数 TYPESAFE_API_KEY を使用
        result = client.evaluate(prompt_spec, facts)
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 base_url: Optional[str] = None):
        try:
            from typesafe_sdk import Noul, TypeSafeClient
        except ImportError as e:
            raise JevClientError(
                "typesafe-sdk がインストールされていません。"
                "`pip install typesafe-sdk` を実行するか、"
                "MockJevClient を使ってください。"
            ) from e

        self._Noul = Noul
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        try:
            self._client = TypeSafeClient(**kwargs)
        except Exception as e:
            raise JevClientError(
                "TypeSafeClient の初期化に失敗しました。"
                "TYPESAFE_API_KEY 環境変数（または api_key 引数）を確認してください。"
                f" ({e})"
            ) from e
        self._default_model = model

    def evaluate(self, prompt_spec: dict, facts: dict) -> dict:
        question_spec = prompt_spec.get("question")
        if not question_spec or question_spec.get("type") != "noul":
            raise JevClientError(
                f"{prompt_spec.get('node_id')}: question.type が 'noul' の"
                " プロンプト仕様のみサポートしています"
            )

        state = _select_state(prompt_spec, facts)
        key = question_spec.get("key", "applies")
        model = prompt_spec.get("model") or self._default_model or "jev-latest"

        questions = {
            key: self._Noul(
                instructions=question_spec["instructions"],
                criteria=question_spec.get("criteria"),
            )
        }

        try:
            call_kwargs: dict[str, Any] = {"state": state, "questions": questions}
            response = self._client.system_one(model=model, **call_kwargs)
        except TypeError:
            # SDKのバージョンによっては system_one が model キーワードを
            # 受け付けない場合があるため、model指定なしで再試行する。
            response = self._client.system_one(state=state, questions=questions)
        except Exception as e:
            raise JevClientError(f"TypeSafe API呼び出しに失敗しました: {e}") from e

        try:
            probability = float(response.answers[key].noul)
        except (AttributeError, KeyError) as e:
            raise JevClientError(
                f"TypeSafeのレスポンスから noul 値を取得できませんでした: {e}"
            ) from e

        threshold = prompt_spec.get("decision_threshold", 0.5)
        result = probability >= threshold
        branch = "true" if result else "false"
        next_id = prompt_spec["next_mapping"][branch]

        return {
            "result": result,
            "probability": probability,
            "reasoning": (
                f"TypeSafe Jev(noul)={probability:.3f} "
                f"(threshold={threshold}) -> {branch}"
            ),
            "next": next_id,
        }
