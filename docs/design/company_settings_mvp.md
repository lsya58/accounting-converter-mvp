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

Conversion Profile schema v3とJDL Context schema v1は変更しない。従来のProfile/JDL設定直接選択は移行用fallbackとして残す。会社設定の追加によってproduction Registry、Evidence gate、Money ForwardからJDLへのREADY範囲は変更しない。Mapping作成、JDL master自動取得、税・補助・部門Mapping UIは次段階とする。
