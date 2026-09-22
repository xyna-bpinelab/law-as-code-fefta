#!/usr/bin/env python3
"""述語論理プロトタイプ: 別表第一の行レベル粗判定(stage1) -> 対象行を号
（述語）単位に分解しての細粒度判定(stage2) -> 除外節によるhard_rule抑制、
を通しで実行するCLI。

--ministerial-xml / --kaishaku-pdf を指定すると、貨物等省令の対応条文
（具体的な数値基準）・運用通達別紙の用語解釈をJevの判定材料に追加し、
追加なしの場合との差分を表示する。

使用例:
    export TYPESAFE_API_KEY="..."
    python3 scripts/classify_predicates.py \
        --xml jurisdictions/jp/raw/cabinet_orders/324CO0000000378_20260605_令和八年政令第百九十四号.xml \
        --row 九 \
        --description "..." \
        --ministerial-xml jurisdictions/jp/raw/ministerial_orders/403M50000400049_20260214_令和七年経済産業省令第七十二号.xml \
        --kaishaku-pdf jurisdictions/jp/raw/circulars/kamotsu-kaishaku.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.kaishaku_lookup import find_interpretation_for_row, kanji_row_label_to_zenkaku  # noqa: E402
from core.list_classifier import classify_item, load_table_rows  # noqa: E402
from core.ministerial_spec_lookup import find_spec_for_row  # noqa: E402
from core.predicate_extractor import classify_subitems, extract_subitems  # noqa: E402


def print_stage2(title: str, stage2_matches, threshold: float) -> None:
    print(f"\n=== {title} ===")
    for m in stage2_matches:
        if m.suppressed:
            marker = "✗"
        elif m.probability >= threshold:
            marker = "★"
        else:
            marker = " "
        review = " [要目視確認: 除外節を機械解析できず]" if m.needs_manual_review else ""
        print(f"  {marker} {m.subitem.label}({m.subitem.item_id}): {m.probability:.3f}{review}")
        if m.suppressed:
            print(f"      -> 抑制理由: {m.suppressed_reason}")
    confirmed = [m for m in stage2_matches if m.probability >= threshold and not m.suppressed]
    suppressed = [m for m in stage2_matches if m.suppressed]
    print(f"  -- 確定該当: {len(confirmed)}件 {[m.subitem.label for m in confirmed]} "
          f"/ 除外規定により抑制: {len(suppressed)}件 {[m.subitem.label for m in suppressed]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xml", required=True, help="別表を含む原典XMLファイルへのパス")
    parser.add_argument("--table", default="別表第一", help="対象の別表タイトル（既定: 別表第一）")
    parser.add_argument("--row", required=True, help="号単位まで細かく判定する行の見出し（例: 二）")
    parser.add_argument("--description", required=True, help="判定したい製品・技術の自然文説明")
    parser.add_argument("--ministerial-xml", default=None,
                         help="貨物等省令の原典XMLへのパス。指定すると対応条文を判定材料に加える")
    parser.add_argument("--kaishaku-pdf", default=None,
                         help="運用通達別紙（用語解釈表）PDFへのパス。指定すると対応する用語解釈を判定材料に加える")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--model", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        from typesafe_sdk import TypeSafeClient
    except ImportError:
        parser.error("typesafe-sdk がインストールされていません（pip install typesafe-sdk）")

    client = TypeSafeClient()

    # --- stage1: 行レベルの粗判定（全行） ---
    rows = load_table_rows(Path(args.xml), table_title=args.table)
    stage1_matches = classify_item(client, args.description, rows, threshold=args.threshold, model=args.model)
    stage1_by_id = {m.row.row_id: m.probability for m in stage1_matches}

    # --- stage2: 指定行を号単位に分解して細粒度判定（追加材料なし） ---
    subitems = extract_subitems(Path(args.xml), row_label=args.row)
    stage2_base = classify_subitems(
        client, args.description, subitems,
        stage1_row_matches=stage1_by_id, threshold=args.threshold, model=args.model,
    )

    spec = None
    if args.ministerial_xml:
        spec = find_spec_for_row(Path(args.ministerial_xml), row_label=args.row)
        if spec is None:
            print(f"[WARN] 貨物等省令に {args.row}の項 に対応する条文が見つかりませんでした"
                  "（省令委任のない項の可能性）", file=sys.stderr)

    kaishaku = None
    if args.kaishaku_pdf:
        zenkaku_label = kanji_row_label_to_zenkaku(args.row)
        kaishaku = find_interpretation_for_row(Path(args.kaishaku_pdf), row_label=zenkaku_label)
        if kaishaku is None:
            print(f"[WARN] 用語解釈PDFに {args.row}の項（{zenkaku_label}） が見つかりませんでした", file=sys.stderr)

    stage2_enriched = None
    if spec is not None or kaishaku is not None:
        stage2_enriched = classify_subitems(
            client, args.description, subitems,
            stage1_row_matches=stage1_by_id, threshold=args.threshold, model=args.model,
            ministerial_spec_text=spec.full_text if spec else None,
            kaishaku_interpretation=kaishaku,
        )

    if args.json:
        out = {
            "description": args.description,
            "stage1_row_matches": [m.to_dict() for m in stage1_matches],
            "stage2_base": [m.to_dict() for m in stage2_base],
        }
        if spec is not None:
            out["ministerial_spec"] = {"article_title": spec.article_title, "full_text": spec.full_text}
        if kaishaku is not None:
            out["kaishaku_text"] = kaishaku.text
        if stage2_enriched is not None:
            out["stage2_enriched"] = [m.to_dict() for m in stage2_enriched]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("=== Stage1: 行レベル判定（全" + str(len(rows)) + "行） ===")
    for m in stage1_matches:
        marker = "★" if m.probability >= args.threshold else " "
        print(f"  {marker} {m.row.label}の項 (row_id={m.row.row_id}): {m.probability:.3f}")

    print_stage2(f"Stage2 [別表条文のみ]: {args.row}の項 を号単位（{len(subitems)}件）で判定", stage2_base, args.threshold)

    if stage2_enriched is not None:
        added = []
        if spec is not None:
            added.append(f"貨物等省令{spec.article_title}({len(spec.full_text):,}字)")
        if kaishaku is not None:
            added.append(f"用語解釈PDF({len(kaishaku.text):,}字)")
        print(f"\n[追加材料: {', '.join(added)}]")
        print_stage2(f"Stage2 [追加材料あり]: {args.row}の項 を号単位で判定", stage2_enriched, args.threshold)

        print("\n=== 追加材料の有無による差分 ===")
        by_id_base = {m.subitem.item_id: m for m in stage2_base}
        by_id_enriched = {m.subitem.item_id: m for m in stage2_enriched}
        for item_id in by_id_base:
            m0, m1 = by_id_base[item_id], by_id_enriched[item_id]
            v0 = m0.probability if not m0.suppressed else -1
            v1 = m1.probability if not m1.suppressed else -1
            verdict0 = "抑制" if m0.suppressed else ("該当" if v0 >= args.threshold else "非該当")
            verdict1 = "抑制" if m1.suppressed else ("該当" if v1 >= args.threshold else "非該当")
            if verdict0 != verdict1 or abs(m0.probability - m1.probability) >= 0.2:
                print(f"  {m0.subitem.label}: 追加なし={m0.probability:.2f}({verdict0}) "
                      f"-> 追加あり={m1.probability:.2f}({verdict1})")


if __name__ == "__main__":
    main()
