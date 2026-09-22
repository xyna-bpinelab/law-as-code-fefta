"""運用通達の別紙PDF（例: kamotsu-kaishaku.pdf =「輸出令別表第１の解釈」）
から、別表第一の特定の項に対応する用語解釈を抽出するプロトタイプ。

このPDFは「項番号｜解釈を要する語｜解釈」という3列の表。(用語, 解釈) の
行単位ペアリング自体はpdfplumberのfind_tables()で座標ベースに正確に
取得できるが、項番号セルは各項の最初の行にしか値が入らない縦結合セルで、
複数ページにまたがるため、項番号列だけは別途、座標ベースで出現位置
（ページ・Y座標）を検出し、「ある項番号の出現位置から次の項番号の出現
位置の直前まで」に含まれる (用語, 解釈) 行を、その項の用語解釈として
まとめる。

さらに、号（SubItem）単位でJevに渡す際は、項全体の用語解釈をまとめて
渡すのではなく、各号のテキストに実際に現れる用語だけを紐付ける
（match_terms_for_text）。これにより、無関係な号に他の号の用語解釈が
混入してノイズになる問題を避ける。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

__all__ = [
    "TermDefinition", "RowInterpretation",
    "find_interpretation_for_row", "match_terms_for_text",
    "kanji_row_label_to_zenkaku",
]

_ROW_NUM_RE = re.compile(r"^[０-９]{1,3}(の[０-９]{1,2})?$")
_ROW_NUM_COL_X0, _ROW_NUM_COL_X1 = 30, 100
_HEADER_MARKERS = ("解釈を要する語", "解 釈 を 要 す る 語")

_KANJI_DIGITS_TO_ARABIC = {"〇": "0", "一": "1", "二": "2", "三": "3", "四": "4",
                            "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
_ZENKAKU_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


def kanji_row_label_to_zenkaku(label: str) -> str:
    """list_classifier.TableRow.label の漢数字表記（例: "九", "三の二"）を、
    kaishaku PDF側で使われる全角数字表記（例: "９", "３の２"）に変換する。
    位取り記数法（十/百）は使わず、桁ごとに読み替える簡易変換
    （別表第一の項番号は1桁または「十◯」形式のみのため、
    ここでは単純な1桁変換で十分な範囲に限定する）。変換不能な場合は
    入力をそのまま返す（呼び出し側でNOT FOUND扱いになる）。"""
    parts = label.split("の")
    out_parts = []
    for p in parts:
        if p and all(ch in _KANJI_DIGITS_TO_ARABIC for ch in p):
            out_parts.append("".join(_KANJI_DIGITS_TO_ARABIC[ch] for ch in p).translate(_ZENKAKU_DIGITS))
        else:
            return label
    return "の".join(out_parts)


@dataclass
class TermDefinition:
    term: str
    definition: str


@dataclass
class RowInterpretation:
    row_label: str                              # 全角数字表記（例: "９", "３の２"）
    start_page: int                              # 0-indexed
    end_page: int                                # 0-indexed
    terms: list[TermDefinition] = field(default_factory=list)

    @property
    def text(self) -> str:
        """全用語解釈をまとめたテキスト（後方互換・デバッグ用）。"""
        return "\n".join(f"【{t.term}】{t.definition}" for t in self.terms)


def _header_bottom(page) -> float:
    bottom = 0.0
    for w in page.extract_words():
        if w["text"] == "項" and w["x0"] < _ROW_NUM_COL_X1:
            bottom = max(bottom, w["bottom"])
    return bottom


def _find_row_number_positions(pdf) -> list[tuple[int, float, str]]:
    positions = []
    for page_index, page in enumerate(pdf.pages):
        header_bottom = _header_bottom(page)
        for w in page.extract_words():
            if (_ROW_NUM_COL_X0 <= w["x0"] <= _ROW_NUM_COL_X1
                    and w["top"] > header_bottom + 2
                    and _ROW_NUM_RE.match(w["text"])):
                positions.append((page_index, w["top"], w["text"]))
    return positions


def _crop_text(page, bbox) -> str:
    if bbox is None:
        return ""
    return (page.crop(bbox).extract_text() or "").replace("\n", "").strip()


def _extract_term_rows(page) -> list[tuple[float, str, str]]:
    """ページ内の (top, term, definition) を行順に返す。
    見出し行・完全に空の行は除外する。用語欄が空の行（解釈が前の用語の
    続きでページをまたいだ場合）は term="" のまま返し、呼び出し側で
    直前のエントリに結合する。"""
    records = []
    for table in page.find_tables():
        for row in table.rows:
            cells = row.cells
            if len(cells) < 3:
                continue
            tops = [c[1] for c in cells if c is not None]
            if not tops:
                continue
            top = min(tops)
            term = _crop_text(page, cells[1])
            defn = _crop_text(page, cells[2])
            if len(cells) > 3:
                defn += _crop_text(page, cells[3])
            if any(marker in term or marker in defn for marker in _HEADER_MARKERS):
                continue
            if not term and not defn:
                continue
            records.append((top, term, defn))
    return records


def find_interpretation_for_row(pdf_path: Path, row_label: str) -> Optional[RowInterpretation]:
    """row_label（全角数字表記。例: "９"）に対応する用語解釈のリストを抽出する。

    注意: kaishaku PDFの項番号は全角数字表記であり、
    list_classifier.TableRow.label の漢数字表記（例: "九"）とは異なる。
    呼び出し側で変換すること（scripts/classify_predicates.py 参照）。
    """
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        positions = _find_row_number_positions(pdf)
        matches = [i for i, (_, _, label) in enumerate(positions) if label == row_label]
        if not matches:
            return None
        idx = matches[0]
        start_page, start_top, _ = positions[idx]
        if idx + 1 < len(positions):
            end_page, end_top, _ = positions[idx + 1]
        else:
            end_page, end_top = len(pdf.pages) - 1, None

        # 項番号セルの文字は、同じ行内の用語欄よりもわずかに下寄りに
        # 配置されることがある（実データで最大10pt程度のずれを確認）ため、
        # 境界に許容誤差を設けて同じ行を取りこぼさないようにする。
        margin = 15.0

        terms: list[TermDefinition] = []
        for page_index in range(start_page, end_page + 1):
            page = pdf.pages[page_index]
            top_bound = (start_top - margin) if page_index == start_page else _header_bottom(page)
            bottom_bound = (end_top - margin) if (page_index == end_page and end_top is not None) else page.height

            for top, term, defn in _extract_term_rows(page):
                if not (top_bound - 1 <= top <= bottom_bound + 1):
                    continue
                if term:
                    terms.append(TermDefinition(term=term, definition=defn))
                elif terms:
                    # 用語欄が空 = 直前の用語の解釈がページをまたいで続いている
                    terms[-1].definition += defn

        return RowInterpretation(row_label=row_label, start_page=start_page, end_page=end_page, terms=terms)


def match_terms_for_text(row_interpretation: RowInterpretation, text: str) -> list[TermDefinition]:
    """text（号の実質テキスト）に関連する用語解釈だけを抽出する。

    用語が号テキストの部分文字列である場合（例: 号「伝送通信装置又は…」
    に用語「伝送通信装置」）、または逆に号テキストが用語の部分文字列で
    ある場合（例: 号「フェーズドアレーアンテナ」に用語「電子的に走査が
    可能なフェーズドアレーアンテナ」）の双方向で判定する。
    """
    if not text:
        return []
    matched = []
    for td in row_interpretation.terms:
        if not td.term:
            continue
        if td.term in text or text in td.term:
            matched.append(td)
    return matched
