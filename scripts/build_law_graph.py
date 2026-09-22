#!/usr/bin/env python3
"""jurisdictions/jp/raw/ の原典法令XML(各法令の現在施行中の最新版)をパースし、

  1. Jev/RAG検索用のClean Markdown  -> jurisdictions/jp/processed/markdown/
  2. 条・項・別表の項番をノード、引用/委任/除外関係をエッジとする
     グラフ構造データ (law_nodes.json / law_edges.json)
     -> jurisdictions/jp/processed/graph/

を生成する。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = REPO_ROOT / "jurisdictions/jp/raw"
PROCESSED_ROOT = REPO_ROOT / "jurisdictions/jp/processed"
MARKDOWN_ROOT = PROCESSED_ROOT / "markdown"
GRAPH_ROOT = PROCESSED_ROOT / "graph"

# 対象法令。current_revision_id は e-Gov law_revisions API で
# current_revision_status == "CurrentEnforced" のものを採用（現在施行中の最新版）。
LAWS = [
    {
        "law_id": "324AC0000000228",
        "law_name": "外国為替及び外国貿易法",
        "category": "laws",
        "current_revision_file": "324AC0000000228_20260812_令和八年法律第六十四号.xml",
    },
    {
        "law_id": "324CO0000000378",
        "law_name": "輸出貿易管理令",
        "category": "cabinet_orders",
        "current_revision_file": "324CO0000000378_20260605_令和八年政令第百九十四号.xml",
    },
    {
        "law_id": "403M50000400049",
        "law_name": "輸出貿易管理令別表第一及び外国為替令別表の規定に基づき貨物又は技術を定める省令",
        "category": "ministerial_orders",
        "current_revision_file": "403M50000400049_20260214_令和七年経済産業省令第七十二号.xml",
    },
]
LAW_NAME_BY_ID = {law["law_id"]: law["law_name"] for law in LAWS}

# 各法令の本文中で用いられる他法令の略称 -> 参照先law_id
# (原文中の「以下「法」という。」「以下「輸出令」という。」等の定義に基づく静的マッピング)
ABBREV_MAP: dict[str, dict[str, str]] = {
    "324CO0000000378": {"法": "324AC0000000228"},
    "403M50000400049": {"輸出令": "324CO0000000378"},
}

# 「政令で定める」等、本文だけでは委任先の具体的な条文まで特定できない場合の
# フォールバック委任先（法令単位のエッジ）
DEFAULT_DELEGATE_TARGET: dict[str, str] = {
    "324AC0000000228": "324CO0000000378",
    "324CO0000000378": "403M50000400049",
}

XML_NS_STRIP = re.compile(r"^\{.*\}")


# ---------------------------------------------------------------------------
# 漢数字 <-> 数値変換
# ---------------------------------------------------------------------------

KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_positional_to_int(s: str) -> Optional[int]:
    """条・項番号など、位取り記数法(十/百/千)の漢数字を整数に変換する。'四十八' -> 48"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    result = 0
    current = 0
    seen_digit = False
    for ch in s:
        if ch in KANJI_DIGITS:
            current = KANJI_DIGITS[ch]
            seen_digit = True
        elif ch in "十百千":
            multiplier = {"十": 10, "百": 100, "千": 1000}[ch]
            current = current if seen_digit else 1
            result += current * multiplier
            current = 0
            seen_digit = False
        else:
            return None
    result += current
    return result if result else None


def kanji_digitseq_to_str(s: str) -> Optional[str]:
    """別表の項番・枝番など、一桁ずつ読み上げる漢数字を文字列に変換する。'二〇' -> '20'"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return str(int(s))
    out = []
    for ch in s:
        if ch in KANJI_DIGITS:
            out.append(str(KANJI_DIGITS[ch]))
        else:
            return None
    return str(int("".join(out))) if out else None


def branch_to_id(s: str, converter) -> Optional[str]:
    """'十六の二' -> '16_2' のように「の」区切りの枝番をアンダースコア連結IDへ変換する。"""
    parts = s.split("の")
    nums = []
    for p in parts:
        n = converter(p)
        if n is None:
            return None
        nums.append(str(n))
    return "_".join(nums)


def sanitize_article_num(num: str) -> str:
    """XMLのArticle/Num属性('16_2', '2:4' 等)をURNセグメントへ整形する。"""
    return num.replace(":", "-")


# ---------------------------------------------------------------------------
# XMLユーティリティ
# ---------------------------------------------------------------------------

def collect_text(el) -> str:
    """要素配下のSentenceテキストを文書順に連結する。"""
    parts = []
    for sentence in el.iter("Sentence"):
        if sentence.text:
            parts.append(sentence.text)
    return "".join(parts)


def local_tag(el) -> str:
    return XML_NS_STRIP.sub("", el.tag)


# ---------------------------------------------------------------------------
# ノード/エッジ ビルダー
# ---------------------------------------------------------------------------

class GraphBuilder:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []

    def add_node(self, node: dict):
        # 同一IDのノードは初出のものを優先（後続の重複追加は無視）
        self.nodes.setdefault(node["id"], node)

    def add_edge(self, source: str, target: str, relation_type: str, context_text: str):
        self.edges.append({
            "source": source,
            "target": target,
            "relation_type": relation_type,
            "context_text": context_text.strip()[:200],
        })

    def ensure_law_node(self, law_id: str):
        node_id = f"urn:jp:law:{law_id}"
        self.add_node({
            "id": node_id,
            "law_id": law_id,
            "law_name": LAW_NAME_BY_ID.get(law_id, law_id),
            "type": "Law",
        })
        return node_id

    def ensure_article_node(self, law_id: str, art_num_raw: str, title: str = "", caption: str = "", text: str = ""):
        seg = sanitize_article_num(art_num_raw)
        node_id = f"urn:jp:law:{law_id}:art_{seg}"
        self.add_node({
            "id": node_id,
            "law_id": law_id,
            "law_name": LAW_NAME_BY_ID.get(law_id, law_id),
            "type": "Article",
            "number": art_num_raw,
            "title": (caption or title or "").strip("（）() "),
            "text": text,
        })
        return node_id

    def ensure_paragraph_node(self, law_id: str, art_num_raw: str, para_num_raw: str, text: str = ""):
        art_seg = sanitize_article_num(art_num_raw)
        node_id = f"urn:jp:law:{law_id}:art_{art_seg}:para_{para_num_raw}"
        self.add_node({
            "id": node_id,
            "law_id": law_id,
            "law_name": LAW_NAME_BY_ID.get(law_id, law_id),
            "type": "Paragraph",
            "article_number": art_num_raw,
            "number": para_num_raw,
            "text": text,
        })
        return node_id

    def ensure_appdx_table_node(self, law_id: str, table_id: str, title: str = "", related_article: str = ""):
        node_id = f"urn:jp:law:{law_id}:appdx_{table_id}"
        self.add_node({
            "id": node_id,
            "law_id": law_id,
            "law_name": LAW_NAME_BY_ID.get(law_id, law_id),
            "type": "AppdxTable",
            "number": table_id,
            "title": title,
            "related_article": related_article,
        })
        return node_id

    def ensure_appdx_row_node(self, law_id: str, table_id: str, row_id: str, text: str = ""):
        node_id = f"urn:jp:law:{law_id}:appdx_{table_id}:row_{row_id}"
        self.add_node({
            "id": node_id,
            "law_id": law_id,
            "law_name": LAW_NAME_BY_ID.get(law_id, law_id),
            "type": "AppdxTableRow",
            "table_number": table_id,
            "number": row_id,
            "text": text,
        })
        return node_id

    def resolve_article_node_id(self, law_id: str, art_num: int, para_num: Optional[int] = None) -> str:
        seg = str(art_num)
        node_id = f"urn:jp:law:{law_id}:art_{seg}"
        if para_num is not None:
            node_id += f":para_{para_num}"
        return node_id


# ---------------------------------------------------------------------------
# 正規表現ルール
# ---------------------------------------------------------------------------

# 条・項の引用: (略称)?第◯条(第◯項)?
CITATION_RE = re.compile(
    r"(?P<abbrev>法|輸出令)?第(?P<art>[〇一二三四五六七八九十百千]+)条"
    r"(?:第(?P<para>[〇一二三四五六七八九十百千]+)項)?"
)

# 別表の参照: 別表第◯(の◯...)?(の項)?
# 「の項」が直後に続く場合、最初の番号だけを表番号(table)とし、残りの「の◯」連なり(rest)は
# 項番号(row)として扱う（例:「別表第一の一六の項」-> table=1, row=16）。
# 「の項」が続かない場合は、番号の連なり全体を表番号の枝番として扱う
# （例:「別表第二の二」-> table=2_2、これは輸出令の実在テーブル「別表第二の二」）。
TABLE_ROW_RE = re.compile(
    r"(?P<prefix>[^\s、。「」（）]{0,6})?"
    r"別表第(?P<table>[〇一二三四五六七八九十]+)"
    r"(?:の(?P<rest>[〇一二三四五六七八九十]+(?:の[〇一二三四五六七八九十]+)*))?"
    r"(?P<has_row>の項)?"
)

DELEGATE_PHRASE_RE = re.compile(r"(政令|(?:経済産業)?省令)で定める")

CITE_TRIGGER_WORDS = ("に規定する", "の規定に基づ", "の規定による")
EXCEPT_TRIGGER = "にかかわらず"
LOOKAHEAD_WINDOW = 20
TABLE_SEARCH_WINDOW = 80


def parse_table_match(m: re.Match) -> tuple[Optional[str], Optional[str]]:
    """TABLE_ROW_RE のマッチから (table_id, row_id) を求める。row_idはNoneの場合がある。"""
    table_kanji = m.group("table")
    rest_kanji = m.group("rest")
    has_row = m.group("has_row")

    if has_row and rest_kanji:
        table_id = kanji_digitseq_to_str(table_kanji)
        row_id = branch_to_id(rest_kanji, kanji_digitseq_to_str)
        return table_id, row_id

    if rest_kanji:
        table_id = branch_to_id(f"{table_kanji}の{rest_kanji}", kanji_digitseq_to_str)
        return table_id, None

    return kanji_digitseq_to_str(table_kanji), None


def resolve_abbrev_target(current_law_id: str, abbrev: Optional[str]) -> Optional[str]:
    if not abbrev:
        return None
    return ABBREV_MAP.get(current_law_id, {}).get(abbrev)


def normalize_abbreviations(current_law_id: str, text: str) -> str:
    """原文の最初の引用箇所は
    「外国為替及び外国貿易法（昭和二十四年法律第二百二十八号。以下「法」という。）第四十八条...」
    のように正式名称＋略称定義が条文引用の直前に埋め込まれる。以降の抽出処理が
    略称プレフィックス（例:「法第」）だけを見れば済むよう、正式名称＋定義部分を
    略称そのものに畳み込む。"""
    for abbrev, mapped_law_id in ABBREV_MAP.get(current_law_id, {}).items():
        full_name = LAW_NAME_BY_ID.get(mapped_law_id)
        if not full_name:
            continue
        pattern = re.compile(
            re.escape(full_name) + r"（[^（）]*以下「" + re.escape(abbrev) + r"」という。?）"
        )
        text = pattern.sub(abbrev, text)
    return text


def extract_citation_edges(gb: GraphBuilder, current_law_id: str, article_num_raw: str, text: str):
    source_article_id = gb.resolve_article_node_id(current_law_id, int(sanitize_article_num(article_num_raw)) if sanitize_article_num(article_num_raw).lstrip("-").isdigit() else article_num_raw)
    # 上のint変換はNum='2:4'等の削除範囲では失敗しうるため、素直にsanitizeした文字列IDを使う
    source_article_id = f"urn:jp:law:{current_law_id}:art_{sanitize_article_num(article_num_raw)}"

    for m in CITATION_RE.finditer(text):
        art_kanji = m.group("art")
        para_kanji = m.group("para")
        abbrev = m.group("abbrev")
        window = text[m.end(): m.end() + LOOKAHEAD_WINDOW]

        art_num = kanji_positional_to_int(art_kanji)
        if art_num is None:
            continue
        para_num = kanji_positional_to_int(para_kanji) if para_kanji else None

        target_law_id = resolve_abbrev_target(current_law_id, abbrev)

        if EXCEPT_TRIGGER in window:
            # 「第◯条(第◯項)の規定にかかわらず」-> 除外関係
            # エッジは条レベルのノードIDに統一する（項ノード自体は別途生成する）
            ref_law_id = target_law_id or current_law_id
            target_id = gb.resolve_article_node_id(ref_law_id, art_num)
            gb.ensure_article_node(ref_law_id, str(art_num))
            if para_num is not None:
                gb.ensure_paragraph_node(ref_law_id, str(art_num), str(para_num))
            ctx_start = max(0, m.start() - 10)
            gb.add_edge(
                source=source_article_id,
                target=target_id,
                relation_type="Excepts",
                context_text=text[ctx_start: m.end() + LOOKAHEAD_WINDOW],
            )
            continue

        if target_law_id and any(w in window for w in CITE_TRIGGER_WORDS):
            # 「法第48条第1項に規定する」+ 別表参照 -> 委任関係(DelegatesTo)
            search_zone = text[m.end(): m.end() + TABLE_SEARCH_WINDOW]
            table_match = TABLE_ROW_RE.search(search_zone)
            if table_match and table_match.group("table"):
                table_id, row_id = parse_table_match(table_match)
                if table_id is None:
                    continue
                # エッジは条レベルのノードIDに統一する（項ノード自体は別途生成する）
                parent_article_id = gb.resolve_article_node_id(target_law_id, art_num)
                gb.ensure_article_node(target_law_id, str(art_num))
                if para_num is not None:
                    gb.ensure_paragraph_node(target_law_id, str(art_num), str(para_num))

                if row_id:
                    target_node_id = gb.ensure_appdx_row_node(current_law_id, table_id, row_id)
                else:
                    target_node_id = gb.ensure_appdx_table_node(current_law_id, table_id)

                ctx_start = max(0, m.start() - 10)
                gb.add_edge(
                    source=parent_article_id,
                    target=target_node_id,
                    relation_type="DelegatesTo",
                    context_text=text[ctx_start: m.end() + TABLE_SEARCH_WINDOW],
                )


BARE_PARA_EXCEPT_RE = re.compile(r"第(?P<para>[〇一二三四五六七八九十百千]+)項の規定にかかわらず")
PREV_PARA_EXCEPT_RE = re.compile(r"前項の規定にかかわらず")
PREV_ARTICLE_EXCEPT_RE = re.compile(r"前条(?:第(?P<para>[〇一二三四五六七八九十百千]+)項)?の規定にかかわらず")


def extract_intra_law_except_edges(gb: GraphBuilder, law_id: str, article_el):
    """同一法令内の相対参照（前項・前条・条番号省略の「第◯項」）による除外関係を抽出する。
    絶対参照（法第◯条第◯項の規定にかかわらず 等）は extract_citation_edges 側で処理済み。"""
    art_num_raw = article_el.get("Num", "")
    art_num_int = int(art_num_raw) if art_num_raw.isdigit() else None

    for para in article_el.findall("Paragraph"):
        para_num_raw = para.get("Num", "")
        para_num_int = int(para_num_raw) if para_num_raw.isdigit() else None
        para_text = collect_text(para)
        source_para_id = gb.ensure_paragraph_node(law_id, art_num_raw, para_num_raw, text=para_text)

        for m in BARE_PARA_EXCEPT_RE.finditer(para_text):
            # 直前に略称(法/令/輸出令 等)が付く絶対参照や「前条第◯項」は
            # それぞれ extract_citation_edges / PREV_ARTICLE_EXCEPT_RE 側の担当なのでスキップ
            preceding = para_text[max(0, m.start() - 4): m.start()]
            if preceding.endswith(("法", "令", "前条")):
                continue
            target_para_num = kanji_positional_to_int(m.group("para"))
            if target_para_num is None:
                continue
            target_id = gb.ensure_paragraph_node(law_id, art_num_raw, str(target_para_num))
            ctx_s = max(0, m.start() - 15)
            gb.add_edge(source_para_id, target_id, "Excepts", para_text[ctx_s: m.end()])

        prev_para_match = PREV_PARA_EXCEPT_RE.search(para_text)
        if prev_para_match and para_num_int and para_num_int > 1:
            target_id = gb.ensure_paragraph_node(law_id, art_num_raw, str(para_num_int - 1))
            ctx_s = max(0, prev_para_match.start() - 15)
            gb.add_edge(source_para_id, target_id, "Excepts", para_text[ctx_s: prev_para_match.end()])

        if art_num_int and art_num_int > 1:
            for m in PREV_ARTICLE_EXCEPT_RE.finditer(para_text):
                prev_art_num = art_num_int - 1
                if m.group("para"):
                    target_para_num = kanji_positional_to_int(m.group("para"))
                    target_id = gb.ensure_paragraph_node(law_id, str(prev_art_num), str(target_para_num)) \
                        if target_para_num is not None else gb.ensure_article_node(law_id, str(prev_art_num))
                else:
                    target_id = gb.ensure_article_node(law_id, str(prev_art_num))
                ctx_s = max(0, m.start() - 15)
                gb.add_edge(source_para_id, target_id, "Excepts", para_text[ctx_s: m.end()])


def extract_table_reference_edges(gb: GraphBuilder, current_law_id: str, article_num_raw: str, text: str):
    """別表参照のうち、委任充足文(extract_citation_edgesで処理済み)以外の
    単純な別表参照を RefersTo エッジとして抽出する。"""
    source_article_id = f"urn:jp:law:{current_law_id}:art_{sanitize_article_num(article_num_raw)}"

    for m in TABLE_ROW_RE.finditer(text):
        table_id, row_id = parse_table_match(m)
        if table_id is None:
            continue

        prefix = (m.group("prefix") or "")
        target_law_id = current_law_id
        for abbrev, mapped_law_id in ABBREV_MAP.get(current_law_id, {}).items():
            if prefix.endswith(abbrev):
                target_law_id = mapped_law_id
                break

        target_node_id = (
            gb.ensure_appdx_row_node(target_law_id, table_id, row_id)
            if row_id else gb.ensure_appdx_table_node(target_law_id, table_id)
        )

        ctx_start = max(0, m.start() - 15)
        ctx_end = min(len(text), m.end() + 30)
        gb.add_edge(
            source=source_article_id,
            target=target_node_id,
            relation_type="RefersTo",
            context_text=text[ctx_start:ctx_end],
        )


def extract_delegate_phrase_edges(gb: GraphBuilder, current_law_id: str, article_num_raw: str, text: str):
    """「政令で定める」「省令で定める」等、委任先の条文までは本文から特定できない
    包括的な委任表現を、法令単位のフォールバック委任エッジとして抽出する。"""
    target_law_id = DEFAULT_DELEGATE_TARGET.get(current_law_id)
    if not target_law_id:
        return
    source_article_id = f"urn:jp:law:{current_law_id}:art_{sanitize_article_num(article_num_raw)}"
    target_node_id = gb.ensure_law_node(target_law_id)

    for m in DELEGATE_PHRASE_RE.finditer(text):
        ctx_start = max(0, m.start() - 20)
        ctx_end = min(len(text), m.end() + 10)
        gb.add_edge(
            source=source_article_id,
            target=target_node_id,
            relation_type="DelegatesTo",
            context_text=text[ctx_start:ctx_end],
        )


# ---------------------------------------------------------------------------
# Markdown生成
# ---------------------------------------------------------------------------

def render_inline_items(parent_el, level: int) -> list[str]:
    """Item/Subitem1/Subitem2/Subitem3 を箇条書きMarkdownへ変換する。"""
    lines = []
    tag_chain = ["Item", "Subitem1", "Subitem2", "Subitem3", "Subitem4"]
    child_tag = tag_chain[level] if level < len(tag_chain) else None
    if child_tag is None:
        return lines
    for child in parent_el.findall(child_tag):
        title_el = child.find(f"{child_tag}Title")
        sentence_el = child.find(f"{child_tag}Sentence")
        title = (title_el.text or "").strip() if title_el is not None else ""
        body = collect_text(sentence_el) if sentence_el is not None else ""
        indent = "  " * level
        lines.append(f"{indent}- {title}　{body}".rstrip())
        lines.extend(render_inline_items(child, level + 1))
    return lines


def render_article_markdown(article_el) -> tuple[str, list[str]]:
    """1条分のMarkdownブロックを生成する。戻り値は (article_num, 行のリスト)。"""
    num = article_el.get("Num", "")
    title_el = article_el.find("ArticleTitle")
    caption_el = article_el.find("ArticleCaption")
    title = (title_el.text or "").strip() if title_el is not None else f"第{num}条"
    caption = (caption_el.text or "").strip() if caption_el is not None else ""

    lines = [f"## {title}{('　' + caption) if caption else ''}", ""]

    for para in article_el.findall("Paragraph"):
        pnum_el = para.find("ParagraphNum")
        pnum_text = (pnum_el.text or "").strip() if pnum_el is not None else ""
        sentence_container = para.find("ParagraphSentence")
        body = collect_text(sentence_container) if sentence_container is not None else ""
        if pnum_text:
            lines.append(f"{pnum_text}　{body}")
        else:
            lines.append(body)
        lines.append("")
        lines.extend(render_inline_items(para, 0))
        if para.findall("Item"):
            lines.append("")

    return num, lines


def render_appdx_table_markdown(table_el) -> list[str]:
    title_el = table_el.find("AppdxTableTitle")
    rel_el = table_el.find("RelatedArticleNum")
    title = (title_el.text or "").strip() if title_el is not None else ""
    rel = (rel_el.text or "").strip() if rel_el is not None else ""

    lines = [f"## {title}{('　' + rel) if rel else ''}", ""]

    if table_el.find("TableStruct") is not None:
        rows = table_el.findall(".//TableRow")
        for i, row in enumerate(rows):
            cols = row.findall("TableColumn")
            cell_texts = [
                "".join(s.text or "" for s in col.iter("Sentence")).replace("\n", " ").replace("|", "\\|").strip()
                for col in cols
            ]
            cell_texts = [c if c else "　" for c in cell_texts]
            lines.append("| " + " | ".join(cell_texts) + " |")
            if i == 0:
                # GFMの表として認識されるよう、見出し行の直後に区切り行を挿入する
                lines.append("| " + " | ".join("---" for _ in cell_texts) + " |")
    elif table_el.findall("Item"):
        # TableStructを持たず、号(Item)の箇条書きとして構成されている別表
        lines.extend(render_inline_items(table_el, 0))

    lines.append("")
    return lines


def build_markdown_for_law(root_el, law_id: str, law_name: str, revision_filename: str) -> str:
    lawbody = root_el.find("LawBody")
    lines = [f"# {law_name}", "", f"- law_id: `{law_id}`", f"- source: `{revision_filename}`", ""]

    main_provision = lawbody.find("MainProvision")
    if main_provision is not None:
        for article in main_provision.iter("Article"):
            _, art_lines = render_article_markdown(article)
            lines.extend(art_lines)

    for table in lawbody.findall("AppdxTable"):
        lines.extend(render_appdx_table_markdown(table))

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def build_nodes_and_edges_for_law(gb: GraphBuilder, root_el, law_id: str):
    lawbody = root_el.find("LawBody")
    gb.ensure_law_node(law_id)

    # AppdxTable(別表)のノードは、本文の引用エッジ抽出でタイトル未設定のスタブが
    # 先に作られてしまわないよう、条文ループより先に正式なメタデータ付きで生成する。
    for table in lawbody.findall("AppdxTable"):
        title_el = table.find("AppdxTableTitle")
        rel_el = table.find("RelatedArticleNum")
        title = (title_el.text or "").strip() if title_el is not None else ""
        rel = (rel_el.text or "").strip() if rel_el is not None else ""
        if not title.startswith("別表第"):
            continue
        table_kanji = title[len("別表第"):]
        table_id = branch_to_id(table_kanji, kanji_digitseq_to_str) if "の" in table_kanji else kanji_digitseq_to_str(table_kanji)
        if table_id is None:
            continue
        gb.ensure_appdx_table_node(law_id, table_id, title=title, related_article=rel)

        if table.find("TableStruct") is not None:
            rows = table.findall(".//TableRow")
            for row in rows:
                cols = row.findall("TableColumn")
                if not cols:
                    continue
                first_cell = "".join(s.text or "" for s in cols[0].iter("Sentence")).strip()
                row_id = kanji_digitseq_to_str(first_cell)
                if row_id is None:
                    continue  # 見出し行など番号化できない行はノード化しない
                row_text = " / ".join(
                    "".join(s.text or "" for s in col.iter("Sentence")).strip() for col in cols[1:]
                )
                gb.ensure_appdx_row_node(law_id, table_id, row_id, text=row_text)
        else:
            # TableStructを持たず、号(Item)で構成されている別表
            for item in table.findall("Item"):
                row_id = item.get("Num")
                if not row_id:
                    continue
                row_text = collect_text(item)
                gb.ensure_appdx_row_node(law_id, table_id, row_id, text=row_text)

    main_provision = lawbody.find("MainProvision")
    if main_provision is not None:
        for article in main_provision.iter("Article"):
            art_num_raw = article.get("Num", "")
            title_el = article.find("ArticleTitle")
            caption_el = article.find("ArticleCaption")
            title = (title_el.text or "") if title_el is not None else ""
            caption = (caption_el.text or "") if caption_el is not None else ""
            full_text = collect_text(article)

            gb.ensure_article_node(law_id, art_num_raw, title=title, caption=caption, text=full_text)

            for para in article.findall("Paragraph"):
                pnum_raw = para.get("Num", "")
                para_text = collect_text(para)
                gb.ensure_paragraph_node(law_id, art_num_raw, pnum_raw, text=para_text)

            normalized_text = normalize_abbreviations(law_id, full_text)
            extract_citation_edges(gb, law_id, art_num_raw, normalized_text)
            extract_table_reference_edges(gb, law_id, art_num_raw, normalized_text)
            extract_delegate_phrase_edges(gb, law_id, art_num_raw, full_text)
            extract_intra_law_except_edges(gb, law_id, article)


def main():
    import xml.etree.ElementTree as ET

    gb = GraphBuilder()

    print("=== 法令XML -> Markdown / グラフJSON 変換 ===")
    for law in LAWS:
        xml_path = RAW_ROOT / law["category"] / law["current_revision_file"]
        if not xml_path.exists():
            raise FileNotFoundError(f"最新版XMLが見つかりません: {xml_path}")

        print(f"[INFO] {law['law_name']} ({law['law_id']}) を処理中... source={xml_path.name}")
        tree = ET.parse(xml_path)
        root_el = tree.getroot()

        # Markdown生成
        md_text = build_markdown_for_law(root_el, law["law_id"], law["law_name"], xml_path.name)
        md_out_dir = MARKDOWN_ROOT / law["category"]
        md_out_dir.mkdir(parents=True, exist_ok=True)
        md_out_path = md_out_dir / f"{law['law_id']}.md"
        md_out_path.write_text(md_text, encoding="utf-8")
        print(f"  [OK] Markdown -> {md_out_path.relative_to(REPO_ROOT)} ({len(md_text):,} 文字)")

        # グラフノード/エッジ生成
        build_nodes_and_edges_for_law(gb, root_el, law["law_id"])

    GRAPH_ROOT.mkdir(parents=True, exist_ok=True)
    nodes_path = GRAPH_ROOT / "law_nodes.json"
    edges_path = GRAPH_ROOT / "law_edges.json"

    nodes_list = list(gb.nodes.values())
    nodes_path.write_text(
        json.dumps(nodes_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    edges_path.write_text(
        json.dumps(gb.edges, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[OK] グラフノード {len(nodes_list)} 件 -> {nodes_path.relative_to(REPO_ROOT)}")
    print(f"[OK] グラフエッジ {len(gb.edges)} 件 -> {edges_path.relative_to(REPO_ROOT)}")
    print("=== 完了 ===")


if __name__ == "__main__":
    main()
