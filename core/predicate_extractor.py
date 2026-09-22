"""別表の1行（TableRow）を、号（一）〜（五十二）単位の"述語"（SubItem）に
分解し、末尾の除外節（例:「（四の項の中欄に掲げるものを除く。）」
「（（三十一）に掲げるものを除く。）」）を正規表現で機械的に抽出する
プロトタイプ。

原典XMLでは、各号はすでに個別の<Sentence>要素として分かれており
（項番号のブラケット「（一）」を含む先頭Sentenceと、それに続く
全角数字「１」「２」...で始まるネストした細目Sentenceがあれば
それも1つの号にまとめる）、自由テキストからの号切り出しは不要。

除外節は2種類に大別できる:
  - 他の項番号への参照（「四の項の中欄に掲げるものを除く。」）
    -> excludes_rows（load_table_rows()のrow_idと同じ採番規則で解決）
  - 同じ行内の他の号への参照（「（三十一）に掲げるものを除く。」）
    -> excludes_self_items（号の位取り漢数字で解決）
どちらのパターンにも一致しない除外節は raw_exclusion に生テキストのまま
残し、「機械的に解決できなかった」ことを明示する（無視して該当ありと
誤判定するより安全）。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

__all__ = ["SubItem", "SubItemMatch", "extract_subitems", "classify_subitems"]

_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                 "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _kanji_positional_to_int(s: str) -> Optional[int]:
    """号番号（一、十二、三十一、五十二 等）は位取り記数法。"""
    s = s.strip()
    if not s:
        return None
    result, current, seen = 0, 0, False
    for ch in s:
        if ch in _KANJI_DIGITS:
            current, seen = _KANJI_DIGITS[ch], True
        elif ch in "十百千":
            mult = {"十": 10, "百": 100, "千": 1000}[ch]
            current = current if seen else 1
            result += current * mult
            current, seen = 0, False
        else:
            return None
    result += current
    return result or None


def _kanji_digitseq_to_str(s: str) -> Optional[str]:
    """項番号（外側の別表の行番号）は一桁ずつ読む採番規則
    （load_table_rows()のrow_idと同じ）。"""
    s = s.strip()
    if not s:
        return None
    out = []
    for ch in s:
        if ch not in _KANJI_DIGITS:
            return None
        out.append(str(_KANJI_DIGITS[ch]))
    return str(int("".join(out)))


def _positional_label_to_id(label: str) -> Optional[str]:
    """号ラベル（'三十五の二' 等）を 'branch_to_id' 的にアンダースコア連結する。"""
    parts = label.split("の")
    nums = [_kanji_positional_to_int(p) for p in parts]
    if any(n is None for n in nums):
        return None
    return "_".join(str(n) for n in nums)


_LABEL_RE = re.compile(r"^（([一二三四五六七八九十]+(?:の[一二三四五六七八九十]+)?)）\s*(.*)$", re.S)
_NESTED_LINE_RE = re.compile(r"^[０-９0-9]+[　\s]")
_ROW_EXCLUSION_RE = re.compile(r"^([一二三四五六七八九十]+(?:及び[一二三四五六七八九十]+)*)の項の中欄に掲げるものを除く。$")


def _find_matching_open_paren(text: str, close_idx: int) -> Optional[int]:
    """text[close_idx] は '）'。対応する開き括弧 '（' の位置を、
    括弧の深さをカウントしながら後ろ向きに探す（ネスト対応）。"""
    depth = 0
    i = close_idx
    while i >= 0:
        if text[i] == "）":
            depth += 1
        elif text[i] == "（":
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return None


def _strip_trailing_exclusion(text: str) -> tuple[str, Optional[str]]:
    """文末の括弧が「〜を除く。」で終わる除外節であれば切り離す。
    括弧のネスト（例:「（（三十一）に掲げるものを除く。）」）に対応するため、
    単純な正規表現ではなく深さカウントで対応する開き括弧を探す。"""
    text = text.rstrip()
    if not text.endswith("）"):
        return text, None
    open_idx = _find_matching_open_paren(text, len(text) - 1)
    if open_idx is None:
        return text, None
    inner = text[open_idx + 1:-1]
    if not inner.endswith("除く。"):
        return text, None
    body = text[:open_idx].rstrip()
    if not body:
        return text, None
    return body, inner


@dataclass
class SubItem:
    label: str                      # 号の見出し（例: "四", "三十五の二"）
    item_id: str                    # ラベルを正規化したID（例: "4", "35_2"）
    text: str                       # 除外節を取り除いた実質テキスト（Jevに渡す）
    raw_text: str                   # 除外節を含む元テキスト
    excludes_rows: list[str] = field(default_factory=list)       # 除外対象の他項番号(row_id)
    excludes_self_items: list[str] = field(default_factory=list)  # 除外対象の同一行内の号(item_id)
    raw_exclusion: Optional[str] = None  # 機械的に解決できなかった除外節の原文

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "item_id": self.item_id,
            "text": self.text,
            "excludes_rows": self.excludes_rows,
            "excludes_self_items": self.excludes_self_items,
            "raw_exclusion": self.raw_exclusion,
        }


def _parse_exclusion(inner: str) -> tuple[list[str], list[str], Optional[str]]:
    """除外節の中身（'四の項の中欄に掲げるものを除く。' 等）を解析する。"""
    text = inner
    self_labels: list[str] = []

    while True:
        m = re.match(r"^（([一二三四五六七八九十]+(?:の[一二三四五六七八九十]+)?)）(及び)?", text)
        if not m:
            break
        self_labels.append(m.group(1))
        text = text[m.end():]

    row_labels: list[str] = []
    m = _ROW_EXCLUSION_RE.match(text)
    if m:
        row_labels = m.group(1).split("及び")
        text = ""
    elif self_labels and text in ("に掲げるものを除く。", ""):
        text = ""

    if text and text not in ("", "に掲げるものを除く。"):
        # 想定外のパターン（例:「一面釣合い試験機を除く。」等、項/号参照ではない除外）
        return (
            [rid for r in row_labels if (rid := _kanji_digitseq_to_str(r))],
            [iid for s in self_labels if (iid := _positional_label_to_id(s))],
            inner,
        )

    row_ids = [rid for r in row_labels if (rid := _kanji_digitseq_to_str(r))]
    self_ids = [iid for s in self_labels if (iid := _positional_label_to_id(s))]
    if not row_ids and not self_ids:
        return [], [], inner
    return row_ids, self_ids, None


def extract_subitems(xml_path: Path, row_label: str) -> list[SubItem]:
    """指定した行（row_label、例: "二"）を号単位に分解する。

    Args:
        xml_path: 別表を含む原典XMLファイルへのパス。
        row_label: 対象行の見出し漢数字（例: "二", "三の二"）。
            load_table_rows() の TableRow.label と同じ表記。
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    lawbody = root.find("LawBody")

    target_row = None
    for appdx in lawbody.findall("AppdxTable"):
        for table_row in appdx.findall(".//TableRow"):
            cols = table_row.findall("TableColumn")
            if not cols:
                continue
            label = "".join(s.text or "" for s in cols[0].iter("Sentence")).strip()
            if label == row_label:
                target_row = table_row
                break
        if target_row is not None:
            break
    if target_row is None:
        raise ValueError(f"行 {row_label!r} が見つかりません: {xml_path}")

    cols = target_row.findall("TableColumn")
    sentences = cols[1].findall(".//Sentence")

    subitems: list[SubItem] = []
    current_label: Optional[str] = None
    # 除外節はラベル行（号の先頭Sentence）の末尾に付くため、ネストした
    # 細目を連結する前の時点でラベル行だけに対して切り離す。
    current_body: str = ""
    current_raw_first_line: str = ""
    current_excl_rows: list[str] = []
    current_excl_self: list[str] = []
    current_raw_excl: Optional[str] = None
    current_nested_lines: list[str] = []

    def flush():
        if current_label is None:
            return
        text = (current_body + "".join(current_nested_lines)).strip()
        raw_text = (current_raw_first_line + "".join(current_nested_lines)).strip()
        if text == "削除":
            # 廃止済みの号。判定対象として意味がないため除外する。
            return
        item_id = _positional_label_to_id(current_label) or current_label
        subitems.append(SubItem(
            label=current_label, item_id=item_id, text=text, raw_text=raw_text,
            excludes_rows=current_excl_rows, excludes_self_items=current_excl_self,
            raw_exclusion=current_raw_excl,
        ))

    for s in sentences:
        text = (s.text or "").strip()
        if not text:
            continue
        m = _LABEL_RE.match(text)
        if m:
            flush()
            current_label = m.group(1)
            current_raw_first_line = m.group(2)
            current_body, excl_inner = _strip_trailing_exclusion(current_raw_first_line)
            if excl_inner is not None:
                current_excl_rows, current_excl_self, current_raw_excl = _parse_exclusion(excl_inner)
            else:
                current_excl_rows, current_excl_self, current_raw_excl = [], [], None
            current_nested_lines = []
        elif _NESTED_LINE_RE.match(text):
            # 号内のネストした細目（"１　..." "２　..." 等）。親の号にまとめる。
            current_nested_lines.append(re.sub(r"^[０-９0-9]+[　\s]", "", text))
        else:
            # 先頭行（「次に掲げる貨物であつて、...」等の号番号なしリード文）はスキップ
            continue

    flush()
    return subitems


@dataclass
class SubItemMatch:
    subitem: SubItem
    probability: float
    suppressed: bool = False
    suppressed_reason: Optional[str] = None
    needs_manual_review: bool = False  # raw_exclusion（機械的に解決できない除外節）がある場合

    def to_dict(self) -> dict:
        return {
            "label": self.subitem.label,
            "item_id": self.subitem.item_id,
            "probability": self.probability,
            "suppressed": self.suppressed,
            "suppressed_reason": self.suppressed_reason,
            "needs_manual_review": self.needs_manual_review,
        }


def classify_subitems(client, product_description: str, subitems: list[SubItem],
                       stage1_row_matches: Optional[dict] = None,
                       threshold: float = 0.5, model: Optional[str] = None,
                       ministerial_spec_text: Optional[str] = None,
                       kaishaku_interpretation=None) -> list[SubItemMatch]:
    """号単位でJev(Noul)に独立して問い合わせ、除外節（hard_rule）で
    機械的に抑制できるものは抑制した上で、確率降順に返す。

    Args:
        client: typesafe_sdk.TypeSafeClient。
        product_description: 判定対象の製品・技術の自然文説明。
        subitems: extract_subitems() で得た号のリスト。
        stage1_row_matches: {row_id: probability} 形式の、行レベル
            （classify_item()）の判定結果。excludes_rows の抑制判定に使う。
            省略時は行レベルの抑制チェックを行わない。
        threshold: 「該当」とみなす確率閾値。excludes_rows/excludes_self_items
            の抑制判定にも同じ閾値を用いる。
        model: TypeSafeのモデル名（省略時は既定）。
        ministerial_spec_text: 貨物等省令の対応条文全文
            （ministerial_spec_lookup.find_spec_for_row() で取得）。
            別表第一の号テキストだけでは「経済産業省令で定める仕様のもの」
            という委任先の具体的な数値基準（周波数・耐熱温度等）が分から
            ないため、指定した場合はJevへのstateに含めて判定材料とする。
            省略時は別表の号テキストのみで判定する（従来動作）。
        kaishaku_interpretation: kaishaku_lookup.find_interpretation_for_row()
            が返す RowInterpretation（運用通達別紙「輸出令別表第１の解釈」
            の、この行に対応する用語解釈一覧）。指定した場合、
            kaishaku_lookup.match_terms_for_text() で各号のテキストに
            実際に現れる用語だけを号ごとに絞り込み、その号自身の
            instructionsに個別に埋め込む（項全体をまとめて共有stateに
            入れると無関係な号に他の号の用語解釈が混入してノイズになる
            ため、号単位でマッチングする）。

    Returns:
        probability 降順の SubItemMatch のリスト。
    """
    from typesafe_sdk import Noul
    from .kaishaku_lookup import match_terms_for_text

    questions = {}
    for it in subitems:
        key = f"item_{it.item_id}"
        instructions = (
            f"次の製品・技術の説明は、下記の号（項の一部）が定める貨物・技術に該当するか。\n"
            f"【{it.label}】{it.text}"
        )
        if ministerial_spec_text:
            instructions += (
                "\n\nなお、この項は「経済産業省令で定める仕様のもの」という要件を含む場合があり、"
                "その具体的な数値基準はstateの ministerial_order_spec に記載されている。"
                "該当する記述があれば必ず参照して判定すること。"
            )
        if kaishaku_interpretation is not None:
            matched_terms = match_terms_for_text(kaishaku_interpretation, it.text)
            if matched_terms:
                instructions += "\n\nこの号で使われる用語の定義（運用通達別紙より）:"
                for td in matched_terms:
                    instructions += f"\n・「{td.term}」: {td.definition}"
        questions[key] = Noul(
            instructions=instructions,
            criteria={
                "true": f"製品説明が{it.label}の規定する範囲に含まれる",
                "false": f"製品説明は{it.label}の規定する範囲に含まれない",
            },
        )

    state: dict = {"product_description": product_description}
    if ministerial_spec_text:
        state["ministerial_order_spec"] = ministerial_spec_text

    kwargs = {"state": state, "questions": questions}
    if model:
        kwargs["model"] = model
    response = client.system_one(**kwargs)

    raw_probs: dict[str, float] = {}
    for it in subitems:
        answer = response.answers.get(f"item_{it.item_id}")
        raw_probs[it.item_id] = float(answer.noul) if answer is not None else 0.0

    stage1_row_matches = stage1_row_matches or {}
    results: list[SubItemMatch] = []
    for it in subitems:
        prob = raw_probs[it.item_id]
        suppressed, reason = False, None

        for rid in it.excludes_rows:
            row_prob = stage1_row_matches.get(rid)
            if row_prob is not None and row_prob >= threshold:
                suppressed = True
                reason = f"項{rid}にも該当（prob={row_prob:.2f} >= {threshold}）のため、除外規定によりこの号は非該当"
                break

        if not suppressed:
            for sid in it.excludes_self_items:
                sib_prob = raw_probs.get(sid)
                if sib_prob is not None and sib_prob >= threshold:
                    suppressed = True
                    reason = f"同一行内の号「{sid}」にも該当（prob={sib_prob:.2f} >= {threshold}）のため、除外規定によりこの号は非該当"
                    break

        results.append(SubItemMatch(
            subitem=it, probability=prob, suppressed=suppressed, suppressed_reason=reason,
            needs_manual_review=it.raw_exclusion is not None,
        ))

    results.sort(key=lambda r: r.probability, reverse=True)
    return results
