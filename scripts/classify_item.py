#!/usr/bin/env python3
"""自然文の製品説明から、輸出令別表第一の該当し得る項番を複数選択の
可能性ありで一次スクリーニングするプロトタイプCLI。

TypeSafe AI(Jev)のNoulプリミティブを項番ごとに独立して呼び出す
（1回のAPI呼び出しにまとめて送信）ため、複数の項番が同時に「該当」と
判定されてもよい。Choiceプリミティブ（1択・確率合計1）とは異なる設計。

注意: これは一次スクリーニングのプロトタイプであり、実際の該非判定の
代替ではない。低い確信度や僅差の複数該当は必ず該非判定担当者が確認する
こと。

使用例:
    export TYPESAFE_API_KEY="..."
    python3 scripts/classify_item.py \
        --xml jurisdictions/jp/raw/cabinet_orders/324CO0000000378_20260605_令和八年政令第百九十四号.xml \
        --table 別表第一 \
        --description "航法用の高精度加速度計とジャイロスコープを内蔵した、弾道ミサイル誘導用の慣性航法装置"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.list_classifier import classify_item, load_table_rows  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xml", required=True, help="別表を含む原典XMLファイルへのパス")
    parser.add_argument("--table", default="別表第一", help="対象の別表タイトル（既定: 別表第一）")
    parser.add_argument("--description", required=True, help="判定したい製品・技術の自然文説明")
    parser.add_argument("--threshold", type=float, default=0.5, help="該当とみなす確率の閾値（既定: 0.5）")
    parser.add_argument("--model", default=None, help="TypeSafeのモデル名を上書き（既定: jev-latest）")
    parser.add_argument("--json", action="store_true", help="結果をJSONで出力する")
    args = parser.parse_args()

    try:
        from typesafe_sdk import TypeSafeClient
    except ImportError:
        parser.error("typesafe-sdk がインストールされていません（pip install typesafe-sdk）")

    rows = load_table_rows(Path(args.xml), table_title=args.table)
    if not rows:
        parser.error(f"{args.table} から番号付き行を抽出できませんでした")

    client = TypeSafeClient()
    matches = classify_item(client, args.description, rows, threshold=args.threshold, model=args.model)

    if args.json:
        print(json.dumps(
            {"description": args.description, "matches": [m.to_dict() for m in matches]},
            ensure_ascii=False, indent=2,
        ))
        return

    print(f"=== {args.table} 該当項番スクリーニング ===")
    print(f"製品説明: {args.description}")
    print(f"閾値: {args.threshold}\n")
    above = [m for m in matches if m.probability >= args.threshold]
    if above:
        print(f"【該当候補（閾値以上、{len(above)}件）】")
        for m in above:
            print(f"  ★ {m.row.label}の項 (row_id={m.row.row_id}): probability={m.probability:.3f}")
    else:
        print("【該当候補なし（閾値以上の項番はありません）】")

    print("\n【全項番の確率一覧（降順）】")
    for m in matches:
        marker = "★" if m.probability >= args.threshold else " "
        print(f"  {marker} {m.row.label}の項 (row_id={m.row.row_id}): {m.probability:.3f}")


if __name__ == "__main__":
    main()
