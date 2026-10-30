# MF subaccount candidates and pending tax Evidence

最終更新: 2026-10-30

この文書はprivateな仕訳・取引先名を含まない集計です。顧客名や摘要は記録しません。

## 新しいJDL科目一覧

HumanがJDL IBEX 出納帳35.5から出力した「MF→JDL科目-売掛金・預り金補助追加.pdf」を基準とする。Ghostscriptで抽出したPDF文字層では、以前の科目一覧に対し、売掛金1551配下の補助が0→9、預り金3271配下が0→3となった。未払金3181は1、普通預金1311は3で件数不変。GUIの正式なPDF読込・保存・Windows CompanySettingへの反映は、この監査では実施していない。

JDL公式30列モデルの借方・貸方補助名称は各10文字。今回のHuman実機画面でも10文字上限を確認した。現行アプリでは35.5の補助reviewにこの制約を表示し、候補検索だけに10文字prefixを使用する。保存済みidentityやformal outputの比較条件は変更しない。

## 候補監査

MF実CSVには14種類の補助identityがあり、売掛金9、預り金3、未払金1、普通預金1。追加された12補助の候補監査結果:

| MF親 | 入力元種類 | JDL同親の候補 | 正規化後一致 | 先頭10文字一致 | 候補なし | 先頭10文字衝突 |
|---|---:|---:|---:|---:|---:|---:|
| 売掛金 | 9 | 9 | 5 | 4 | 0 | 0 |
| 預り金 | 3 | 3 | 3 | 0 | 0 | 0 |

追加12種類のうち、候補発見率は12/12。これはHuman-confirmed mappingの精度やREADYを意味しない。Windowsの「補助科目13設定」には、PDF追加12種類以外の設定も含まれ得るため、この監査だけで13設定すべての保存状態は確定できない。今回のPDFに候補がない追加12種類は0件だが、Humanが新規作成すべき件数は現在のCompanySettingを再確認するまで0と断定しない。

候補検索はNFKCと空白差の吸収のみ行う。株式会社・有限会社などの意味を持つ語は削除しない。優先順位は正規化後一致、10文字prefix、その他のprefix、類似、その他。類似度は表示順にだけ使い、自動選択・自動保存しない。同じ10文字prefixを複数のMF補助が持つ場合は警告する。

正式mappingは入力元親・補助identityとJDL親・補助コードに紐づける。既存の保存処理はtarget code、target name、parent、policyを記録し、master更新時に親・code・nameを照合する。既存のUSER_CONFIRMED mappingは候補順位付けで変更しない。親変更時は候補と選択を再計算する。

短縮名の自動提案は今回実装しない。先頭10文字は衝突や識別性の問題があり、実際のJDL登録名をPDFで観測してからHumanが選ぶ方が安全。候補がなければJDLで補助作成、科目一覧再出力、アプリで更新、review再確認という導線を使う。

## Tax Evidence待ち

現在のContextはJDL IBEX 出納帳35.5、課税・税抜・原則課税・一括比例配分方式。次の4 source tax identityは`MF-JDL-TAX-EVIDENCE-MISSING-EXACT`で`SYSTEM_EVIDENCE`扱い。

| Tax identity | 影響行 | 観測した構造 | 追加で固定する条件 |
|---|---:|---|---|
| 対象外仕入 | 11 | 借方、4D6C×5・5D7C×1・5D8C×5 | grouping、物理行順、相手側tax、各account/subaccount |
| 課税売上10% | 65 | 貸方1D1C、取引先あり18・なし47 | 取引先摘要policy有無、相手側tax、account/subaccount |
| 非課税仕入 | 10 | 借方1D1C | 税率blank、相手側tax、account/subaccount |
| 非課税売上 | 2 | 貸方1D1C | 税率blank、相手側tax、account/subaccount |

各identityのsource account組合せは順に3、5、2、1種類。Evidence signatureは単なるtax literalではなく、route、shape、行順、借貸side、target account/subaccount、source tax identity、取引先有無、Tax Contextを含む。amount semantics、税額、入力方式、opposite tax、摘要、groupingもstrict comparisonで確認する。

既存P01〜P07は課税仕入10%または対象外を含むexact signatureに限定される。対象外仕入は対象外と異なるsource identityで、課税売上10%・非課税仕入・非課税売上も別tax identity。旧税込Contextの実機Evidenceを現在の税抜Contextへ流用しない。

### 最小batch計画

確認済みtarget identityとcurrent Tax ContextをWindowsのCompanySettingから取得した後に、同じ会計期間内の複数probeを1つのNOT_FOR_PRODUCTION Importバッチへまとめられる。少なくとも上記shape別・取引先有無別・account/subaccount signature別のcaseを含める。batch全体を1つの万能Evidenceにせず、caseごとにImport/re-export strict comparisonを行う。予期しない差分があるcaseは昇格しない。

このLinux workspaceにはWindows保存済みCompanySettingの確認済みtarget mappingとTax Context snapshotがないため、exact JDL candidateはまだ生成しない。probe path/status: 未生成 / `PENDING_CONFIRMED_TARGET_CONTEXT`。Humanの次の操作は最新PDFをCompanySettingへ読み込み、補助mappingを確認すること。税4種類のprobe作成と実機比較はSYSTEM_EVIDENCE担当。

## 次のcoverage gate

480/482（99.59%）はformal scope projectionであり、Tax EvidenceとHuman mappingが揃ったREADY数ではない。481/482には1D2Cまたは10D9Cの一方のexact Evidenceと実装検証、482/482には両方が必要。各shapeが実JDL Import/re-exportに失敗する場合はcoverageを引き上げない。全482件のformal batchは全blocker解消後にだけ出力する。
