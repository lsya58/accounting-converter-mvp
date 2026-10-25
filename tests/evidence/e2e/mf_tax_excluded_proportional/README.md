# MF→JDL 税抜・一括比例配分方式 round-trip Evidence

- Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT`
- JDL: IBEX 出納帳 35.5
- Context: 課税 / 税抜 / 原則課税 / 一括比例配分方式
- Human Import: PASS
- Strict semantic comparison: PASS
- Journals: 7
- Physical rows: 8
- Unexpected changes: 0

P01～P07はshape、relevant account/subaccount、取引先摘要との共存を分離した独立scopeである。税込、個別対応方式、別税区分、別account/subaccount、別shapeには一般化しない。

raw candidateとJDL re-exportはprivateに保持し、このEvidence folderには保存しない。JDLによる伝番・blank数値field、master略称、補助コード先頭zeroの正規化はraw差分として保持し、exact scope内だけsemantic normalizationとして扱う。
