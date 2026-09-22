#!/usr/bin/env python3
"""law-as-code-fefta の決定木エンジンをコマンドラインから実行するツール。

使用例:
    # モック評価（APIキー不要。hybrid_jevノードはツリー自身のconditionsで判定）
    python3 scripts/run_tree.py --tree inclusive_license_tree --facts examples/general_license_ok.json

    # 実際にTypeSafe AI(Jev)を呼び出す（要 pip install typesafe-sdk, TYPESAFE_API_KEY）
    python3 scripts/run_tree.py --tree exemption_tree --facts examples/repair_exemption.json --live

    # facts をコマンドラインでインラインJSON指定
    python3 scripts/run_tree.py --tree inclusive_license_tree --facts-json '{"item": {"is_list_controlled": false}}'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.jev_client import JevClientError, MockJevClient, TypeSafeJevClient  # noqa: E402
from core.tree_engine import TreeEngineError, load_tree_by_name, run_tree  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tree", required=True, help="ツール名（拡張子なし。例: inclusive_license_tree, exemption_tree）")
    facts_group = parser.add_mutually_exclusive_group(required=True)
    facts_group.add_argument("--facts", help="facts JSONファイルへのパス")
    facts_group.add_argument("--facts-json", help="facts をインラインJSON文字列で指定")
    parser.add_argument("--live", action="store_true", help="hybrid_jevノードで実際にTypeSafe AI(Jev)を呼び出す（既定: モック評価）")
    parser.add_argument("--model", default=None, help="TypeSafeのモデル名を上書き（既定: 各プロンプトのmodel、通常jev-latest）")
    parser.add_argument("--json", action="store_true", help="トレース結果をJSONで標準出力する（既定: 整形テキスト）")
    args = parser.parse_args()

    try:
        tree = load_tree_by_name(args.tree)
    except TreeEngineError as e:
        parser.error(str(e))

    if args.facts_json:
        facts = json.loads(args.facts_json)
    else:
        facts_path = Path(args.facts)
        if not facts_path.exists():
            parser.error(f"factsファイルが見つかりません: {facts_path}")
        facts = json.loads(facts_path.read_text(encoding="utf-8"))

    if args.live:
        try:
            jev_client = TypeSafeJevClient(model=args.model)
        except JevClientError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)
    else:
        jev_client = MockJevClient()

    try:
        result = run_tree(tree, facts, jev_client=jev_client)
    except (TreeEngineError, JevClientError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.pretty_print())


if __name__ == "__main__":
    main()
