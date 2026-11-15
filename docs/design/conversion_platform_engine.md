# 共通変換エンジン：現状調査（E0）・設計（E1）・freee試作（E2）・次の方向（E3）

日付: 2026-11-15 / 範囲: 変換エンジンのみ（UI/UXは別トラック） / 既存の動作: **変更なし**

この文書は、利用者の指示（2026-11-15）で始めた「複数の会計ソフト間で安全に変換できる基盤」への調査と最小実装の記録。[開発ロードマップ](../product/開発ロードマップ.md#基盤変更の凍結2026-10-31) の凍結は、ここでは「既存経路の作り替えをしない」制約として守っている（追加したのは新規ファイルだけ）。

## 1. E0：現行エンジンの構造

### 1.1 流れ

```
入力ファイル
  └ 入力アダプター（ソース別・厳密）            adapters/input/{moneyforward,yayoi,jdl}
      └ 共通仕訳モデル JournalEntry               domain/journal.py, journal_rows.py, journal_identity.py
          └ マッピング（Human確認済みのみ）        application/mapping_engine.py, domain/mapping.py
              └ ルート方針・税の意味づけ（ソース別） application/*_workflow.py
                  └ 業務検証（ソース別の欠落ルール） MoneyForwardToJdlLossRule / YayoiToJdlLossRule
                      └ JDL出力 preflight（ソース非依存） adapters/output/jdl/preflight.py
                          └ JDL CSV 書き出し（30列・CP932・CRLF） adapters/output/jdl/adapter.py
                              └ 出力検証・監査・照合       output validator / *.audit.json / roundtrip tools
```

この順序を実行するのは `application/conversion.py` の `ConversionService`（ソース非依存）。ソースごとの workflow（`moneyforward_conversion_workflow.py`、`yayoi_jdl_workflow.py`）が部品を組み立てて渡す。

### 1.2 各要素の現状

| # | 要素 | 実装 | 共通化の状況 |
|---|---|---|---|
| 1 | 入力アダプター | MF: `MoneyForwardObservedParser`（観測19列の完全一致）。弥生: 仕訳日記帳 汎用形式（31列）とインポート形式（25列）を `application/yayoi_sources.py` が1つの口にまとめる。JDL: 移行用 `observed_parser.py` | 基底 `InputAdapter`（supports/read）は共通。厳密さ（ヘッダー完全一致・CP932・BOM拒否・直列化形式）は各パーサーが個別に持つ |
| 2 | 共通仕訳モデル | `JournalEntry`（日付・行・摘要・metadata）、`JournalLine`（貸借・科目・補助・部門・金額・`TaxInfo`）、`SourceReference`（ファイル・行・元の伝票番号） | 複数借方・複数貸方、物理行と行ごとの摘要（`journal_rows`）、内容identity（`journal_identity`）は**共通化済み**。取引先は `LINE_COUNTERPARTY_KEY` で共通 |
| 3 | JDL出力アダプター | `JdlOutputPreflight`：target context・Evidence profile・形・税・補助・部門・振替伝票行数・決算日付・CP932・桁数を検証し、通った計画だけ書く | **ソース非依存**（preflight内に MF/弥生 の参照は0件）。Evidence は JDL が受け取るもの（課区・税区・税入力方法・税額規則・形）で索引 |
| 4 | 科目・税区分マッピング | `MappingRuleSet`（科目・補助・文脈付き補助・部門・税区分）。`USER_CONFIRMED` 以外は出力しない。`ConversionProfile` が source/target の `FormatIdentity` を厳密に束縛 | 仕組みは共通。税の「JDL上の意味」（`tax_semantics.JdlTaxSemantic`）も共通。ただし MF の税込ルート `_TAX_ROUTES` は MF の税区分名で索引（凍結対象として残置） |
| 5 | Evidence の適用範囲 | 形: `row_evidence.JDL_ROW_DESCRIPTION_VERIFIED_SHAPES`（ソース非依存）。税・科目: capability composition（MF/ACTの Tax Context）。会社A: `scoped_evidence` が 1社の設定（税抜・原則・一括比例・端数・16行）に限定 | target 側の Evidence は再利用可能な形になっている。会社スコープ Evidence は類似で広げない |
| 6 | READY/BLOCK | 仕訳ごとの blocker を `HUMAN:` / `SYSTEM_EVIDENCE:` / `SYSTEM_IMPLEMENTATION:` で分類（`yayoi_jdl_workflow.assess`、`readiness_breakdown`）。MF は `tools/mf_formal_readiness.py` | 分類語彙は共通。集計の実装はソース別 |
| 7 | 監査・非保持・検証 | 弥生: JDLに入らない値（部門・付箋・メモ等）を `<出力>.audit.json` に保存し SHA で束縛、READY-only は `.ready_only.json`、承認台帳はハッシュ連鎖。MF: 入らない値は欠落ルールで BLOCK（取引先は Human 確認の変換のみ）。照合: `mf_full_e2e_compare`、`yayoi_roundtrip_check` | **ソース別**。非保持の値は `moneyforward_*` / `yayoi_*` の別キーで持っている |
| 8 | 新しいソースの追加時に必要な変更 | 下表 | |

### 1.3 新しい会計ソフトを入力元に加えるときの変更箇所

| 変更箇所 | 必要な作業 | 既存への影響 |
|---|---|---|
| `adapters/input/<vendor>/` | 厳密パーサー。共通行キー（`journal_rows`）・内容identity・非保持の値を埋める | なし（新規） |
| `profiles/known_formats.py` | `FormatIdentity`／`SchemaDefinition`（製品・版・形式・Evidence水準） | 追加のみ |
| `infrastructure/adapter_registry.py` | 実データで観測後に入力アダプターを登録 | 追加のみ |
| `application/<vendor>_jdl_workflow.py` | 欠落ルール、税区分マッピングの確認画面用データ、ルート方針、監査（弥生の非保持監査を一般化するまでは個別） | 新規 |
| `ui/controllers.py`・`ui_qt/` | 入力元の選択と確認画面（`ui/controllers.py` で弥生に触れる行91・MFに触れる行36） | **UIトラックの担当**。エンジン側は先に CLI で完結させる |
| 照合ツール | 同期間の再Exportとの比較（ソースの列 → JDLの列の期待値） | 新規 |
| JDL target Evidence | 不要（形・税literal はソース非依存）。ただし**新しい税の書き方・形・会社設定**は実機往復が必要 | なし |

## 2. E1：共通変換基盤の設計

### 2.1 基本構造（既存を再利用）

```
入力アダプター → 共通仕訳モデル → 会計・税区分・構造の検証 → 変換先アダプター → 出力・監査・照合
（厳密・ソース別）   （domain）       （mapping + preflight）     （target別）      （target別＋共通の束縛）
```

既存の `ConversionService` がこの順序そのもので、作り替えは不要。不足していたのは「共通モデルで表せない情報の置き場」と「変換方向の段階管理」の2点。

### 2.2 共通仕訳モデルの要件と現状

| 要件 | 現状 | 今回の対応 |
|---|---|---|
| 複数借方・複数貸方 | `JournalEntry.lines`、`is_compound` | 不要 |
| 物理行・行ごとの摘要 | `journal_rows`（共通キー） | 不要（freeeも同じキーを使用） |
| 消費税額と計算条件 | `TaxInfo.tax_amount`・`rate`・`tax_inclusion`。端数・税抜/税込は会社設定（CompanySetting の Tax Context） | 不要。freee は `tax_inclusion` を推測せず `None` |
| 補助科目 | `JournalLine.sub_account`、親科目のみ方針 | 不要。freee は補助を導出しない |
| 決算整理 | 弥生の `yayoi_closing` だけ（ソース別） | **追加**: `ENTRY_CLOSING_ADJUSTMENT_KEY`（生の値のみ。意味の解釈はしない） |
| 原本の識別情報 | `SourceReference`、内容identity、`FormatIdentity` | **追加**: `ENTRY_SOURCE_FORMAT_KEY`（形式の変種＋ヘッダー指紋） |
| 任意項目・失われる情報 | `moneyforward_tags/memos/trade_partner`、`yayoi_optional_values` と別キー | **追加**: `ENTRY_SOURCE_FIELDS_KEY`（`SourceFieldValue`: 列名・値・範囲・行・既知/未知）。既存ソースは `legacy_source_fields()` で読み取り専用に参照（パーサーは変更しない） |

追加した型: `domain/source_information.py`。既存の変換経路はこれを読まないため、出力は変わらない。

### 2.3 Fail-Closed の扱い

- 共通モデルに入らない値は捨てずに `SourceFieldValue` として保持し、変換先が持てなければ BLOCK または Human 判断（既存の MF/弥生 と同じ方針）
- パーサーが知らない列は `known=False` で保持し、その仕訳は `SYSTEM_EVIDENCE:UNKNOWN_SOURCE_COLUMN` で止める
- 既存ソースを新しいキーへ移行するのは、移行前後で監査JSON・出力CSVがバイト一致することを確認できる時だけ（今回は移行しない）

### 2.4 製品・版・税設定・検証済み構造の区別

| 区別 | 置き場 |
|---|---|
| 製品・版・形式・方向・Evidence水準 | 既存 `FormatIdentity.stable_key`（vendor/product/edition/version/format_name/format_version/direction/evidence_level）。`ConversionProfile` が完全一致で束縛 |
| ヘッダーの実物 | freee は SHA-256 の指紋。実サンプルで確認した指紋だけ `VERIFIED_HEADER_FINGERPRINTS` に登録 |
| 税設定 | 既存 CompanySetting の Tax Context（会社単位、Human 確認） |
| 検証済みの構造 | 既存 JDL Evidence（形・税literal・会社スコープ） |
| 変換方向の段階 | **追加**: `domain/conversion_direction.py`（NOT_STARTED / RESEARCH / DIAGNOSE_ONLY / PROBE_ONLY / PRODUCTION）。`ready_allowed` は PRODUCTION のみ。未登録の方向は NOT_STARTED |

## 3. E2：freee会計

公開情報の詳細と未確認事項は [freee 仕訳帳CSV 調査記録](../research/freee_journal_csv_public_spec.md)。

### 3.1 3つの出力の違い

| | 新CSV | 旧CSV | freee標準 JDL形式 |
|---|---|---|---|
| 内容 | 全項目（内部データ含む）、選択不可 | 一般的な項目、取引先等は選択可 | JDL「会計net」の取込形式 |
| 本アプリでの位置づけ | 第一候補（情報が最も多い） | 補助（列が少なく、税額列が無い可能性） | **使わない前提**。IBEX出納帳35.5との互換性は未確認。科目コードの事前割当が freee 側で必要 |
| 強み | 決算書表示名・ショートカット・取引先コードなど対応付けの手がかり | 仕訳番号・作成日時・決算整理区分 | JDL科目コードで出る |

### 3.2 freee CSV の項目と共通モデルの対応

| freee 列（借方/貸方） | 共通モデル | 根拠 | JDL IBEX 35.5 |
|---|---|---|---|
| No. | 仕訳のまとまり（連続する同一番号）、`SourceReference.source_journal_id` | 旧CSVで「複数行の仕訳は同一番号」と記載 | 出力しない（伝票番号は採番） |
| 取引日 | `JournalEntry.date` | 例 2015/03/01 | 日付 |
| 勘定科目 | `JournalLine.account` | 記載あり | 科目（Human確認の対応付け） |
| 決算書表示名 | `SourceFieldValue`（対応付けの手がかり） | 新CSVに記載 | なし。勘定科目と違う場合は口座＝科目＋補助の判断が必要 |
| 金額 | `JournalLine.amount` | 記載あり | 金額 |
| 税区分 | `TaxInfo.category`（生の名前） | 記載あり | 課区・税区・税入力方法（Human確認＋JDL Evidence） |
| 税金額 | `TaxInfo.tax_amount` | 新CSVに記載 | 消費税（JDL Evidence の税額規則に従う） |
| 取引先名／取引先 | `LINE_COUNTERPARTY_KEY`＋`SourceFieldValue` | 記載あり | なし（摘要への追記は Human 確認の変換のみ） |
| 品目・メモタグ・セグメント1〜3・備考 | `SourceFieldValue` | 記載あり（備考は仮定） | なし（非保持として監査記録が必要） |
| 部門 | `JournalLine.department` | 記載あり | 部門（会社が部門を使う場合のみ） |
| 管理番号・仕訳番号・作成日時・各ショートカット・取引先コード | `SourceFieldValue` | 記載あり | なし |
| 決算整理仕訳 | `ENTRY_CLOSING_ADJUSTMENT_KEY`（生の値） | 旧CSVに記載 | 決算整理（13月）は JDL Evidence あり。ただし freee の値の意味が未確認 |
| 摘要 | `LINE_ROW_DESCRIPTION_KEY` | **仮定**（列名未確認） | 摘要（64バイト） |
| 補助科目 | なし（導出しない） | freee の文書化された出力に列なし | 補助 |

### 3.3 既存モデルとの共通化

- MF と同じく「1物理行に借方・貸方の両側」を持つ形なので、物理行・行ごとの摘要・取引先は既存の共通キーで表せた。共通モデルの変更は不要だった
- 違いは、freee に補助科目が無いこと（口座・タグで表す）、税込/税抜・内税/外税が CSV に出ない可能性、取引先がコード付きの構造化データであること
- JDL側の形の Evidence はソース非依存なので、freee の仕訳の形を既存 Evidence と照らせる（診断で件数を表示。適用はしない）

### 3.4 変換で失われ得る情報

取引先（コード・名前・ショートカット）、品目、メモタグ、セグメント1〜3、備考、管理番号、仕訳番号、作成日時、決算書表示名、口座の区別（補助への割当を Human が決めない限り）、税込/税抜の区別（CSV に無い場合は会社設定から）、インボイス関連の区別（列が存在するか未確認）。

### 3.5 freee 固有の税区分・補助・タグ

- 税区分: 「課税売上10%」「課対仕入10%」「課対仕入(控80)10%」のような名前。率・軽減・経過措置の控除割合・個別対応（課対/共対/非対）を名前から**手がかり**として表示するだけで、対応付けはしない。JDL側の表現は既存 `JdlTaxSemantic` に無いもの（控50、個別対応など）は実機 Evidence が必要
- 補助: freee の「口座」と「タグ」をどう JDL 補助にするかは会社ごとの Human 判断。自動導出しない
- タグ: 取引先・品目・部門・メモタグ・セグメント。部門以外は JDL に入らない

### 3.6 試作したもの（合成データのみ）

| ファイル | 内容 |
|---|---|
| `adapters/input/freee/journal_csv.py` | 列名で読む厳密パーサー。UTF-8（BOM有無）・Shift-JIS、UTF-16 と NUL は拒否。新CSV/旧CSV/判定不能、ヘッダー指紋、仮定列・未知列の報告。仕訳単位の拒否理由（番号の再使用・日付・金額書式・片側だけ・貸借不一致・複数日付）。**InputAdapter ではなく、レジストリにも登録しない** |
| `application/freee_diagnosis.py` | blocker の分類（HUMAN / SYSTEM_EVIDENCE / SYSTEM_IMPLEMENTATION）、税区分の手がかり、JDLに列が無い情報の一覧、形の分布。顧客の値は出さない。`formal_ready` は方向が PRODUCTION でない限り 0 |
| `tools/freee_journal_diagnose.py` | 読み取り専用 CLI（件数とコードのみ） |
| `domain/source_information.py`、`domain/conversion_direction.py` | 2.2・2.4 の共通部品 |
| `tests/test_freee_journal_csv.py` | 合成CSVで 17 テスト（ヘッダー指紋を検証済みにしても READY にならないことを含む） |

## 4. E3：次の変換方向

### 4.1 公式の移行機能（調査時点）

| 方向 | 公式機能 | 出典 |
|---|---|---|
| freee → JDL | freee が JDL形式（会計net向け）を出力。科目コードを freee 側で割当 | freee ヘルプ 204614914 |
| freee → 弥生 / MJS / TKC / ICS / 財務応援 | freee が各社形式を出力 | freee ヘルプ（各ページ） |
| 弥生 → MF | MF「他社ソフトデータの移行」で弥生インポート形式を取込。税区分名が一致しなければ「税区分の分類」画面で対応付け | MF 使い方ガイド、弥生サポート ida27187 |
| JDL → MF | MF「他社ソフトデータの移行」に JDL（IBEX出納帳）。課区・税区はタグとして取り込まれ自動マッチしない（MF確定申告ガイドの記載） | MF ガイド、[判断記録](jdl_to_mf_decision.md) |
| MF → 弥生 | MF から弥生形式でエクスポート→弥生で取込（弥生 Next は編集不要と案内） | 弥生 Next 案内、弥生サポート |
| freee/MF → 弥生 Next | 弥生形式のまま取込 | 弥生 Next 案内 |
| PCA / 勘定奉行 → MF | MF が仕訳を取込（勘定奉行は i8/i10/i11 の仕訳ファイル）。科目・開始残高は一部 | MF 使い方ガイド |

### 4.2 比較と優先順位

本アプリの価値は「形式変換」ではなく、**会社ごとの確認済み対応付けの保存・実機往復で裏付けた出力・欠落ゼロの証明（監査）・READY-only と未移行の管理**にある。公式機能はどれも「取込時に画面で対応付け」で、厳密な往復照合と非保持情報の監査は無い。

| 順位 | 方向 | 需要 | 公式との差 | 技術リスク | 再利用 | 判断 |
|---|---|---|---|---|---|---|
| 1 | **freee → JDL IBEX 出納帳** | 父親事務所の流れ（顧問先→事務所JDL）に一致。freee顧問先がいれば即効 | freee標準は会計net向けで IBEX出納帳35.5は未確認。科目コードの事前割当が freee 側で必要 | 中（税込/内外税の表現、口座→補助、実サンプル無し） | JDL target・Evidence・監査・READY-only がそのまま使える | **継続**。実サンプル入手が次の関門 |
| 2 | 将来の PCA・勘定奉行 → JDL | 顧問先次第 | 各社→JDL の公式は不明 | 中 | freee と同じ（入力アダプターだけ） | freee の手順を型にして、実データが来たら |
| 3 | 弥生 → MF | 事務所の流れと逆。需要未確認 | MF 公式が弥生形式を直接取込 | 高（MF target 新規、MF 側の税額検証手段が無い） | 弥生入力は再利用可、出力は新規 | 保留 |
| 4 | MF → 弥生 | 同上 | MF が弥生形式を出力 | 高（弥生 target 新規） | MF 入力は再利用可 | 保留 |
| 5 | JDL → MF | 需要未確認 | MF 公式に JDL 取込あり | 高 | — | 2026-10-31 の NO-GO を維持 |

target を増やす方向（3〜5）は、`OutputAdapter` 実装・target context・target 側の実機 Evidence・照合ツールが全部新規になり、本アプリの強み（厳密往復）を target 側で証明する手段（再Export に税額が出るか等）を先に確かめる必要がある。

## 5. UI と独立して進められること

- freee 実サンプルの CLI 診断と、`VERIFIED_HEADER_FINGERPRINTS`・列表の確定（UI不要）
- freee の税区分名 → JDL 税 semantic の候補表（Human 確認用シート、既存の弥生確認シートの形式）
- 非保持情報の監査を `SourceFieldValue` で一般化（弥生の監査JSONとバイト一致を確認してから）
- freee → JDL の照合ツール（freee の列 → JDL再Exportの列の期待値）
- 既存ソースの `legacy_source_fields` を使った「JDLに入らない情報」一覧の共通化（読み取りのみ）

## 6. 次の実装ステップ

1. **Human**: freee の実エクスポート（新CSV・旧CSV、Shift-JIS/UTF-8）と会社の税設定を入手し `data/private/` に置く（[依頼リスト](../research/freee_journal_csv_public_spec.md#4-実データで確認が必要なこと依頼リスト)）
2. SYSTEM: 実サンプルを `freee_journal_diagnose` で診断し、列表・仮定列・税の表現を確定。指紋を登録（この時点で `ADAPTER` としての登録を検討、方向は DIAGNOSE_ONLY のまま）
3. SYSTEM: freee 用 `FormatIdentity` を `known_formats` に、`ConversionProfile` 用の source identity を定義
4. SYSTEM＋Human: 税区分・科目・口座→補助の確認シート（既存の弥生シートを流用）
5. SYSTEM: freee 専用の欠落ルールと非保持監査（`SourceFieldValue` ベース）。既存の弥生監査は変更しない
6. SYSTEM_EVIDENCE: 既存 Evidence で足りない形・税（控50・個別対応 等）だけ NOT_FOR_PRODUCTION Probe → 検証用の空の JDL 会社で実機往復（既存の実機テストは再実施しない）
7. 実機往復 PASS 後に初めて、方向を PRODUCTION にして READY を許可（会社スコープ）
