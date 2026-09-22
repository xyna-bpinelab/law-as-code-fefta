"""貨物等省令・別表条文の条文テキストから、数値仕様の判定条件（周波数・
温度・速度等の「〜以上」「〜を超える」等の閾値表現）を機械的に抽出し、
Stage3（ユーザーが実測値を入力して最終該非判定を行う画面）向けの
構造化された質問項目（SpecCriterion）に変換するプロトタイプ。

条文の数値表記には3種類の記数法が混在する:
  - 半角/全角アラビア数字（例: "500メガヘルツ", "０．１ワット"）
  - 位取り漢数字（例: "三十二ビット" = 32、十/百/千を含む）
  - 数字列漢数字（例: "五六ビット" = 56、"五一二ビット" = 512。
    十/百/千を含まない場合はこちらとして解釈する）
  - 「零下」接頭辞は符号反転（例: "零下５５度より低い" = 摂氏-55度未満）

抽出できなかった行（数値基準を含まない、または未対応のパターン）は
resolved=False の質問項目として返し、ユーザーが原文を読んで直接
該当/非該当を判断できるようにする（machine-parsed as best-effort;
never silently drop a clause — predicate_extractor.py の
raw_exclusion/needs_manual_review と同じ設計方針）。

同一行内に複数の数値条件が含まれる場合（例:「１から３までの全てに
該当」の各項目とは別に、1行に閾値が複数出現するケース）は、それぞれを
独立した SpecCriterion として抽出する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

__all__ = ["SpecCriterion", "extract_spec_criteria", "evaluate_criterion"]

_KANJI_DIGIT_MAP = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                     "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_MULT = {"十": 10, "百": 100, "千": 1000}

_ZENKAKU_ARABIC = "０１２３４５６７８９"
_HANKAKU_ARABIC = "0123456789"
_ARABIC_TRANS = str.maketrans(_ZENKAKU_ARABIC + "．", _HANKAKU_ARABIC + ".")

_NUM_TOKEN_RE = r'(?:[0-9０-９]+(?:[.．][0-9０-９]+)?|[〇一二三四五六七八九十百千]+)'
_UNIT_RE = r'[^\s、。0-9０-９]{0,14}?'


def _parse_kanji_positional(s: str) -> Optional[int]:
    result, current, seen = 0, 0, False
    for ch in s:
        if ch in _KANJI_DIGIT_MAP:
            current, seen = _KANJI_DIGIT_MAP[ch], True
        elif ch in _KANJI_MULT:
            current = current if seen else 1
            result += current * _KANJI_MULT[ch]
            current, seen = 0, False
        else:
            return None
    result += current
    return result or None


def _parse_kanji_digitseq(s: str) -> Optional[int]:
    out = []
    for ch in s:
        if ch not in _KANJI_DIGIT_MAP:
            return None
        out.append(str(_KANJI_DIGIT_MAP[ch]))
    return int("".join(out))


def _parse_number(token: str) -> Optional[float]:
    token = token.strip()
    if not token:
        return None
    if re.fullmatch(r'[0-9０-９]+(?:[.．][0-9０-９]+)?', token):
        return float(token.translate(_ARABIC_TRANS))
    if re.fullmatch(r'[〇一二三四五六七八九十百千]+', token):
        if any(c in _KANJI_MULT for c in token):
            v = _parse_kanji_positional(token)
        else:
            v = _parse_kanji_digitseq(token)
        return float(v) if v is not None else None
    return None


# (比較演算子を表す条文フレーズの正規表現, comparator記号, 零下接頭辞を許容するか)
_COMPARATOR_PATTERNS: list[tuple[str, str]] = [
    (r'以上', '>='),
    (r'を超えない', '<='),
    (r'を超える', '>'),
    (r'超のもの', '>'),
    (r'超える', '>'),
    (r'以下', '<='),
    (r'以内', '<='),
    (r'未満', '<'),
    (r'より低い', '<'),
    (r'より小さい', '<'),
    (r'より高い', '>'),
    (r'より大きい', '>'),
]

# 「零下NN度より低い」のように接頭辞が符号を反転させるケース
_ZERO_KA_RE = re.compile(rf'零下\s*({_NUM_TOKEN_RE})\s*({_UNIT_RE})\s*(以上|以下|未満|より低い|より高い|を超える)')

_PATTERNS = [
    re.compile(rf'({_NUM_TOKEN_RE})\s*({_UNIT_RE})\s*{phrase}')
    for phrase, _sym in _COMPARATOR_PATTERNS
]


@dataclass
class SpecCriterion:
    raw_line: str                    # 抽出元の条文行（原文まま。ユーザーへの参照表示用）
    resolved: bool                   # 数値条件として機械的に解釈できたか
    parameter_label: Optional[str] = None  # 例: "周波数"（ベストエフォート）
    comparator: Optional[str] = None       # ">=", "<=", ">", "<" のいずれか
    threshold: Optional[float] = None
    unit: Optional[str] = None
    matched_text: Optional[str] = None     # 原文中でマッチした数値条件の部分文字列

    def to_dict(self) -> dict:
        return {
            "raw_line": self.raw_line,
            "resolved": self.resolved,
            "parameter_label": self.parameter_label,
            "comparator": self.comparator,
            "threshold": self.threshold,
            "unit": self.unit,
            "matched_text": self.matched_text,
        }


def _derive_parameter_label(line: str, match_start: int) -> Optional[str]:
    """マッチ開始位置より前のテキストから、判定対象量の名称を推定する
    （「周波数が」「〜の長さが」等の直前の名詞句、ベストエフォート）。"""
    prefix = line[:match_start]
    # 直前の読点・かぎ括弧・開き括弧・全角スペース（イロハ等の枝番号の後）までを候補とする
    segment = re.split(r'[、。（　]', prefix)[-1]
    segment = re.sub(r'(が|は|で|の場合において|であって)$', '', segment).strip()
    if not segment or len(segment) > 20 or len(segment) <= 1:
        return None
    return segment


# 「０．１ワット（２０ディービーエム）以下」のような、主たる数値の直後に
# 別単位換算値だけを示す注釈括弧が続くケース。括弧の中身が数値と単位だけ
# （NUM+UNITのみ）であれば、除外節のような実質的な条件ではなく単なる
# 単位注釈と判断し、抽出前に取り除く（そうしないと括弧内の数値を主たる
# 閾値と誤認識してしまう）。
_UNIT_ANNOTATION_PAREN_RE = re.compile(rf'（{_NUM_TOKEN_RE}{_UNIT_RE}）')


def _strip_unit_annotation_parens(line: str) -> str:
    return _UNIT_ANNOTATION_PAREN_RE.sub('', line)


def _extract_from_line(line: str) -> list[SpecCriterion]:
    original_line = line
    line = _strip_unit_annotation_parens(line)
    spans: list[tuple[int, int, str, float, str, str]] = []  # start,end,comparator,threshold,unit,matched_text

    m = _ZERO_KA_RE.search(line)
    zero_ka_span = None
    if m:
        num_token, unit_token, phrase = m.group(1), m.group(2), m.group(3)
        value = _parse_number(num_token)
        if value is not None:
            symbol = next((sym for p, sym in _COMPARATOR_PATTERNS if re.fullmatch(p, phrase) or phrase == p), None)
            # "零下NN度より低い" 等は絶対値としては閾値未満だが符号反転するため方向は変わらない
            spans.append((m.start(), m.end(), symbol or '<', -value, unit_token.strip(), m.group(0)))
            zero_ka_span = (m.start(), m.end())

    for pattern, (phrase, symbol) in zip(_PATTERNS, _COMPARATOR_PATTERNS):
        for mm in pattern.finditer(line):
            if zero_ka_span and not (mm.end() <= zero_ka_span[0] or mm.start() >= zero_ka_span[1]):
                continue  # 零下パターンと重複する範囲はスキップ（二重カウント防止）
            num_token, unit_token = mm.group(1), mm.group(2)
            value = _parse_number(num_token)
            if value is None:
                continue
            spans.append((mm.start(), mm.end(), symbol, value, unit_token.strip(), mm.group(0)))

    if not spans:
        return [SpecCriterion(raw_line=original_line, resolved=False)]

    # 開始位置でソートし、重複するスパンは除去（先勝ち）
    spans.sort(key=lambda s: s[0])
    selected: list[tuple[int, int, str, float, str, str]] = []
    for span in spans:
        if selected and span[0] < selected[-1][1]:
            continue
        selected.append(span)

    criteria = []
    for start, end, comparator, threshold, unit, matched_text in selected:
        criteria.append(SpecCriterion(
            raw_line=original_line, resolved=True,
            parameter_label=_derive_parameter_label(line, start),
            comparator=comparator, threshold=threshold, unit=unit or None,
            matched_text=matched_text,
        ))
    return criteria


def extract_spec_criteria(lines: list[str]) -> list[SpecCriterion]:
    """条文行（号の本文、または貨物等省令の枝番テキスト各行）のリストから、
    数値仕様の判定条件を抽出する。1行から複数条件が抽出される場合もある。
    数値条件を含まない行は resolved=False の1件として返す（原文をそのまま
    ユーザーに提示し、手動判定を促すため）。
    """
    criteria: list[SpecCriterion] = []
    for line in lines:
        line = line.strip()
        if not line or line in ("削除", "（削る）"):
            continue
        criteria.extend(_extract_from_line(line))
    return criteria


def evaluate_criterion(criterion: SpecCriterion, value) -> Optional[bool]:
    """ユーザー入力値に対して、この条件を満たすかどうかを判定する。
    resolved=False の場合、value はユーザーが直接下した true/false 判断
    としてそのまま返す。value が None（未入力）の場合は None（未判定）。"""
    if value is None or value == "":
        return None
    if not criterion.resolved:
        return bool(value)
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    if criterion.comparator == '>=':
        return numeric_value >= criterion.threshold
    if criterion.comparator == '<=':
        return numeric_value <= criterion.threshold
    if criterion.comparator == '>':
        return numeric_value > criterion.threshold
    if criterion.comparator == '<':
        return numeric_value < criterion.threshold
    return None
