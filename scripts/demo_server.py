#!/usr/bin/env python3
"""別表第一 該非判定プロトタイプの実証用デモサーバー。

自然文の製品・技術説明を入力すると、ブラウザ上でリアルタイムに
輸出令別表第一のどの項番・号に該当し得るかを、実際のTypeSafe AI(Jev)
APIを呼び出して判定・表示する。

標準ライブラリのみで動作する（Flask等は使わない）。

使用方法:
    export TYPESAFE_API_KEY="..."
    pip install typesafe-sdk openpyxl
    python3 scripts/demo_server.py [--port 8800]
    -> ブラウザで http://127.0.0.1:8800 を開く

API:
    POST /api/stage1  {"description": "..."}
        -> 別表第一の全17項について、"どの項番の製品カテゴリに属するか"
           という分類スクリーニング結果を返す（規制基準の該非判定では
           ない。どの項番で該非判定すべきかを絞り込むための一次分類）
    POST /api/stage2  {"description": "...", "row_label": "九"}
        -> 指定行を号単位に分解し、METI公式マトリクス表
           （kamotsu_matrix_*.xlsx）から号ごとに正確対応付けられた
           貨物等省令の条文・用語解釈を判定材料に加えた、実際の
           該非判定結果を返す
    POST /api/stage3  {"row_label": "九", "item_id": "1"}
        -> 指定の号の条文（別表本文＋貨物等省令の対応条文）から、
           数値仕様の判定条件（周波数・温度等の閾値）を機械的に抽出し、
           ユーザーが実測値を入力するための質問項目を返す（TypeSafe
           API呼び出し不要。純粋な正規表現ベースの抽出）。最終的な
           該非判定（各条件を満たすか）はブラウザ側で計算する。
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.list_classifier import classify_item, load_table_rows  # noqa: E402
from core.matrix_lookup import find_entry, load_matrix_entries  # noqa: E402
from core.predicate_extractor import classify_subitems, extract_subitems  # noqa: E402
from core.spec_extractor import extract_spec_criteria  # noqa: E402

XML_PATH = REPO_ROOT / "jurisdictions/jp/raw/cabinet_orders/324CO0000000378_20260605_令和八年政令第百九十四号.xml"
MATRIX_XLSX_PATH = REPO_ROOT / "jurisdictions/jp/raw/matrix/kamotsu_matrix_20260214.xlsx"
STATIC_DIR = Path(__file__).resolve().parent / "demo_static"
THRESHOLD = 0.5

_client = None
_rows_cache = None


def get_client():
    global _client
    if _client is None:
        try:
            from typesafe_sdk import TypeSafeClient
        except ImportError as e:
            raise RuntimeError(
                "typesafe-sdk がインストールされていません。`pip install typesafe-sdk` を実行してください。"
            ) from e
        try:
            _client = TypeSafeClient()
        except Exception as e:
            raise RuntimeError(
                f"TypeSafeClientの初期化に失敗しました。TYPESAFE_API_KEY環境変数を確認してください。({e})"
            ) from e
    return _client


def get_rows():
    global _rows_cache
    if _rows_cache is None:
        _rows_cache = load_table_rows(XML_PATH)
    return _rows_cache


def get_row_id_by_label(row_label: str):
    for row in get_rows():
        if row.label == row_label:
            return row.row_id
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "FEFTADemo/1.0"

    def log_message(self, fmt, *args):  # 標準の冗長アクセスログを抑制
        sys.stderr.write(f"[demo_server] {fmt % args}\n")

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_error(404, f"not found: {path.name}")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._serve_file(STATIC_DIR / "app.js", "text/javascript; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            self._send_json({"error": "リクエストがJSONとして解釈できません"}, 400)
            return

        try:
            if path == "/api/stage1":
                self._handle_stage1(payload)
            elif path == "/api/stage2":
                self._handle_stage2(payload)
            elif path == "/api/stage3":
                self._handle_stage3(payload)
            else:
                self.send_error(404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._send_json({"error": str(e)}, 500)

    def _handle_stage1(self, payload: dict):
        description = (payload.get("description") or "").strip()
        if not description:
            self._send_json({"error": "description は必須です"}, 400)
            return

        rows = get_rows()
        matches = classify_item(get_client(), description, rows, threshold=THRESHOLD)
        self._send_json({
            "threshold": THRESHOLD,
            "matches": [
                {"row_id": m.row.row_id, "label": m.row.label, "probability": m.probability}
                for m in matches
            ],
        })

    def _handle_stage2(self, payload: dict):
        description = (payload.get("description") or "").strip()
        row_label = (payload.get("row_label") or "").strip()
        if not description or not row_label:
            self._send_json({"error": "description と row_label は必須です"}, 400)
            return

        # stage1をこの行についてだけ再取得（除外規定の抑制判定に使う）
        rows = get_rows()
        stage1_matches = classify_item(get_client(), description, rows, threshold=THRESHOLD)
        stage1_by_id = {m.row.row_id: m.probability for m in stage1_matches}

        subitems = extract_subitems(XML_PATH, row_label=row_label)
        if not subitems:
            self._send_json({
                "row_label": row_label, "subitems": [],
                "note": "この行には号への分解対象がありません（削除済み等）",
            })
            return

        row_id = get_row_id_by_label(row_label)
        matrix_entries = load_matrix_entries(MATRIX_XLSX_PATH, row_id) if row_id else []
        matrix_term_count = sum(len(e.terms) for e in matrix_entries)
        matrix_spec_count = sum(1 for e in matrix_entries if e.ministerial_text)

        matches = classify_subitems(
            get_client(), description, subitems,
            stage1_row_matches=stage1_by_id, threshold=THRESHOLD,
            matrix_entries=matrix_entries,
        )

        self._send_json({
            "row_label": row_label,
            "threshold": THRESHOLD,
            "matrix_found": bool(matrix_entries),
            "matrix_spec_item_count": matrix_spec_count,
            "matrix_term_count": matrix_term_count,
            "subitems": [m.to_dict() for m in matches],
        })

    def _handle_stage3(self, payload: dict):
        row_label = (payload.get("row_label") or "").strip()
        item_id = (payload.get("item_id") or "").strip()
        if not row_label or not item_id:
            self._send_json({"error": "row_label と item_id は必須です"}, 400)
            return

        subitems = extract_subitems(XML_PATH, row_label=row_label)
        subitem = next((s for s in subitems if s.item_id == item_id), None)
        if subitem is None:
            self._send_json({"error": f"{row_label}の項 に号 item_id={item_id} が見つかりません"}, 404)
            return

        row_id = get_row_id_by_label(row_label)
        matrix_entries = load_matrix_entries(MATRIX_XLSX_PATH, row_id) if row_id else []
        matrix_entry = find_entry(matrix_entries, item_id)

        # 別表条文本文（一文として）＋ 貨物等省令の対応条文（枝番ごとの行）
        # の両方から数値仕様条件を抽出する。前者は委任なしで別表自体に
        # 数値基準が書かれているケース、後者は「経済産業省令で定める
        # 仕様のもの」に委任されているケースをカバーする。
        source_lines = [subitem.text]
        if matrix_entry is not None:
            source_lines.extend(matrix_entry.ministerial_lines)
        criteria = extract_spec_criteria(source_lines)

        self._send_json({
            "row_label": row_label,
            "item_id": item_id,
            "label": subitem.label,
            "item_text": subitem.text,
            "ministerial_refs": matrix_entry.ministerial_refs if matrix_entry else [],
            "criteria": [c.to_dict() for c in criteria],
        })


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if not XML_PATH.exists():
        print(f"[ERROR] 輸出令XMLが見つかりません: {XML_PATH}", file=sys.stderr)
        sys.exit(1)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"=== FEFTA 該非判定デモサーバー ===")
    print(f"ブラウザで {url} を開いてください（Ctrl+Cで終了）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。")


if __name__ == "__main__":
    main()
