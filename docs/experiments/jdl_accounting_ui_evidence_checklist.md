# JDL UI Evidence Checklist

## 目的

JDL IBEX出納帳 35.5およびJDL会計/server-side財務システムのCSV/仕訳取込仕様を推測せず、実機画面で確認できる範囲のEvidenceを集める。

この手順では取り込み実行を行わない。実顧客データは使用しない。画面やメモに顧客名、摘要、個別金額、実口座名などが写り込まないようにする。

最優先対象は、JDL IBEX出納帳 35.5の「会計データ変換」->「1:入力 [CSVファイル -> 仕訳ファイル]」を選択した後の画面である。

次の最優先対象は、JDL IBEX出納帳 35.5の `データ管理・選択 -> CSV入力 -> データ種類: 仕訳データ` のHELPと、rejection時のログ表示内容である。

## 取得したい画面・情報

- 製品名とVersion情報
- JDL IBEX出納帳 35.5の「会計データ変換」メニュー
- 「会計データ入出力設定」画面
- `1:入力 [CSVファイル -> 仕訳ファイル]` 選択後の画面
- `2:出力 [仕訳ファイル -> CSVファイル]` の存在確認
- import dialogの初期表示
- file type selector
- format / layout / field mapping画面
- 文字コード、区切り文字、ヘッダー有無などの設定
- account/subaccount handling
- tax handling
- department handling
- import options
- validation/preview画面の有無
- sample/template出力機能の有無
- help / manualへの導線
- error確認画面またはlog出力先
- CSV入力画面のHELP内容
- rejection時のログ表示内容
- JDL server-side financial/accounting systemの製品名/VersionまたはJOBMENU表示

## 撮影・記録時の注意

- テスト会社または空の検証用会社で開く。
- 実顧客名、実取引先名、実摘要、実金額を画面に出さない。
- 取込実行ボタンは押さない。
- `CSVファイル -> 仕訳ファイル` を選択しても、最終実行・登録はしない。
- HELPやログ表示は、CSV field/layout specificationとエラー詳細が含まれる可能性があるため、画面全体をprivate evidenceとして保存する。
- 設定値は「見えた事実」と「推測」を分けて記録する。
- 画面から読み取った内容を正式仕様として扱わない。

## 期待する成果物

- UI画面のprivate画像またはprivateメモ
- 取込可能なファイル種類の候補
- field mappingやtemplate機能の有無
- import時にJDL側が要求する条件の候補

成果物は `data/private/` 配下に保存し、Git管理対象にしない。
