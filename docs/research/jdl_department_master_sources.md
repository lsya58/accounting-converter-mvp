# JDL Department Master Sources

## Current conclusion

JDL IBEX 出納帳35.5の部門について、30列仕訳CSVに現れた使用済みcode/name、限定的なUI/runtime実験、および部門登録から印刷した部門情報一覧PDFを確認した。PDFは対象synthetic companyのprinted master candidateとして扱うが、1部門・1ページだけのEvidenceなので `FULL_MASTER` とはしない。

後続PDFでは同じ1ページに2部門が1行ずつ連続表示され、code/name/略名称、optional表示欄、malformed 0、conflict 0を再観測した。Evidence IDは `EVID-JDL-MASTER-DEPARTMENT-PRINT-002`。複数行構造は確認できたが、引き続き `OBSERVED_PRINTED_MASTER` であり `FULL_MASTER` ではない。

| Source candidate | Current state | Completeness |
|---|---|---|
| 正式な部門master export | 未確認 | `UNKNOWN` |
| 部門登録から印刷した部門情報一覧PDF | 1ページ・1部門を観測 | `OBSERVED_PRINTED_MASTER` |
| JDL 30列仕訳CSV | code/nameを観測可能 | `OBSERVED_USED_MASTER` |
| 保存済みJDL Target Context | local contextは存在するが、監査対象contextに部門masterなし | context-specific only |
| JDL画面・限定Import実験 | 部門処理有効化と限定値のruntime挙動を観測 | UI/runtime evidence only |

部門PDFではcode、名称、略名称、集計部門、配賦元、配賦基準、推定利益率の表示欄を観測した。codeはPDF上のexact表現を保持し、補助科目の4桁表現を適用しない。略名称の自動生成規則、長さ、truncate規則は推測しない。

30列仕訳CSVの観測値を全masterへ昇格しない。異なる会社・取得元を無条件にmergeせず、code/name conflictは明示的に保持する。今回のPDF identityは既存journal observationsと一致せず、同一codeの別名称が存在したが、複数事業所由来なのでPDFの誤りやglobal conflictとは判定しない。観測部門はprovenance付きのread-only candidateとして扱い、正式Contextへの採用には対象会社での明示確認が必要である。

## Existing architecture

既存の `JournalLine.department`、`MappingType.DEPARTMENT`、`MappingRequirementExtractor`、`ConversionProfile.department_mappings`、`JdlDepartmentIdentity`、`JdlTargetContext.departments` を再利用できる。Context validationとJDL output preflightは部門処理有効、exact code/name、確認済みoutput identityを検査するため、parallel modelは不要である。

会社設定GUIは現在、部門要件を未解決として保持できるが、部門PDFを取り込んで確認する製品UIは未実装である。将来はJSON pathを見せず、科目一覧PDF、補助、部門、税処理の取得状態をapplication serviceから表示する。PDF由来draftは部門code/name/略名称を保持するが、output representation未確認としてproduction利用をBLOCKする。

## Money Forward impact

private実業務仕訳帳で解析できた範囲では、部門が設定されたlineおよびlogical journalは観測されなかった。このEvidenceだけで「実務で部門を使わない」と一般化はしないが、現在のMVPでは部門master取得を最優先blockerとはしない。

## Next human evidence

同じsynthetic test companyへ完全架空の2件目の部門を追加し、再度「部門登録 -> 印刷」を実行する。目的は1部門1行、複数行の境界、code/name/略名称の重複検査、および登録済み部門が一覧へ追加されることの再現確認である。配賦・集計設定はまだ変更せず、変更変数を部門件数だけに限定する。
