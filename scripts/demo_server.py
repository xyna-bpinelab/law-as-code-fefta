#!/usr/bin/env python3
"""別表第一 該非判定プロトタイプの実証用デモサーバー。

自然文の製品・技術説明を入力すると、ブラウザ上でリアルタイムに
輸出令別表第一のどの項番・号に該当し得るかを、実際のTypeSafe AI(Jev)
APIを呼び出して判定・表示する。

標準ライブラリのみで動作する（Flask等は使わない）。

使用方法:
    export TYPESAFE_API_KEY="..."
    pip install typesafe-sdk pdfplumber
    python3 scripts/demo_server.py [--port 8800]
    -> ブラウザで http://127.0.0.1:8800 を開く

API:
    POST /api/stage1  {"description": "..."}
        -> 別表第一の全17項について、行レベルの粗判定結果を返す
    POST /api/stage2  {"description": "...", "row_label": "九"}
        -> 指定行を号単位に分解し、貨物等省令・用語解釈PDFを判定材料に
           加えた細粒度判定結果を返す
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

from core.kaishaku_lookup import find_interpretation_for_row, kanji_row_label_to_zenkaku  # noqa: E402
from core.list_classifier import classify_item, load_table_rows  # noqa: E402
from core.ministerial_spec_lookup import find_spec_for_row  # noqa: E402
from core.predicate_extractor import classify_subitems, extract_subitems  # noqa: E402

XML_PATH = REPO_ROOT / "jurisdictions/jp/raw/cabinet_orders/324CO0000000378_20260605_令和八年政令第百九十四号.xml"
MINISTERIAL_XML_PATH = REPO_ROOT / "jurisdictions/jp/raw/ministerial_orders/403M50000400049_20260214_令和七年経済産業省令第七十二号.xml"
KAISHAKU_PDF_PATH = REPO_ROOT / "jurisdictions/jp/raw/circulars/kamotsu-kaishaku.pdf"
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

        spec = find_spec_for_row(MINISTERIAL_XML_PATH, row_label=row_label)

        kaishaku = None
        if KAISHAKU_PDF_PATH.exists():
            try:
                zenkaku = kanji_row_label_to_zenkaku(row_label)
                kaishaku = find_interpretation_for_row(KAISHAKU_PDF_PATH, row_label=zenkaku)
            except ImportError:
                kaishaku = None  # pdfplumber未インストール

        matches = classify_subitems(
            get_client(), description, subitems,
            stage1_row_matches=stage1_by_id, threshold=THRESHOLD,
            ministerial_spec_text=spec.full_text if spec else None,
            kaishaku_interpretation=kaishaku,
        )

        self._send_json({
            "row_label": row_label,
            "threshold": THRESHOLD,
            "ministerial_spec_found": spec is not None,
            "ministerial_spec_article": spec.article_title if spec else None,
            "kaishaku_found": kaishaku is not None,
            "kaishaku_term_count": len(kaishaku.terms) if kaishaku else 0,
            "subitems": [m.to_dict() for m in matches],
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
