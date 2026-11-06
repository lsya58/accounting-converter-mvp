# 会社A Evidenceキャンペーン 第2回（グループB：合成JDL target probe）

Human が 2026-11-05 に、会社A の JDL IBEX 出納帳35.5 を元の会社データから復元した検証用環境で実施。
仕訳日付は元データに取引のない1日（第1回とは別の日）。顧客の値はこの文書に書かない。
生ファイルと詳細結果は `data/private/yayoi_buddies/evidence_campaign_20261105/`（`SESSION2_RESULT_20260627.json`）。

**これは弥生source→正式出力のEvidenceではない。** production Evidence registry・READY判定は変更していない。

## 使った表現

第1回の手入力見本の再Exportで観測した表現だけを使った（[第1回の記録](../yayoi_buddies_campaign_session1/README.md)）。

| 表現 | JDL（課区／税区／税入力方法） | 明示税額 |
|---|---|---|
| 輸出売上 | 輸出売／なし／なし（貸方） | なし |
| 軽減8%仕入 | 仕　入／軽減8%／内税（借方） | 1,080円→80 |
| 80%経過措置の仕入 | 仕　入／10%免80／内税（借方） | 1,100円→80（10%全額の80%） |

控除不可（10%・8%）と決算仕訳は表現が未確認のため含めていない（PASSとして扱わない）。

## 結果（ケース別 strict）

| ケース | 構造 | 判定 |
|---|---|---|
| BI-EXPORT | 1D1C | PASS |
| BI-EXPORT-2D2C | 2D2C/2行（1行目 貸方 輸出売、2行目 対象外同士） | PASS |
| BI-RED8 | 1D1C | PASS |
| BI-RED8-2D1C | 2D1C/2行（課税仕入10%＋軽減8%） | PASS |
| BI-TRANS80 | 1D1C | PASS |
| BI-TRANS80-1D2C | 1D2C/2行（10%免80＋対象外2行） | PASS |

- 6/6仕訳・9/9行。重複0、説明できない仕訳0、手入力なし。並び順込みの全体厳密比較も PASS。
- 差分は既知の正規化40セルのみ（伝番 空欄→0 9、貸方消費税 空欄→0 9、借方消費税 空欄→0 4、借方・貸方部門コード 空欄→0 各9）。
- 税区分・税率・明示税額・金額・科目・行順・摘要の識別子は変化なし。

## ファイル（SHA-256）

| ファイル | SHA-256 |
|---|---|
| B candidate | `d0e7a38a0d8d515d63425717814d7a45ad1dcdd12d6d083bc45ee402f357aa99` |
| 第2回 再Export（1日分） | `360566efd4150dfb7c7b44fdfe66ee04afe0288162c6f6ea3a50fa5154215f02` |

Pending ID は manifest の `pending_evidence_id`（`PENDING:EVID-YAYOI-JDL-35-5-COMPANY-YAYOI-BUDDIES-BI-…-SYNTHETIC-ROUNDTRIP-001`）。
