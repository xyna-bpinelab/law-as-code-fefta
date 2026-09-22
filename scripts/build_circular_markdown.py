#!/usr/bin/env python3
"""経済産業省が公開する運用通達PDF（jurisdictions/jp/raw/circulars/）を
`pdftotext -layout` でテキスト化し、Jev/RAG検索用のMarkdownへ変換する。

法律・政令・省令と異なり、通達はe-Gov法令APIの対象外でXML構造化もされて
いないため、レイアウト保持のプレーンテキスト抽出＋ページ区切りの付与に
とどめる（見出しの完全な構造化は行わない）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "jurisdictions/jp/raw/circulars"
MARKDOWN_DIR = REPO_ROOT / "jurisdictions/jp/processed/markdown/circulars"

CIRCULARS = [
    {
        "pdf": "unyou_tsutatsu.pdf",
        "title": "輸出貿易管理令の運用について",
        "source_url": "https://www.meti.go.jp/policy/anpo/law_document/tutatu/26fy/unyou_tsutatsu.pdf",
        "note": "輸出注意事項62第11号・62貿局第322号（S62.11.6）",
    },
    {
        "pdf": "kamotsu-kaishaku.pdf",
        "title": "輸出令別表第１の解釈（表）",
        "source_url": "https://www.meti.go.jp/policy/anpo/law_document/tutatu/26fy/kamotsu-kaishaku.pdf",
        "note": "「輸出貿易管理令の運用について」１－１（７）（イ）の別掲表",
    },
]


def extract_text(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def build_markdown(circular: dict, raw_text: str) -> str:
    pages = raw_text.split("\f")
    # pdftotextは末尾に空ページを付与することがあるため除去する
    while pages and not pages[-1].strip():
        pages.pop()

    lines = [
        f"# {circular['title']}",
        "",
        f"- 出典: {circular['note']}",
        f"- 原本URL: {circular['source_url']}",
        f"- 原本PDF: `jurisdictions/jp/raw/circulars/{circular['pdf']}`",
        f"- 総ページ数: {len(pages)}",
        "",
        "> このMarkdownは原本PDFを `pdftotext -layout` でテキスト化したものです。",
        "> 表・罫線等のレイアウトは崩れている場合があるため、正確な内容確認には原本PDFを参照してください。",
        "",
    ]

    for i, page_text in enumerate(pages, start=1):
        lines.append(f"---\n\n**p.{i}**\n")
        lines.append(page_text.strip("\n"))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    print("=== 運用通達PDF -> Markdown 変換 ===")
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

    for circular in CIRCULARS:
        pdf_path = RAW_DIR / circular["pdf"]
        if not pdf_path.exists():
            print(f"  [SKIP] {circular['pdf']} が見つかりません（{pdf_path}）")
            continue

        print(f"[INFO] {circular['title']} を変換中... ({pdf_path.name})")
        raw_text = extract_text(pdf_path)
        if not raw_text.strip():
            print(f"  [ERROR] テキスト抽出結果が空です: {pdf_path}")
            continue

        md_text = build_markdown(circular, raw_text)
        out_path = MARKDOWN_DIR / (pdf_path.stem + ".md")
        out_path.write_text(md_text, encoding="utf-8")
        print(f"  [OK] -> {out_path.relative_to(REPO_ROOT)} ({len(md_text):,} 文字)")

    print("=== 完了 ===")


if __name__ == "__main__":
    main()
