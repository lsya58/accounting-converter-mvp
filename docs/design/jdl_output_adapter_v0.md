# Evidence-limited JDLOutputAdapter v0

## Status

`JDLOutputAdapter`と`JDLOutputValidator`は正式`src`配下に実装済み。ConversionService、YayoiInputAdapter、Registry、context-aware factory、Windows packaged GUIを通るstrict scopeのartifactはJDL実機Import、UI確認、self re-export比較まで完了した。JDL IBEX出納帳35.5のexact identityに限りRegistryをproduction有効とし、Context、Mapping、Evidence allow-listのどれかを満たさない入力は停止する。

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

Adapter behavior、strict scopeのYayoiInputAdapter起点E2E、context-aware instantiation path、同日`1111 + 1111`のexact pair、固定mixed batchに加え、Windows packaged GUI経路もruntime gateを通過した。scroll/resizeと未対応versionを実行前に停止するnegative pathもWindows実機で確認したため、strict scopeのRegistryは`AVAILABLE`、First Release経路はREADYとする。

subaccount/tax/department付きYayoi -> JDL、任意batch拡張、他JDL versionはFirst Release対象外であり、追加Evidenceを得るまでblockする。

## Yayoi Input Software E2E

Yayoi AE19 observed 25-field synthetic CSVを正式`YayoiInputAdapter`で読み、Common Journal Model、確認済みMapping、Business Validation、JDL output preflight、temporary output、output validation、Verification Report、atomic publishまで通すsoftware E2Eを実装した。

- input: CP932、BOMなし、CRLF、headerなし、4 physical records
- grouping: `2111` 1件と`2110 -> 2100 -> 2101` 1件、合計2 logical journals
- route: journal IDごとの明示割当のみ。feature inferenceなし
- output: `1111, 1110, 1100, 1101`、4 records / 2 journals
- safety: unknown mappingまたはroute未割当は正式出力前にblock

生成artifactはJDL IBEX出納帳35.5で4 records / exactly 2 vouchersとしてImportされ、UIとself re-exportでsemantic preservationを確認した。candidate/re-exportの120 fieldsは88 preserved、32 blank-to-nonblank、semantic difference 0だった。これによりstrict allow-list内のcore conversion engineはruntime validatedとする。

一方、tax/subaccount/department、任意compound、任意batch、別製品/versionはFirst Release対象外である。RegistryがAVAILABLEでもpreflight allow-list外としてblockする。candidate伝番blank、UI blank、re-export `0`は別Evidenceとして保持し、`0`を生成defaultにしない。

## Runtime Target Context

- `ConversionProfile`: source -> target Mapping decision、確認状態、変換rule
- `JdlTargetContext`: 今回のJDL target identity、確認済みmaster、会社・税設定snapshot
- `JdlTargetContextBuilder`: duplicate、親子関係、文字/桁、会社設定をstrict validation
- `JdlOutputRuntimeFactory`: Profileのtarget code/正式名称とContextをexact cross-check
- `ConversionRequest`: Profileとrun-scoped Contextを明示注入

context欠落・不整合は`BLOCKED_BY_TARGET_CONTEXT`で停止する。global customer default、module-level mutable state、前回context再利用、fuzzy補完は行わない。Verification Reportへは製品/version、検証状態、master件数、税分類、Mapping整合結果だけを記録する。

## First Release GUI release candidate

GUIは入力CSV、ConversionProfile、確認済みJDL設定JSON、出力先を明示選択し、Applicationの`FirstReleaseConversionWorkflow`を呼ぶ。workflowはYayoi AE19 observed subsetをstrict parseし、confirmed exact Mapping、JDL IBEX出納帳35.5、免税、補助なし、部門なし、税情報なし、検証済み1借方1貸方またはexact 1借方3貸方構成だけをroute assignmentへ変換する。複数groupはOutput preflightの検証済み順序・件数制約をそのまま適用する。

実行前にはsource/profile/target/context/mapping/feature/output/no-overwriteをprivacy-safeに表示する。最終確認後だけ`ConversionService`を実行し、成功時は件数、貸借合計、出力検証、Evidence profileを含む既存Verification Reportを表示する。出力済みpath、sourceとの衝突、未確認Mapping、unsupported featureは正式ファイルを生成せず停止する。

`EVID-JDL-WINDOWS-GUI-E2E-001`により、Windows packaged appでProfile、Context、input、outputを明示選択し、この導線から生成した同日simple 2件がJDL実機へImportされ、UI確認とself re-export比較（60 fields、semantic difference 0）まで完了した。candidate伝番blank、runtime UI blank、re-export `0`は分離し、runtime追加値をgeneration defaultへ昇格しない。

Windows packaged appでは、縦scroll、mouse wheel、resize後の結果欄到達を確認した。未対応target version `99.9`はpreflightでBLOCKされ、作成buttonが無効のまま変換・出力されないことも確認した。この最終acceptanceを根拠に、strict scopeだけproduction Registryを有効化する。

## Operator Acceptance Checklist

変換前:

- Sourceが弥生AE19の直接Exportであること
- 正しいConversionProfileとJDL Target Contextを明示選択したこと
- targetがJDL IBEX出納帳35.5、会社設定が免税であること
- Mapping unresolvedが0、出力先が新規、実行前判定がREADYであること

変換後:

- 結果がSUCCESSで、logical journal数とphysical record数が想定どおりであること
- 借方/貸方合計が一致し、unresolvedが0、Output Validationが成功していること
- JDL Import前に出納帳ファイルを退避し、Import時にJDL側の認識件数を確認すること
