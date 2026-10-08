# First Release GUI v2

## Purpose

通常操作を`CSVを選ぶ -> 保存先を決める -> 変換する`の3段階へ絞る。内部処理は従来どおり厳格に行い、画面上では非IT利用者が次の操作を判断するために必要な情報だけを表示する。

## Main Flow

1. `変換するCSV`で入力ファイルを選択する。
2. 既存Input Adapterによるstrict parseが成功した場合だけ、形式名、logical journal件数、Domain Modelから取得した期間を表示する。
3. `保存先`を指定する。
4. 初期設定済みの場合は既存FirstReleaseConversionWorkflowで自動的に実行前確認を行う。
5. `変換できます`の場合だけ`変換する`を有効にする。

ProfileまたはJDL Contextが未設定の場合は、通常フローを増やさず`設定を確認する`から会社設定画面へ移動する。保存済みProfileがexactly 1件の場合だけ選択状態にする。JDL Contextのunsafeな自動探索・自動選択は行わない。

## Screen States

- `変換できます`: backendがREADYで、変換ボタンが有効。
- `確認が必要です`: Mapping、会社設定、JDL設定など人間確認で解消可能。
- `変換できません`: unsupported format、validation failure、unsafe condition。
- `変換が完了しました`: 件数、貸借一致、Error件数、Output Validation、保存先を表示。

色だけに依存せず、status textと記号を併記する。内部enumは通常画面へ出さない。

## Hidden Internal Concepts

次の概念はbackendに維持するが、通常画面には表示しない。

- ConversionProfile ID、Format ID
- Adapter Registry、Evidence level
- JdlTargetContext JSON path
- internal readiness/conversion enum
- technical mapping status

設定画面でも名称は`対応設定`、`JDL設定`とし、生の内部identityは表示しない。

## Safety Boundaries

- 変換可否はGUIで再実装せず、FirstReleaseConversionWorkflowへ委譲する。
- source overwrite、existing output、Mapping、Context、Evidence scope、atomic outputの規則は変更しない。
- Money Forwardはstrict parserによる形式認識表示に限定し、production routeを有効化しない。
- unknown formatは推測せず、対応外として表示する。
- Error表示に会計本文を含めない。

## Future Work

- JDL Contextの安全なローカル保存・会社単位選択
- 複数会社向けの分かりやすい設定選択
- 明示的なMapping確認画面
- Windows実機でのfocus order、high DPI、screen reader確認

これらはproduction scopeやEvidence gateを変更せず、別作業として扱う。
