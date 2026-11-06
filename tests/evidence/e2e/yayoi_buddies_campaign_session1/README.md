# 会社A Evidenceキャンペーン 第1回（合成JDL target probe）

Human が 2026-11-05 に、会社A（弥生 仕訳日記帳 汎用形式）の JDL IBEX 出納帳35.5 **検証用複製**で実施。
仕訳日付は元データに取引のない1日。計画は [キャンペーン計画](../../../../docs/development/yayoi_buddies_evidence_campaign.md)。
顧客の値はこの文書に書かない。生ファイルと詳細結果は `data/private/yayoi_buddies/evidence_campaign_20261105/`（`SESSION1_RESULT_20260628.json`）。

**これは弥生source→正式出力のEvidenceではない。** production Evidence registry・READY判定は変更していない。

## 結果

| ファイル | 取込 | 厳密比較（ケース別） |
|---|---|---|
| A1（48仕訳・278行、最長15行） | 成功 | **48/48 PASS** |
| A2（9仕訳・10行、税の付く側が逆） | 成功 | **9/9 PASS** |
| A3（16行1仕訳） | 成功 | **1/1 PASS** |
| A4（17・25・50・73行の4仕訳、165行） | **全行拒否**「伝票内の仕訳数が多すぎます」 | 0/4（JDLに登録なし） |

- 判定: `tools/yayoi_campaign_session.py check`。1ケースにつき再Exportのちょうど1仕訳が既存の厳密比較で一致した場合だけ PASS。重複0、2ケースに一致した仕訳0。
- 説明できない仕訳1件は、摘要なしで手入力された見本（80%経過措置）。内容で一意に特定した。
- A1単独の再Exportでも 48/48 PASS、重複0、説明できない仕訳0。
- A4のJDLエラーログは投入ファイルと165行すべて一致し、全行に同じメッセージ。再Exportに A4 の仕訳は無い。

## 振替伝票の行数上限（会社設定付き）

`EVID-YAYOI-JDL-35-5-BUDDIES-VOUCHER-ROW-LIMIT-16-001`

- 会社設定: 振替伝票入力行数「16行以内」（Human確認）。
- 16行の伝票は CSV 取込でき、再Export厳密一致。17行以上（17・25・50・73行）は CSV 取込で拒否。
- **範囲**: 会社Aの検証用複製、この行数設定、JDL IBEX 出納帳35.5。他の会社・他の行数設定・他の製品へは一般化しない。
- 会社Aの元データで16行を超える30仕訳は、この設定のままでは1伝票として取り込めない。自動分割・会社設定の変更はしない。

## 明示税額（会社Aの端数設定：売上 切上げ／仕入 四捨五入）

CSV取込では、切上げ値・切捨て値・四捨五入値のいずれの明示税額も JDL が書き換えず、そのまま再Exportされた
（EXP-S-CEIL-6121/6131/6181、EXP-S-FLOOR-6121、EXP-P-HALFUP、EXP-DS-FLOOR が PASS）。
画面での手入力では、JDL が会社の端数設定で税額を計算した（観測のみ）。

## 手入力見本（グループB）

| 見本 | 分類 | 再Exportで確認できた表現 |
|---|---|---|
| 輸出売上 | 入力成功 | 貸方 課区「輸出売」、税区・税入力方法なし、消費税 0 |
| 軽減8%仕入 | 入力成功 | 借方「仕　入／軽減8%／内税」、明示税額あり |
| 80%経過措置 | 入力成功（摘要の印なし、内容で特定） | 借方「仕　入／10%免80／内税」、税額は10%全額の80% |
| 控除不可10% | **保留** | 控除不可の指定方法が確認できず、通常の10%仕入として入力された。表現は未確認 |
| 控除不可8% | **保留** | 同上（通常の軽減8%仕入） |
| 決算仕訳 | **保留** | 決算区分の入力方法が確認できず、通常の仕訳として入力された。表現は未確認 |

自己Exportは表現の観測であり、Evidenceではない。輸出売上・軽減8%・80%経過措置は第2回の取込往復で判定する。
保留の3項目は推測で生成しない。

## Pending Evidence ID

A1〜A3 の58ケースは各 manifest の `pending_evidence_id`（`PENDING:EVID-YAYOI-JDL-35-5-COMPANY-YAYOI-BUDDIES-<CASE>-SYNTHETIC-ROUNDTRIP-001`）で PASS を記録した。登録（activation）は後の明示的なコード変更で行う。

## ファイル（SHA-256）

| ファイル | SHA-256 |
|---|---|
| A1 candidate | `b850d2fd5f722acc2aa6833eb1b3c51e8187287b0932dcdb75766305af016caa` |
| A2 candidate | `aa4a43aae6a4da4f6d9751db63b384a720bf6f7e5483b6199c1d8dfec2f3f52e` |
| A3 candidate | `80e40206c7dea922df78342a5d4910c5826e9a88b54685de132fcb2290712508` |
| A4 candidate | `d4af2e55de1a7e94b407863bed8c255404c867ab4c8dc1fa9d70650602c8f9a9` |
| 第1回 再Export（1日分） | `cbcba219d7206e68bd086f6dc2e3b73fa1884ca7cae025f1b318c36f2cb281ee` |
| A1単独 再Export | `6f80de952527a64a26a419a7a76d04db0f2aab1f3bbf9e7223a7c3054895821a` |
| A4 JDLエラーログ | `a55ea0e1113548d68cd4fb331da79a171802508aa1ebc86f11d8b50ce0b81f90` |
