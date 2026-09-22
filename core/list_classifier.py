"""自然文の製品説明から、輸出貿易管理令 別表第一のどの項番に該当し得るかを
複数該当ありきで判定するプロトタイプ。

``Choice`` プリミティブは「N択から1つを選ぶ」設計（確率の合計が1になる）
のため、1つの製品が複数の項番に同時に該当し得るケースには向かない。
代わりに項番ごとに独立した ``Noul``（yes/no確率）質問を1回のAPI呼び出しに
まとめて投げ、各項番の該当確率を個別に得る（他の項番の確率と無関係に
0〜1をとるため、複数項番が同時にtrueと判定されてもよい）。

これは実運用の該非判定を代替するものではなく、一次スクリーニングの
プロトタイプ。低いconfidence/僅差の複数該当は必ず人間の該非判定担当者の
確認に回すこと。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# 別表第一の各行の説明テキストは長大（数百〜数千字）なため、
# Noulのinstructionsに含める際はこの文字数で切り詰める。
DESCRIPTION_TRUNCATE_CHARS = 500


@dataclass
class TableRow:
    row_id: str  # 例: "1", "13_2"（十三の二）
    label: str   # 元の行見出し文字（漢数字表記。例: "一", "十三の二"）
    description: str  # 切り詰め済みの本文
    full_length: int  # 切り詰め前の元の文字数（参考情報）


_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                 "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _kanji_digitseq_to_str(s: str) -> Optional[str]:
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return str(int(s))
    out = []
    for ch in s:
        if ch not in _KANJI_DIGITS:
            return None
        out.append(str(_KANJI_DIGITS[ch]))
    return str(int("".join(out)))


def _row_id_from_label(label: str) -> Optional[str]:
    parts = label.split("の")
    nums = [_kanji_digitseq_to_str(p) for p in parts]
    if any(n is None for n in nums):
        return None
    return "_".join(nums)


def load_table_rows(xml_path: Path, table_title: str = "別表第一") -> list[TableRow]:
    """輸出令等のAppdxTable(別表)から、番号付き行だけを抽出する
    （見出し行など番号化できない行は除外する）。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    lawbody = root.find("LawBody")

    target = None
    for t in lawbody.findall("AppdxTable"):
        title_el = t.find("AppdxTableTitle")
        if title_el is not None and (title_el.text or "").strip() == table_title:
            target = t
            break
    if target is None:
        raise ValueError(f"{xml_path} に {table_title!r} が見つかりません")

    rows: list[TableRow] = []
    for table_row in target.findall(".//TableRow"):
        cols = table_row.findall("TableColumn")
        if len(cols) < 2:
            continue
        label = "".join(s.text or "" for s in cols[0].iter("Sentence")).strip()
        row_id = _row_id_from_label(label)
        if row_id is None:
            continue  # 見出し行（"貨物"「地域」等）はスキップ
        full_text = "".join(s.text or "" for s in cols[1].iter("Sentence")).strip()
        description = full_text[:DESCRIPTION_TRUNCATE_CHARS]
        rows.append(TableRow(row_id=row_id, label=label, description=description, full_length=len(full_text)))

    return rows


@dataclass
class RowMatch:
    row: TableRow
    probability: float

    def to_dict(self) -> dict:
        return {
            "row_id": self.row.row_id,
            "label": self.row.label,
            "probability": self.probability,
        }


def classify_item(client, product_description: str, rows: list[TableRow],
                   threshold: float = 0.5, model: Optional[str] = None) -> list[RowMatch]:
    """product_description が rows の各項番にどれだけ該当し得るかを、
    1回のsystem_one呼び出しで行ごと独立に(Noul)判定する。

    複数の項番が同時にthreshold以上となり得る（該当複数）。

    Args:
        client: typesafe_sdk.TypeSafeClient（またはこれと互換のオブジェクト）。
        product_description: 判定対象の製品・技術の自然文説明。
        rows: load_table_rows() で得た候補行のリスト。
        threshold: この確率以上を「該当」として扱う閾値。
        model: TypeSafeのモデル名（省略時はクライアント既定 = jev-latest）。

    Returns:
        rows と同じ順序ではなく、probability降順に並べた RowMatch のリスト
        （全件を返す。閾値以上かどうかは呼び出し側が RowMatch.probability
        で判断する）。
    """
    from typesafe_sdk import Noul

    questions = {}
    for row in rows:
        key = f"row_{row.row_id}"
        questions[key] = Noul(
            instructions=(
                f"次の製品・技術の説明は、輸出貿易管理令別表第一の"
                f"{row.label}の項に掲げる貨物・技術に該当するか。\n"
                f"【{row.label}の項の規定】{row.description}"
                + ("...(以下略、原文はさらに長い)" if row.full_length > len(row.description) else "")
            ),
            criteria={
                "true": f"製品説明が{row.label}の項の規定する範囲に含まれる",
                "false": f"製品説明は{row.label}の項の規定する範囲に含まれない",
            },
        )

    kwargs = {"state": {"product_description": product_description}, "questions": questions}
    if model:
        kwargs["model"] = model
    response = client.system_one(**kwargs)

    matches = []
    for row in rows:
        key = f"row_{row.row_id}"
        answer = response.answers.get(key)
        probability = float(answer.noul) if answer is not None else 0.0
        matches.append(RowMatch(row=row, probability=probability))

    matches.sort(key=lambda m: m.probability, reverse=True)
    return matches
