"""貨物等省令（輸出貿易管理令別表第一及び外国為替令別表の規定に基づき
貨物又は技術を定める省令）から、別表第一の特定の行（項）に対応する
「経済産業省令で定める仕様」の条文を検索するプロトタイプ。

別表第一の各号は「〜であつて、経済産業省令で定める仕様のもの」という
形で、具体的な数値スペック（周波数、耐熱温度、伝送速度等）の決定を
貨物等省令に委任している。別表第一の条文テキストだけでは実務上の
該非判定に必要な閾値が分からないため、対応する貨物等省令の条文を
判定材料としてJevに渡す。

貨物等省令の各条は
    「輸出令別表第一の{row_label}の項の経済産業省令で定める仕様のもの
     は、次のいずれかに該当するものとする。」
という定型文で始まるため、これを正規表現で機械的に検索できる。

注意: 貨物等省令側のItem（号）番号は、別表第一側の号番号と必ずしも
1対1で対応しない（省令側だけの削除号があったり、複数号が統合・分割
されていたりする）。そのため本プロトタイプでは、対応条文の全文を
1つのまとまり（stateの一部）としてJevに渡し、号ごとの精密な対応付けは
将来の課題として残す。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

__all__ = ["MinisterialSpec", "find_spec_for_row"]

# 条文冒頭は「輸出貿易管理令（以下「輸出令」という。）別表第一の...」のように
# 正式名称＋略称定義が略称の直前に埋め込まれることがあるため、
# 「◯◯令別表」の直前までは緩く読み飛ばす。項番号（一〇 等の位取り表記）には
# 「〇」も含まれるため文字クラスに含める。
_LEAD_SENTENCE_RE = re.compile(
    r"(?:輸出令|外為令|輸出貿易管理令|外国為替令)(?:（[^（）]*）)?別表(?:第一)?の?([〇一二三四五六七八九十]+(?:の[〇一二三四五六七八九十]+)?)の項"
    r"(?:（[^（）]*）)?の経済産業省令で定める(?:仕様|技術|もの)"
)


@dataclass
class MinisterialSpec:
    article_title: str   # 例: "第八条"
    article_caption: str  # 例: "（輸出貿易管理令別表第一関係）"（無題の場合は空）
    lead_sentence: str    # 条文の最初の文（どの項に対応するかの宣言）
    full_text: str        # 条文全文
    item_count: int       # 条文内のItem（号）数（参考情報）


def find_spec_for_row(xml_path: Path, row_label: str) -> Optional[MinisterialSpec]:
    """貨物等省令の中から、別表第一の row_label（例: "九"）に対応する
    「経済産業省令で定める仕様」の条文を探す。見つからなければ None。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    mp = root.find("LawBody").find("MainProvision")
    if mp is None:
        return None

    for article in mp.findall(".//Article"):
        paragraphs = article.findall("Paragraph")
        if not paragraphs:
            continue
        lead_sentence_el = paragraphs[0].find("ParagraphSentence")
        if lead_sentence_el is None:
            continue
        lead_sentence = "".join(s.text or "" for s in lead_sentence_el.iter("Sentence"))

        m = _LEAD_SENTENCE_RE.search(lead_sentence)
        if not m or m.group(1) != row_label:
            continue

        title_el = article.find("ArticleTitle")
        caption_el = article.find("ArticleCaption")
        full_text = "".join(s.text or "" for s in article.iter("Sentence"))
        item_count = len(paragraphs[0].findall("Item"))

        return MinisterialSpec(
            article_title=(title_el.text or "").strip() if title_el is not None else "",
            article_caption=(caption_el.text or "").strip() if caption_el is not None else "",
            lead_sentence=lead_sentence,
            full_text=full_text,
            item_count=item_count,
        )

    return None
