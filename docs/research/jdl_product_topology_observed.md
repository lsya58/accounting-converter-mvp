# JDL Product Topology Observed

## 目的

JDL製品群の実運用上の位置づけを、正式仕様ではなくObserved Evidenceとして整理する。

この文書には顧客名、会社名、実金額、摘要、個別科目名、個別補助科目名、raw CSV rowを記録しない。

## JDL IBEX 出納帳 35.5

- role: primary MVP import target candidate
- deployment: 各従業員PCにstandaloneでインストール
- operational use: 日常の会計入力作業
- UI evidence:
  - 「会計データ変換」機能を観測
  - 「会計データ入出力設定」画面を観測
  - `1: 入力 [CSVファイル -> 仕訳ファイル]` を観測
  - `2: 出力 [仕訳ファイル -> CSVファイル]` を観測
  - `8: 入力 [入出金明細 -> 仕訳ファイル]` を観測
- current interpretation:
  - CSVから仕訳ファイルへ変換する入力経路の存在は確認済み
  - 30-column observed CSVがImport形式そのものかは未検証
  - Export CSVとImport CSVの対称性は仮説
  - EXP-01 candidateのImport成功は未検証

## JDL Server-Side Financial / Accounting System

- role: downstream closing/reporting system
- operational use: 決算・申告時にstandalone側からデータを移行して利用
- update operation: server-side system is operationally auto-updated
- observed UI text:
  - JOBMENU画面に `財務システム38` と表示
- current interpretation:
  - `財務システム38` は観測文字列として記録する
  - product versionとしてhardcodeしない
  - MVPの直接CSV import targetとはまだ扱わない

## JDL Accounting 21-Column Journal List Export

- role: downstream / post-import verification research candidate
- observed structure:
  - 21-column journal list export family
  - JDL IBEX出納帳30-column observed schemaとは別構造
- current interpretation:
  - JDL側に登録された結果をread-onlyに確認する候補
  - 30-column import candidateへ流用しない
  - Common Journal Modelへ自動昇格しない

## JDL Accounting 8-Column Balance Trial Report Export

- role: report/export evidence
- observed structure:
  - 8-column report family
  - 仕訳import formatとは別
- current interpretation:
  - report/export family evidenceとして保持
  - import candidate researchには使わない

## MVP Target Assessment

現時点のMVP直接出力ターゲット候補は、JDL IBEX出納帳 35.5が最も自然である。

理由:

- 日常入力がJDL IBEX出納帳で行われている。
- JDL IBEX出納帳 35.5でCSVから仕訳ファイルへ変換する入力経路がUI上確認された。
- 決算・申告時のJDL server-side移行は既存業務フローに含まれる。

ただし、正式JDLOutputAdapter、正式JDL FormatProfile、`VERIFIED_BY_REAL_IMPORT` への昇格は、EXP-01等の実Import成功確認後にのみ検討する。
