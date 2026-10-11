# JDL Department Master Sources

## Current conclusion

JDL IBEX 出納帳35.5の部門について、追跡可能なEvidenceから確認できるのは、30列仕訳CSVに現れた使用済みcode/nameと、限定的なUI/runtime実験だけである。全件を取得できる正式exportまたは部門一覧PDFは未確認である。

| Source candidate | Current state | Completeness |
|---|---|---|
| 正式な部門master export | 未確認 | `UNKNOWN` |
| 部門一覧の印刷/PDF | 未確認 | `UNKNOWN` |
| JDL 30列仕訳CSV | code/nameを観測可能 | `OBSERVED_USED_MASTER` |
| 保存済みJDL Target Context | local contextは存在するが、監査対象contextに部門masterなし | context-specific only |
| JDL画面・限定Import実験 | 部門処理有効化と限定値のruntime挙動を観測 | UI/runtime evidence only |

30列仕訳CSVの観測値を全masterへ昇格しない。異なる会社・取得元を無条件にmergeせず、code/name conflictは明示的に保持する。観測部門はprovenance付きのread-only candidateとして扱い、正式Contextへの採用には対象会社での明示確認が必要である。

## Existing architecture

既存の `JournalLine.department`、`MappingType.DEPARTMENT`、`MappingRequirementExtractor`、`ConversionProfile.department_mappings`、`JdlDepartmentIdentity`、`JdlTargetContext.departments` を再利用できる。Context validationとJDL output preflightは部門処理有効、exact code/name、確認済みoutput identityを検査するため、parallel modelは不要である。

会社設定GUIは現在、部門要件を未解決として保持できるが、部門masterを取り込んで確認する製品UIは未実装である。将来はJSON pathを見せず、科目一覧PDF、補助、部門、税処理の取得状態をapplication serviceから表示する。

## Money Forward impact

private実業務仕訳帳で解析できた範囲では、部門が設定されたlineおよびlogical journalは観測されなかった。このEvidenceだけで「実務で部門を使わない」と一般化はしないが、現在のMVPでは部門master取得を最優先blockerとはしない。

## Next human evidence

JDL実機の既知の部門登録一覧画面を開き、画面内または関連HELPに「印刷」「一覧」「CSV出力」の導線があるかだけ確認する。取り込みや自動操作は行わない。導線があれば、完全架空テスト事業所で未使用部門を含められるかを確認してからEvidenceを取得する。導線がなければ、一覧画面全体とHELPの取得可能項目を記録し、正式exportが存在すると推測しない。
