#!/usr/bin/env python3
"""述語論理プロトタイプ: 別表第一の行レベル粗判定(stage1) -> 対象行を号
（述語）単位に分解しての細粒度判定(stage2) -> 除外節によるhard_rule抑制、
を通しで実行するCLI。

使用例:
    export TYPESAFE_API_KEY="..."
    python3 scripts/classify_predicates.py \
        --xml jurisdictions/jp/raw/cabinet_orders/324CO0000000378_20260605_令和八年政令第百九十四号.xml \
        --row 二 \
        --description "多段ロケットの製造に使用される、チタン合金部品の等方圧成形（アイソスタチックプレス）装置。ロケットエンジンの構造部材製造工程で使用される。"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.list_classifier import classify_item, load_table_rows  # noqa: E402
from core.predicate_extractor import classify_subitems, extract_subitems  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xml", required=True, help="別表を含む原典XMLファイルへのパス")
    parser.add_argument("--table", default="別表第一", help="対象の別表タイトル（既定: 別表第一）")
    parser.add_argument("--row", required=True, help="号単位まで細かく判定する行の見出し（例: 二）")
    parser.add_argument("--description", required=True, help="判定したい製品・技術の自然文説明")
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

    # --- stage2: 指定行を号単位に分解して細粒度判定 ---
    subitems = extract_subitems(Path(args.xml), row_label=args.row)
    stage2_matches = classify_subitems(
        client, args.description, subitems,
        stage1_row_matches=stage1_by_id, threshold=args.threshold, model=args.model,
    )

    if args.json:
        print(json.dumps({
            "description": args.description,
            "stage1_row_matches": [m.to_dict() for m in stage1_matches],
            "stage2_subitem_matches": [m.to_dict() for m in stage2_matches],
        }, ensure_ascii=False, indent=2))
        return

    print("=== Stage1: 行レベル判定（全" + str(len(rows)) + "行） ===")
    for m in stage1_matches:
        marker = "★" if m.probability >= args.threshold else " "
        print(f"  {marker} {m.row.label}の項 (row_id={m.row.row_id}): {m.probability:.3f}")

    print(f"\n=== Stage2: {args.row}の項 を号単位（{len(subitems)}件）で細粒度判定 ===")
    for m in stage2_matches:
        if m.suppressed:
            marker = "✗"
        elif m.probability >= args.threshold:
            marker = "★"
        else:
            marker = " "
        review = " [要目視確認: 除外節を機械解析できず]" if m.needs_manual_review else ""
        print(f"  {marker} {m.subitem.label}({m.subitem.item_id}): {m.probability:.3f}{review}")
        if m.suppressed:
            print(f"      -> 抑制理由: {m.suppressed_reason}")

    confirmed = [m for m in stage2_matches if m.probability >= args.threshold and not m.suppressed]
    suppressed = [m for m in stage2_matches if m.suppressed]
    print(f"\n=== まとめ ===")
    print(f"確定該当（閾値以上・除外なし）: {len(confirmed)}件 -> {[m.subitem.label for m in confirmed]}")
    print(f"除外規定により抑制: {len(suppressed)}件 -> {[m.subitem.label for m in suppressed]}")


if __name__ == "__main__":
    main()
