# First Release 初回セットアップ

## アプリ本体と会社別設定

AccountingConverter本体には、会社固有の科目対応やJDL masterを同梱しない。

- アプリ本体: 全利用者共通のexeとruntime
- ConversionProfile: sourceからtargetへの、人間が確認したMapping
- JDL Target Context: 今回取り込む会社のJDL環境を確認したsnapshot

ConversionProfileとJDL Target Contextは別ファイルである。どちらも会社固有であり、別会社へ流用しない。配布ZIPにはJSONを入れず、管理者が会社ごとに安全な経路で渡す。

## 新しいPCでの導入

1. 管理者から、対象会社専用のConversionProfile JSONとJDL Target Context JSONを受け取る。
2. `AccountingConverter.exe`を起動する。
3. 「変換設定」の「設定を追加」を押し、ConversionProfile JSONを選択する。
4. 追加完了後、dropdownに対象Profileが表示・選択されていることを確認する。
5. 入力CSVを選択する。
6. 「JDL設定（会社別）」の「選択」を押し、同じ会社のJDL Target Context JSONを選択する。
7. 新しい出力先を指定して実行前チェックを行う。
8. `READY`、未確認Mapping 0、会社・製品/version・税設定を確認してから変換する。
9. 最初は少量の完全に確認可能な仕訳だけを使う。
10. JDL Import前に必ずバックアップし、取込後に件数と代表仕訳を目視確認する。

`READY`でなければ変換しない。`SUCCESS`かつOutput Validation成功でなければJDLへImportしない。

## ConversionProfile Importの安全条件

GUIの「設定を追加」は、次を満たすファイルだけをローカルProfile storeへ保存する。

- UTF-8 JSONとして読める
- ConversionProfile schema versionが現行version
- 必須fieldとFormatIdentityがvalid
- First ReleaseのYayoi AE19 direct exportからJDL IBEX出納帳35.5へのidentityと一致または既存規則上compatible
- 全Mappingが`USER_CONFIRMED`でtarget値を持つ
- 同じProfile IDまたはProfile名が未登録

保存先はWindowsユーザーごとの`%LOCALAPPDATA%\AccountingConverter\profiles`である。既存Profileは上書きしない。Import元JSONは変更しない。不正JSON、未対応schema、未確認Mapping、重複は明示的に停止する。

## JDL Target Contextの選択

JDL Target ContextはProfile storeへImportしない。実行ごとに「JDL設定（会社別）」から明示選択する。

Contextは次を表す。

- target product/versionとformat identity
- 会社の消費税処理・部門処理設定
- 確認済み勘定科目master
- 必要な場合の親科目付き補助科目master
- 必要な場合の部門master
- 確認状態とprovenance
- fuzzy matchingなし・自動置換なし

未確認Context、別version、別会社のmaster、Profileとの不一致はBLOCKされる。

## 父親事務所用設定の作成に必要な情報

### Source side

- 実際に使用する弥生会計の製品名・version
- そのversionから直接Exportした、完全架空のsynthetic仕訳CSV
- pilotで出現するsource勘定科目名
- pilotで使用する場合だけ、親科目付き補助科目、部門、税区分
- Export操作経路と、Excel等で再保存していないことの確認

### Target JDL side

- JDL製品名・version。First Release対象はJDL IBEX出納帳35.5
- 対象会社の消費税処理。初回pilot対象は免税
- 部門処理の有効/無効
- 勘定科目masterのMapping値、master code、名称、正式名称
- 補助を使う場合だけ、親勘定科目、master code、出力code/nameとその確認証拠
- 部門を使う場合だけ、master code、出力code/name、正式名称
- 設定を誰が・どの実機で確認したかを示すprovenance

### Mapping decision

- source勘定科目からJDL勘定科目へのexact Mapping
- JDL target codeと正式名称
- 補助科目を使う場合のsource親科目context
- unresolvedが0であること
- 各Mappingを利用者または管理者が明示確認したこと

値が不足する場合は推測せず、Profile/Contextを作成しない。

## First Pilot Scope

- 1社
- 少量仕訳
- source identityを実CSVで確認済み
- JDL IBEX出納帳35.5
- 免税、税情報なし
- 補助科目なし、部門なし
- exact confirmed Mapping、unresolved 0
- verified simpleまたは対応済みcompound/groupだけ
- 新しいoutput path

実環境がこのscopeと異なる場合は、無理に`READY`へせず追加Evidenceを取得する。

## Private Setup Bundle

会社別設定はrepo外、またはGit管理外の`data/private/`で次のように管理できる。

```text
OfficeSetup/
├── conversion_profile.json
├── jdl_target_context.json
└── 導入手順.txt
```

このbundleをアプリ配布ZIPへ混ぜない。メール誤送信や会社間取り違えを避け、安全な受渡し方法を管理者が決める。schema-validであっても、人間の確認がないtemplateをREADY設定として配布しない。
