# JDL会計 UI Evidence Checklist

## 目的

JDL会計のCSV/仕訳取込仕様を推測せず、実機画面で確認できる範囲のEvidenceを集める。

この手順では取り込み実行を行わない。実顧客データは使用しない。画面やメモに顧客名、摘要、個別金額、実口座名などが写り込まないようにする。

## 取得したい画面・情報

- 製品名とVersion情報
- CSV/仕訳取込メニューの場所
- import dialogの初期表示
- file type selector
- format / layout / field mapping画面
- 文字コード、区切り文字、ヘッダー有無などの設定
- import options
- sample/template出力機能の有無
- help / manualへの導線
- error確認画面またはlog出力先

## 撮影・記録時の注意

- テスト会社または空の検証用会社で開く。
- 実顧客名、実取引先名、実摘要、実金額を画面に出さない。
- 取込実行ボタンは押さない。
- 設定値は「見えた事実」と「推測」を分けて記録する。
- 画面から読み取った内容を正式仕様として扱わない。

## 期待する成果物

- UI画面のprivate画像またはprivateメモ
- 取込可能なファイル種類の候補
- field mappingやtemplate機能の有無
- import時にJDL側が要求する条件の候補

成果物は `data/private/` 配下に保存し、Git管理対象にしない。
