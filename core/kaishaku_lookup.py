"""運用通達の別紙PDF（例: kamotsu-kaishaku.pdf =「輸出令別表第１の解釈」）
から、別表第一の特定の項に対応する用語解釈のまとまりを抽出するプロトタイプ。

このPDFは「項番号｜解釈を要する語｜解釈」という3列の表だが、
  - 項番号セルは各項の最初の行にしか値が入らない縦結合セルで、
    複数ページにまたがることがある
  - 列の罫線構成がページによって微妙に異なる（解釈列が1列のページと
    2列に分かれているように見えるページがある）
ため、行単位で「項番号｜用語｜解釈」を完全に構造化するのは頑健性の面で
リスクが高い。

そこで本プロトタイプでは、項番号セル（x座標がページ左端の項番号列の
範囲内にあり、かつ全角数字＋枝番のみのテキスト）の出現位置
（ページ番号・Y座標）を機械的に検出し、「ある項番号の出現位置から
次の項番号の出現位置の直前まで」のテキスト全体を、その項に対応する
用語解釈のまとまりとして抽出する。用語単位への分割は行わず、
まとまったテキストをJevへの追加コンテキストとして渡す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

__all__ = ["RowInterpretation", "find_interpretation_for_row"]

_ROW_NUM_RE = re.compile(r"^[０-９]{1,3}(の[０-９]{1,2})?$")
_ROW_NUM_COL_X0, _ROW_NUM_COL_X1 = 30, 100


@dataclass
class RowInterpretation:
    row_label: str       # 全角数字表記（例: "９", "３の２"）
    start_page: int       # 0-indexed
    end_page: int          # 0-indexed（この項の最後のテキストを含むページ）
    text: str              # 項番号自身の表記を除いた、用語・解釈のまとまりテキスト


def _header_bottom(page) -> float:
    """各ページ冒頭に繰り返される見出し「輸出令別表第１の項...」の下端Yを返す。
    見出しが無いページ（表の続きだけのページ）では0を返す。"""
    bottom = 0.0
    for w in page.extract_words():
        if w["text"] == "項" and w["x0"] < _ROW_NUM_COL_X1:
            bottom = max(bottom, w["bottom"])
    return bottom


def _find_row_number_positions(pdf) -> list[tuple[int, float, str]]:
    """(page_index, top, row_label) のリストを、PDF全体から出現順に返す。"""
    positions = []
    for page_index, page in enumerate(pdf.pages):
        header_bottom = _header_bottom(page)
        for w in page.extract_words():
            if (_ROW_NUM_COL_X0 <= w["x0"] <= _ROW_NUM_COL_X1
                    and w["top"] > header_bottom + 2
                    and _ROW_NUM_RE.match(w["text"])):
                positions.append((page_index, w["top"], w["text"]))
    return positions


def find_interpretation_for_row(pdf_path: Path, row_label: str,
                                 max_chars: int = 6000) -> Optional[RowInterpretation]:
    """row_label（例: "九" ではなく全角数字表記 "９"）に対応する用語解釈の
    まとまりを抽出する。

    注意: このPDFの項番号は全角数字表記（例: "９"）であり、
    list_classifier.TableRow.label の漢数字表記（例: "九"）とは異なる。
    呼び出し側で変換すること。
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

        chunks = []
        for page_index in range(start_page, end_page + 1):
            page = pdf.pages[page_index]
            top_bound = start_top if page_index == start_page else _header_bottom(page)
            bottom_bound = end_top if page_index == end_page and end_top is not None else page.height
            cropped = page.crop((0, top_bound, page.width, bottom_bound))
            text = cropped.extract_text() or ""
            chunks.append(text)

        full_text = "\n".join(chunks).strip()
        truncated = full_text[:max_chars]
        return RowInterpretation(
            row_label=row_label, start_page=start_page, end_page=end_page, text=truncated,
        )
