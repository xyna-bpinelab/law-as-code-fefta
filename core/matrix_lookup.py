"""METI公式「貨物・技術のマトリクス表」
(https://www.meti.go.jp/policy/anpo/matrix_intro.html) から、別表第一の
各号に対応する貨物等省令の条文（枝番レベル）・用語解釈・参考ECCN番号を
取得するモジュール。

公式マトリクス表（jurisdictions/jp/raw/matrix/kamotsu_matrix_*.xlsx 等）は
項番ごとに1シートで構成され、各シート内で以下の3つの列グループが
並行して配置されている:
  - 輸出令別表第一側（列0:項番ラベル、例「輸出令第９項（５の２）」、
    列1:号の本文）
  - 貨物等省令側（列2:条文番号、列3:条文テキスト。イ・ロ・ハ・ニ等の
    枝番ごとに複数行に分かれる）
  - 用語解釈側（列4:用語、列5:解釈）
  - 参考ECCN番号（列7）
これらは物理的な行位置が完全には一致しない（各列グループが独立して
「値がある行」を持つ）ため、号の開始行（列0に値がある行）を境界として
検出し、次の号の開始行の直前までの範囲内にある列2/3・列4/5・列7を
すべて集約する。

これは core.ministerial_spec_lookup / core.kaishaku_lookup が
PDF座標解析・正規表現で試みていた再構築の後継。マトリクス表は
すでに号単位（枝番レベルまで）で対応関係が公式に確定しているため、
文字列マッチングによる推測が不要になり、より正確。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

__all__ = ["MatrixEntry", "load_matrix_entries", "find_entry", "find_sheet_name"]

_ROW_LABEL_RE = re.compile(
    r"輸出令第?\s*(?P<row>[０-９0-9]+)項\s*(?:（(?P<item>[０-９0-9]+(?:の[０-９0-9]+)?)）)?"
)
_SHEET_ROW_RE = re.compile(r"^\s*([０-９0-9]+(?:の[０-９0-9]+)?)項")
_ZENKAKU_TO_HANKAKU = str.maketrans("０１２３４５６７８９", "0123456789")


def _normalize_digits(s: str) -> str:
    return s.translate(_ZENKAKU_TO_HANKAKU)


def _parse_row_label(raw: str) -> Optional[tuple[str, Optional[str]]]:
    """列0の値（例: '輸出令\\n第９項\\n（５の２）'）から (row_id, item_id) を
    返す。item_idは項全体の頭書き行ではNone。"""
    if not raw:
        return None
    flat = raw.replace("\n", "")
    m = _ROW_LABEL_RE.search(flat)
    if not m:
        return None
    row_id = _normalize_digits(m.group("row"))
    item_raw = m.group("item")
    if item_raw is None:
        return row_id, None
    item_id = "_".join(_normalize_digits(p) for p in item_raw.split("の"))
    return row_id, item_id


def find_sheet_name(wb, row_id: str) -> Optional[str]:
    """row_id（例: "9"）に対応するシート名を探す。
    シート名の項番号表記は全角/半角が混在するため正規化して比較する。"""
    for name in wb.sheetnames:
        m = _SHEET_ROW_RE.match(name)
        if not m:
            continue
        sheet_row_id = "_".join(_normalize_digits(p) for p in m.group(1).split("の"))
        if sheet_row_id == row_id:
            return name
    return None


@dataclass
class MatrixEntry:
    row_id: str
    item_id: Optional[str]  # Noneは項全体の頭書き（号未分類の行）
    label: str               # 列0の値（改行除去済み）
    item_text: str           # 列1の値（号の本文）
    ministerial_refs: list[str] = field(default_factory=list)  # 列2（条文番号）の一覧
    ministerial_text: str = ""                                  # 列3を連結したテキスト
    ministerial_lines: list[str] = field(default_factory=list)  # 列3の行単位（イ/ロ/ハ等の枝ごと）
    terms: list[tuple[str, str]] = field(default_factory=list)  # (用語, 解釈)
    eccn: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "item_text": self.item_text,
            "ministerial_refs": self.ministerial_refs,
            "ministerial_text": self.ministerial_text,
            "ministerial_lines": self.ministerial_lines,
            "terms": [{"term": t, "definition": d} for t, d in self.terms],
            "eccn": self.eccn,
        }


def _cell(row: tuple, idx: int):
    return row[idx] if idx < len(row) else None


def load_matrix_entries(xlsx_path: Path, row_id: str) -> list[MatrixEntry]:
    """指定した項番号(row_id、例: "9")のシートを号単位に分解する。
    シートが見つからない場合は空リストを返す。"""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    sheet_name = find_sheet_name(wb, row_id)
    if sheet_name is None:
        return []

    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))

    # 号の開始行（列0に値があり、この項番号に属する行）を先に収集する
    boundaries: list[tuple[int, Optional[str], str]] = []  # (行index, item_id, label)
    for i, r in enumerate(rows):
        raw = _cell(r, 0)
        if not raw or not isinstance(raw, str):
            continue
        parsed = _parse_row_label(raw)
        if parsed is None:
            continue
        parsed_row_id, item_id = parsed
        if parsed_row_id != row_id:
            continue
        boundaries.append((i, item_id, raw.replace("\n", "")))

    entries: list[MatrixEntry] = []
    for bi, (start, item_id, label) in enumerate(boundaries):
        end = boundaries[bi + 1][0] if bi + 1 < len(boundaries) else len(rows)
        item_text = _cell(rows[start], 1) or ""

        ministerial_refs: list[str] = []
        ministerial_parts: list[str] = []
        terms: list[tuple[str, str]] = []
        eccn: list[str] = []

        for r in rows[start:end]:
            c2, c3 = _cell(r, 2), _cell(r, 3)
            c4, c5 = _cell(r, 4), _cell(r, 5)
            c7 = _cell(r, 7)
            if c2:
                ministerial_refs.append(str(c2).replace("\n", ""))
            if c3:
                ministerial_parts.append(str(c3).replace("\n", ""))
            if c4:
                terms.append((str(c4).replace("\n", ""), str(c5 or "").replace("\n", "")))
            if c7:
                eccn.append(str(c7).replace("\n", ""))

        entries.append(MatrixEntry(
            row_id=row_id, item_id=item_id, label=label, item_text=str(item_text).replace("\n", ""),
            ministerial_refs=ministerial_refs, ministerial_text="".join(ministerial_parts),
            ministerial_lines=ministerial_parts,
            terms=terms, eccn=eccn,
        ))

    return entries


def find_entry(entries: list[MatrixEntry], item_id: str) -> Optional[MatrixEntry]:
    for e in entries:
        if e.item_id == item_id:
            return e
    return None
