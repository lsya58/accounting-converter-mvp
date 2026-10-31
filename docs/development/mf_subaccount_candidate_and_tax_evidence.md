# MF subaccount candidates and pending tax Evidence

> **履歴資料（2026-10-30時点）**: ここにある件数・blocker・Evidence待ちは当時の状態です。現在地は [Current Evidence Status](current_evidence_status.md) を参照してください（2026-10-31時点で482/482 READY、記載のEvidence待ちはすべて解消済み）。


最終更新: 2026-10-31

この文書はprivateな仕訳・取引先名を含まない集計です。顧客名や摘要は記録しません。

## 新しいJDL科目一覧

HumanがJDL IBEX 出納帳35.5から出力した「MF→JDL科目-売掛金・預り金補助追加.pdf」を基準とする。Ghostscriptで抽出したPDF文字層では、以前の科目一覧に対し、売掛金1551配下の補助が0→9、預り金3271配下が0→3となった。未払金3181は1、普通預金1311は3で件数不変。GUIの正式なPDF読込・保存・Windows CompanySettingへの反映は、この監査では実施していない。

JDL公式30列モデルの借方・貸方補助名称は各10文字。最新の実JDL登録済み科目一覧では、売掛金1551/補助0006の名称はUnicode 12文字・CP932 20バイトであり、Pythonの`len <= 10`では誤って拒否される。追加12補助はすべてCP932 20バイト以内だった。35.5の補助名称欄だけを全角10文字相当（CP932 20バイト以内）で検証する。候補検索の先頭10文字prefixは選択順位用であり、名称長のvalidationではない。20バイトを超える名称、CP932でlosslessに表せない名称は引き続きBLOCKする。今回の実機観測はmaster登録の事実であり、この補助を含む仕訳CSVのImport/re-export成功を意味しない。

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

Windows保存済みCompanySettingの読み取り可能なsnapshotがある。非課税仕入・非課税売上の各1件は実機Import/re-exportでstrict PASSしたが、実データ全件のformal tax routeは未接続。実データと同じtarget account/subaccount署名はそれぞれ9/10件、2/2件で、署名の異なる1件は別Evidenceが必要。これらはREADY数ではない。

### 現会社JDL自己Exportからの課税売上10%候補

現会社の`売一種` Importは失敗。現会社のJDLで2026-05-23に、借方1111現金/補助なし、貸方6121売上高/補助なし、貸借各1,100円、貸方だけ課税売上10%、摘要`EVID-TAX-SALES10-SELFEXPORT`の1D1CをHumanが入力し、その日をJDL自身からCSV Exportする。実機画面で表示される税入力方法と税額はそのまま観測し、推測でCSV literalを指定しない。実環境へ投入する前にbackupと削除/復元手順を確認する。

`accounting_converter.tools.generate_mf_sales10_selfexport_probe`は、そのExportのmarker行から識別フラグ・借貸科目/補助・金額・貸方課区/税区/入力方法/税額・反対側tax・optional欄を検査する。現master/Tax Contextと一致する場合だけ、2026-05-24の別日で30列/CP932/BOMなし/CRLFの`PENDING_REAL_JDL_IMPORT_REEXPORT` probeをatomic/no-overwriteで生成する。自己Exportはtax literalのprovenanceであってImport Evidenceではない。probeを別途Importし、同日再Exportを既存`compare_probe_patterns`で比較して初めてEvidence判定する。秘密のCSV本体はGitへ入れない。

課税売上10%の`売　上` literalは現会社の自己Export `0871`から取得し、rev2 candidateの実機Import・再Export `0872`でexact 1111/補助なし→6121/補助なし、取引先なしの1件だけstrict PASS。ただし実データ65件の署名一致は0件（別署名8種類）であり、このEvidenceによるformal解放は0件。失敗した`売一種`を再利用しない。詳細は `tests/evidence/e2e/mf_tax_sales10_excluded_proportional_cash/`。

対象外仕入のtarget表現は、05/25の自己Export 0873でHuman選択UI `0 対象外`とCSV上の両側tax欄blank/税額0を分けて観測した。05/26の1D1C probeは実機Import・0874再Exportでstrict PASS。11件は4D6C×5・5D7C×1・5D8C×5、127 physical rowsで、05/27の実機Import・0875再Exportも11件全case strict PASS、unexpected diff 0。tax interaction、各shape、行別摘要は独立Evidenceとして記録し、exact formal routeを接続した。source税区分`対象外仕入`のHuman-confirmed mappingは現Profileでまだ`UNRESOLVED`なので、現実のformal READY/full outputはBLOCKのまま。詳細は `tests/evidence/e2e/mf_tax_outpur_excluded_proportional_cash/` と `tests/evidence/e2e/mf_tax_outpur_compound_11/`。

## 次のcoverage gate

481/482（99.79%）は1D2C実機Evidenceを含む構造projectionであり、Tax EvidenceとHuman mappingが揃ったREADY数ではない。1D2Cのexact output preflight/serializer接続は実装済み。482/482の構造projectionには10D9Cの独立Evidenceと実装検証が必要。全482件のformal batchは全blocker解消後にだけ出力する。
