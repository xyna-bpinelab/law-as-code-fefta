#!/usr/bin/env python3
"""e-Gov法令API v2から日本の法令（外為法・輸出令・貨物等省令）の
全改正履歴XMLを取得し、Git Diffで差分が見やすいようインデント整形して保存する。

対象の法令ID:
    - 324AC0000000228 : 外国為替及び外国貿易法（外為法）
    - 324CO0000000378 : 輸出貿易管理令（輸出令）
    - 403M50000008001 : 貨物等省令

保存ファイル名: {LawId}_{PromulgateDate}_{AmendLawNum}.xml
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import xml.dom.minidom
import xml.etree.ElementTree as ET
from pathlib import Path

API_BASE = "https://laws.e-gov.go.jp/api/2"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 3
REQUEST_INTERVAL_SEC = 0.3

REPO_ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    {
        "law_id": "324AC0000000228",
        "name": "外国為替及び外国貿易法（外為法）",
        "out_dir": REPO_ROOT / "jurisdictions/jp/raw/laws",
    },
    {
        "law_id": "324CO0000000378",
        "name": "輸出貿易管理令（輸出令）",
        "out_dir": REPO_ROOT / "jurisdictions/jp/raw/cabinet_orders",
    },
    {
        # 通称「貨物等省令」正式名称：輸出貿易管理令別表第一及び外国為替令別表の
        # 規定に基づき貨物又は技術を定める省令（平成三年通商産業省令第四十九号）
        "law_id": "403M50000400049",
        "name": "貨物等省令",
        "out_dir": REPO_ROOT / "jurisdictions/jp/raw/ministerial_orders",
    },
]

# ファイル名として使用できない文字を除去する
UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def fetch_json(url: str) -> dict:
    """リダイレクトを追跡しつつJSONを取得する。失敗時はリトライする。"""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "law-as-code-fefta/1.0"}
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = resp.read()
            if not body:
                raise ValueError("empty response body")
            return json.loads(body.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
            last_error = e
            print(f"    [WARN] attempt {attempt}/{MAX_RETRIES} failed for {url}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SEC * attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def build_element(node: dict) -> ET.Element:
    """e-Gov API v2が返すJSONツリー ({'tag','attr','children'}) をElementTreeへ変換する。"""
    tag = node["tag"]
    attrib = {k: str(v) for k, v in (node.get("attr") or {}).items()}
    element = ET.Element(tag, attrib)

    text_parts = []
    for child in node.get("children") or []:
        if isinstance(child, dict):
            element.append(build_element(child))
        else:
            text_parts.append(str(child))
    if text_parts:
        element.text = "".join(text_parts)
    return element


def prettify_xml(element: ET.Element) -> bytes:
    """xml.dom.minidomでインデント整形したUTF-8バイト列を返す。"""
    rough = ET.tostring(element, encoding="utf-8")
    reparsed = xml.dom.minidom.parseString(rough)
    pretty = reparsed.toprettyxml(indent="  ", encoding="utf-8")
    # minidomはテキストノードの周りに空行を挿入することがあるため、Diffを綺麗にするため除去する
    lines = [line for line in pretty.decode("utf-8").splitlines() if line.strip()]
    return ("\n".join(lines) + "\n").encode("utf-8")


def safe_filename_component(value: str) -> str:
    return UNSAFE_FILENAME_CHARS.sub("", value).strip() or "unknown"


def build_filename(law_id: str, revision: dict) -> str:
    # NOTE: amendment_promulgate_date + amendment_law_num だけではファイル名が一意にならない。
    # 同一改正法が段階施行（複数の施行日）される場合、異なる内容のリビジョンが
    # 同じ (促進日, 改正法令番号) を共有し、ファイル名が衝突して取りこぼしてしまう。
    # law_revision_id に含まれる日付は各リビジョンの施行日（適用日）であり、
    # APIの仕様上リビジョンごとに一意なので、こちらを採用して衝突を避ける。
    revision_id = revision.get("law_revision_id", "")
    parts = revision_id.split("_")
    version_date = parts[1] if len(parts) >= 2 and re.fullmatch(r"\d{8}", parts[1]) else ""
    if not version_date:
        version_date = (revision.get("amendment_enforcement_date") or "").replace("-", "")
    if not version_date:
        version_date = (revision.get("amendment_promulgate_date") or "").replace("-", "")

    amend_law_num = revision.get("amendment_law_num") or "制定"
    return (
        f"{law_id}_{version_date or 'unknown'}_"
        f"{safe_filename_component(amend_law_num)}.xml"
    )


def process_law(law_id: str, name: str, out_dir: Path) -> tuple[int, int, int]:
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] {name} ({law_id}) の改正履歴一覧を取得中...")
    revision_list = fetch_json(f"{API_BASE}/law_revisions/{law_id}")
    revisions = revision_list.get("revisions", [])
    print(f"  -> {len(revisions)} 件の履歴バージョンを検出")

    saved = skipped = failed = 0
    for revision in revisions:
        revision_id = revision.get("law_revision_id")
        if not revision_id:
            failed += 1
            print(f"  [ERROR] law_revision_id が存在しないレコードをスキップ: {revision}")
            continue

        filename = build_filename(law_id, revision)
        out_path = out_dir / filename

        if out_path.exists() and out_path.stat().st_size > 0:
            skipped += 1
            continue

        try:
            data = fetch_json(f"{API_BASE}/law_data/{revision_id}")
            full_text = data.get("law_full_text")
            if not full_text:
                raise ValueError("law_full_text が空です")

            root_element = build_element(full_text)
            xml_bytes = prettify_xml(root_element)
            if len(xml_bytes) == 0:
                raise ValueError("整形後のXMLが0バイトです")

            # 0バイトファイルが残らないよう、一時ファイル経由でアトミックに書き込む
            tmp_path = out_path.with_name(out_path.name + ".tmp")
            tmp_path.write_bytes(xml_bytes)
            if tmp_path.stat().st_size == 0:
                tmp_path.unlink(missing_ok=True)
                raise ValueError("書き込み後のファイルが0バイトです")
            tmp_path.rename(out_path)

            saved += 1
            print(f"  [OK] {filename} ({len(xml_bytes):,} bytes)")
        except Exception as e:  # noqa: BLE001 - 個別バージョンの失敗は継続して処理する
            failed += 1
            print(f"  [ERROR] {revision_id}: {e}")
        finally:
            time.sleep(REQUEST_INTERVAL_SEC)

    print(f"[SUMMARY] {name}: 新規保存 {saved} / スキップ(既存) {skipped} / 失敗 {failed}")
    return saved, skipped, failed


def main() -> None:
    print("=== e-Gov法令API v2 全改正履歴取得スクリプト ===")
    total_saved = total_skipped = total_failed = 0

    for target in TARGETS:
        s, sk, f = process_law(target["law_id"], target["name"], target["out_dir"])
        total_saved += s
        total_skipped += sk
        total_failed += f

    print("=== 完了 ===")
    print(
        f"合計: 新規保存 {total_saved} / スキップ {total_skipped} / 失敗 {total_failed}"
    )
    if total_failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
