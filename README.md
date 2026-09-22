# law-as-code-fefta

日本の外国為替及び外国貿易法（外為法）・輸出貿易管理令・関連省令・運用通達を機械可読化し、安全保障貿易管理の該非判定・許可区分判定を支援するナレッジベース＋実行エンジン。「Jev」（[TypeSafe AI](https://docs.typesafe.ai/) の System One モデル）による構造化判定と、決定的な `hard_rule` 判定を組み合わせるハイブリッド方式を採用する。

## ディレクトリ構成

```text
law-as-code-fefta/
├── jurisdictions/jp/
│   ├── raw/                    # e-Gov法令API/METIから取得した原典（XML・PDF）
│   │   ├── laws/                    外為法の全改正履歴
│   │   ├── cabinet_orders/          輸出貿易管理令の全改正履歴
│   │   ├── ministerial_orders/      貨物等省令の全改正履歴
│   │   └── circulars/               運用通達・役務通達（PDF原本）
│   ├── processed/               # ナレッジツリーJSON（許可区分・特例判定）
│   ├── jev_prompts/             # Jev(TypeSafe Noul)向けプロンプト定義
│   └── dsl/                     # (将来の述語論理コード配置用)
├── core/                        # 決定木実行エンジン・分類プロトタイプ
├── scripts/                     # 各種CLIツール
├── tests/                       # 自動テスト（53件）
├── examples/                    # CLI動作確認用のサンプル入力
└── .github/workflows/           # 法令XMLの週次自動同期
```

## できること

### 1. 法令原典の自動取得・追従（Phase 1）

`scripts/fetch_jp_law_history.py` が e-Gov法令API v2から外為法・輸出令・貨物等省令の**全改正履歴**をXMLで取得し、Git diffが読みやすいようインデント整形して保存する。`.github/workflows/sync-jp-fefta-history.yml` により毎週自動同期される。

運用通達（輸出貿易管理令の運用について／輸出令別表第１の解釈／外為令別表中解釈を要する語／役務通達）はe-Gov API対象外のため、METI公式サイトから個別に取得し `jurisdictions/jp/raw/circulars/` にPDF原本として保存している。

### 2. 許可区分・特例判定のナレッジツリー

`jurisdictions/jp/processed/*.json` に、包括許可（一般包括・特別一般包括・特定包括）の判定と、輸出令第4条の各種特例（少額特例・無償修理特例・手荷物特例）の判定を、`hard_rule`（決定的条件式）と `hybrid_jev`（Jevによる自然言語判断）を組み合わせたノードグラフとして定義している。

### 3. 決定木実行エンジン（`core/`）

- `core/expr.py`: `item.is_list_controlled == true` 等の条件式を、`eval()`を使わずASTベースで安全に評価するミニ言語
- `core/jev_client.py`: `MockJevClient`（APIキー不要、ツリー自身の条件式で即時判定）と `TypeSafeJevClient`（実際にTypeSafe AIのNoulプリミティブを呼ぶ）
- `core/tree_engine.py`: ルートから終端の判定結果まで木を辿り、全ステップのトレースを返す

```bash
# モック評価（APIキー不要）
python3 scripts/run_tree.py --tree exemption_tree --facts examples/exemption_repair_ok.json

# 実際にJevを呼ぶ場合（要 pip install typesafe-sdk, TYPESAFE_API_KEY）
python3 scripts/run_tree.py --tree inclusive_license_tree --facts examples/inclusive_license_special_general_ok.json --live
```

### 4. 該非判定の多段階・述語論理プロトタイプ

自然文の製品・技術説明から、輸出令別表第一のどの項番・号に該当し得るかを推定するプロトタイプ。単純な1問合わせでは精度・監査性に限界があるため、以下のように段階的に精緻化している。

1. **行レベル粗判定・複数該当対応**（`core/list_classifier.py`）— 別表第一の全17項について、項ごとに独立した`Noul`質問を1回のAPI呼び出しにまとめて判定する（`Choice`と異なり複数項が同時に該当してよい）
2. **号単位への分解・除外節のhard_rule化**（`core/predicate_extractor.py`）— 対象行をXMLの`<Sentence>`単位で号（一）〜（五十二）に分解し、「〜の項の中欄に掲げるものを除く。」等の除外節を正規表現で抽出、他の号・行が該当する場合に機械的に抑制する
3. **貨物等省令の数値スペックの統合**（`core/ministerial_spec_lookup.py`）— 別表第一の「経済産業省令で定める仕様のもの」という委任文言に対応する貨物等省令の条文を機械的に検索し、Jevの判定材料に加える
4. **用語解釈PDFの号単位統合**（`core/kaishaku_lookup.py`）— 運用通達別紙「輸出令別表第１の解釈」から、号ごとに実際に使われる用語の定義だけを双方向部分文字列マッチングで紐付ける（項全体をまとめて渡すと無関係な号への誤爆が起きるため）

```bash
python3 scripts/classify_predicates.py \
  --xml jurisdictions/jp/raw/cabinet_orders/<輸出令XML> \
  --row 九 \
  --description "<製品・技術の自然文説明>" \
  --ministerial-xml jurisdictions/jp/raw/ministerial_orders/<貨物等省令XML> \
  --kaishaku-pdf jurisdictions/jp/raw/circulars/kamotsu-kaishaku.pdf
```

## セットアップ

```bash
pip install typesafe-sdk pdfplumber   # --live実行・用語解釈PDF抽出に必要
export TYPESAFE_API_KEY="..."          # https://console.typesafe.ai/keys で取得
```

## テスト

```bash
python3 -m unittest discover -s tests -v
# または: pytest tests/
```

53件のテストが、両ナレッジツリーの全終端結果への到達、条件式エバリュエータの安全性、号単位分解・除外節抽出の正確性、貨物等省令・用語解釈PDFとの対応付けを、実際にコミットされている法令データに対して検証する（TypeSafe API呼び出し部分はモッククライアントで代替し、APIキーなしで実行できる）。

## 注意事項

- 本リポジトリの分類・判定プロトタイプは**一次スクリーニングの試作**であり、実際の該非判定・許可要否判断の代替ではない。低確信度・僅差の複数該当・機械的に解決できない除外節（`needs_manual_review`フラグ）は、必ず有資格者による確認を要する。
- Jev（TypeSafe AI）は自由文の理由づけを返さない設計のため、判定根拠の説明が必要な場合は別途、通常のLLMによる二段構成が必要（未実装）。
