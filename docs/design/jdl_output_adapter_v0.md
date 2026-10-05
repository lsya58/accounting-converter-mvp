# Evidence-limited JDLOutputAdapter v0

## Status

`JDLOutputAdapter`と`JDLOutputValidator`は正式`src`配下に実装済み。ConversionService、YayoiInputAdapter起点に加え、`EVID-JDL-CONTEXT-AWARE-RUNTIME-E2E-001`でRegistryとcontext-aware factoryを通るartifactもJDL実機Import、UI確認、self re-export比較まで完了した。実装はRegistry登録済みだがproduction無効で、YayoiからJDLへのreadinessは`ADAPTER_UNAVAILABLE`のままとする。

Target identityはJDL IBEX出納帳35.5 / Journal CSV Input / official documented 30-column schema。schema自体のEvidence levelは`OFFICIAL_DOCUMENTED`から変更しない。adapter behaviorだけを個別の`VERIFIED_BY_REAL_IMPORT` Evidenceへ結び付ける。

## Supported Profiles

| Profile | Evidence | Scope |
| --- | --- | --- |
| `SUPPORTED_1111_BASIC` | `EVID-JDL-GENERATOR-1111-001` | 免税、借貸各1行、補助/部門/税なし |
| `SUPPORTED_1000_BASIC` | `EVID-JDL-GENERATOR-1000-001` | 免税、非伝票、借貸各1行 |
| `SUPPORTED_1000_SUBACCOUNT` | `EVID-JDL-GENERATOR-1000-SUBACCOUNT-001` | 貸方補助1件、親科目contextと出力表現を明示確認 |
| `SUPPORTED_1111_DEPARTMENT` | `EVID-JDL-GENERATOR-1111-DEPARTMENT-001` | 借貸両側へ同じ確認済み部門を明示 |
| `SUPPORTED_1111_TAX_INCLUDED` | `EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001` | 原則課税・個別対応・税込、借方`仕　入`/`10%` |
| `SUPPORTED_1111_TAX_EXCLUDED` | `EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001` | 原則課税・個別対応・税抜、借方`仕　入`/`10%`/`内税`/明示税額。税額は検証済み10%内税・端数切捨てpatternと一致する場合だけ許可 |
| `SUPPORTED_COMPOUND_1D3C` | `EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001` | 免税、1借方対3貸方、exact 3-record sequence |

file-level multi-groupは、同日の`SUPPORTED_1111_BASIC + SUPPORTED_COMPOUND_1D3C`を`EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001`で、同日の`SUPPORTED_1111_BASIC + SUPPORTED_1111_BASIC`を`EVID-JDL-SIMPLE-PLUS-SIMPLE-RUNTIME-001`で許可する。いずれもexact 2-journal combinationに限定し、profileは仕訳metadataへ明示して特徴から推測しない。3 journals以上、compound+compound、異なる日付、他profileの組合せは引き続きblockする。

同日12 journals（simple 7 / exact 1D3C compound 5）、22 physical recordsの固定profile順は、`EVID-JDL-MIXED-BATCH-RUNTIME-001`で実機検証済みのstrict allow-listとする。4種類のgroup boundaryを保持したexact sequenceだけを許可し、順序・件数・日付の差異、任意batch、未対応featureの混入はblockする。

## Preflight

- exact product/version/format profile
- accountの確認済みtarget master完全一致
- subaccountのparent account context、target code、output representation確認
- department code/nameのtarget master完全一致
- fuzzy matching、自動置換、暗黙defaultなし
- Evidence profileごとのfeature combination完全一致
- 貸借一致、整数円、field長、日付、CP932 round-trip
- compound shape、順序、同一日付、group balance
- multiple groupのexact allow-list

1件でもErrorがあれば`ConversionService`は`BLOCKED_BY_OUTPUT_PREFLIGHT`を返し、一時出力前に停止する。

## Serialization And Validation

30列順序のsource of truthは`jdl_ibex_cashbook_official_journal_import_spec()`を使用する。出力はCP932、BOMなし、CRLF、preambleなし、first physical row exact header。伝番、未使用tax amount、未使用department code等にre-export由来の`0`を挿入しない。

`JDLOutputValidator`はCP932 byte round-trip、BOM、改行、header、30列、parse-back、Evidence planとのexact row一致、record/journal count、借貸合計を検証する。Verification ReportにはEvidence ID、schema identity、unsupported profile countを追加し、会計本文を含めない。

## Must Block

unknown product/version、未知Evidence profile、未確認master、1000+tax/department、department+tax、8%/売上側/未知tax literal、取引科目、compound内tax/subaccount/department、2借方対1貸方、many-to-many、2-record compound、複数compound、検証済みexact pair以外のmulti-group、3 groups以上、nonblank伝番、CP932変換不能、truncate/normalize/inferred valueをblockする。

## Release Gate Result

正式ConversionServiceで生成した同日simple+compound artifactは、JDL IBEX出納帳35.5で4 records / exactly 2 vouchersとしてImport成功した。candidate/re-exportの120 fieldsは88 preserved、32 blank-to-nonblankで、semantic differenceは0だった。

Adapter behavior、strict scopeのYayoiInputAdapter起点E2E、context-aware instantiation path、同日`1111 + 1111`のexact pairに加え、12 journals / 22 recordsの固定mixed batchもruntime gateを通過した。一般ユーザー向けContext確認UI、production enable設計、Windows package E2Eが未完了のためregistryは`UNAVAILABLE`、YayoiからJDLはNOT READYを維持する。

初回release前の優先度は、GUIでのProfile/Context確認、production有効化設計、Windows package E2Eを`MUST BEFORE FIRST RELEASE`とする。subaccount付きYayoi -> JDLは`SHOULD SOON AFTER`、tax/department付き経路と任意batch拡張は`OPTIONAL / POST-MVP`とする。

## Yayoi Input Software E2E

Yayoi AE19 observed 25-field synthetic CSVを正式`YayoiInputAdapter`で読み、Common Journal Model、確認済みMapping、Business Validation、JDL output preflight、temporary output、output validation、Verification Report、atomic publishまで通すsoftware E2Eを実装した。

- input: CP932、BOMなし、CRLF、headerなし、4 physical records
- grouping: `2111` 1件と`2110 -> 2100 -> 2101` 1件、合計2 logical journals
- route: journal IDごとの明示割当のみ。feature inferenceなし
- output: `1111, 1110, 1100, 1101`、4 records / 2 journals
- safety: unknown mappingまたはroute未割当は正式出力前にblock

生成artifactはJDL IBEX出納帳35.5で4 records / exactly 2 vouchersとしてImportされ、UIとself re-exportでsemantic preservationを確認した。candidate/re-exportの120 fieldsは88 preserved、32 blank-to-nonblank、semantic difference 0だった。これによりstrict allow-list内のcore conversion engineはruntime validatedとする。

一方、tax/subaccount/department、任意compound、任意batch、別製品/versionは未検証である。`AdapterRegistry`はcontext-aware実装を保持するがproduction無効、YayoiからJDLの一般利用readinessはNOT READYを維持する。candidate伝番blank、UI blank、re-export `0`は別Evidenceとして保持し、`0`を生成defaultにしない。

## Runtime Target Context

- `ConversionProfile`: source -> target Mapping decision、確認状態、変換rule
- `JdlTargetContext`: 今回のJDL target identity、確認済みmaster、会社・税設定snapshot
- `JdlTargetContextBuilder`: duplicate、親子関係、文字/桁、会社設定をstrict validation
- `JdlOutputRuntimeFactory`: Profileのtarget code/正式名称とContextをexact cross-check
- `ConversionRequest`: Profileとrun-scoped Contextを明示注入

context欠落・不整合は`BLOCKED_BY_TARGET_CONTEXT`で停止する。global customer default、module-level mutable state、前回context再利用、fuzzy補完は行わない。Verification Reportへは製品/version、検証状態、master件数、税分類、Mapping整合結果だけを記録する。
