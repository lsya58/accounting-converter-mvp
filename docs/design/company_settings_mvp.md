# 会社設定 MVP

## 目的

会社設定は会計domainではなく、既存のConversion Profileと検証済みJDL設定をユーザー単位で束ねるローカルApplication設定である。Mapping、JDL master、仕訳本文は複製しない。

## 保存構造

Windowsでは`%LOCALAPPDATA%/AccountingConverter`配下を使用する。

```text
profiles/<profile-id>.json
companies/<company-setting-id>/company.json
companies/<company-setting-id>/jdl-context.json
preferences.json
```

JDL設定は既存Loaderで検証してから会社専用directoryへatomic copyする。`company.json`には相対path、Profile ID、source/target format identity、Profile/Context fingerprintだけを保存し、絶対pathや会計本文は保存しない。

## 利用時検証

会社設定は使用時に毎回resolveする。ProfileまたはContextの欠落、fingerprint変更、format identity不一致、JDL製品/version不一致、target masterとのMapping不一致、補助親科目不一致、fuzzy matching許可、自動置換許可はBLOCKする。表示は「会社設定を確認してください」とし、内部IDやfingerprintを通常画面へ出さない。

## 選択

入力CSVのexact source formatと一致する利用可能な会社設定が1件だけなら選択できる。複数候補を会社名やファイル名で推測しない。最後に使用したIDはpreferencesへ保存し、存在し、exact source formatが一致し、staleでない場合だけ復元する。

## 互換性と範囲

Conversion Profile schema v3とJDL Context schema v1は変更しない。従来のProfile/JDL設定直接選択は移行用fallbackとして残す。会社設定の追加によってproduction Registry、Evidence gate、Money ForwardからJDLへのREADY範囲は変更しない。JDL master自動取得、税・補助・部門Mapping UIは次段階とする。

## Money Forward対応設定の初回作成

Money Forward用Profileがない場合に限り、会社追加画面から仕訳CSVと確認済みJDL設定を明示選択して科目対応を作成できる。CSVは`MoneyForwardInputAdapter`でexact parseし、永続保存しない。必要科目は既存`MappingRequirementExtractor`から取得する。

source科目名とJDL masterの名称・正式名称が完全一致し、候補が一意でも、候補表示に留める。各行でユーザーが「確認しました」を選んだ後にだけ、既存`MappingConfirmationService`を通じて`USER_CONFIRMED`としてschema v3 Profileへ保存する。fuzzy、contains、表記補正、AI推測は行わない。

初回MVPは科目mappingだけを対象とする。補助科目、部門、税区分、取引先、インボイス、タグ、メモが入力に含まれる場合、値を捨てず種類だけを表示してProfile作成をBLOCKする。Profile作成後もMoney Forward production Adapter登録とREADY gateは変更しない。
