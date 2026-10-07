# Private CSV Batch Audit

## Purpose

実業務CSVをproduction変換へ投入する前に、既存Input Adapterとの適合率と安全な停止理由をdirectory単位で確認するdevelopment utilityである。CSV変換、mapping、JDL出力、GUI処理は行わない。

## Usage

repository rootで実行する。

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.audit_private_csv data/private/research/
```

privacy-safe JSONも必要な場合は、Git管理外の保存先を明示する。既存reportは上書きしない。

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.audit_private_csv \
  data/private/research/ \
  --json-report data/private/audit/audit_report.json
```

defaultではfile nameとrelative pathをreportへ含めない。調査上必要で、path自体に顧客情報が含まれないとHumanが確認した場合だけ`--include-relative-paths`を使用する。

## Status

- `PASS`: exact observed identityに一致し、既存Input Adapterによるparseとcountが成功した。
- `BLOCK`: 既知format候補だが、既存Adapterの安全条件により拒否された。
- `UNKNOWN`: 既存identityに一致しない。別formatとは推測しない。
- `ERROR`: file readやAdapter外例外などaudit execution自体のtechnical failure。

`UNKNOWN`のrowをjournalとして数えない。File pass rateは全CSVに対するPASS率、Recognized-file pass rateは`PASS / (PASS + BLOCK)`である。

## Privacy Rules

- raw row、科目、摘要、会社、取引先、金額、日付をreport modelへ渡さない。
- exception messageはreportへ出さず、固定reason codeへ分類する。
- raw CSVを変更、上書き、copyしない。
- network access、外部API、AI inferenceを使用しない。
- reportには匿名file ID、hash、size、構造件数、format metadataだけを含める。
- `data/private/`と生成reportをGit管理しない。

Format detectionはMoney Forwardのexact observed 19-column headerと、Yayoi AE19で観測済みのidentifier flagsに限定する。認識後のparseはaudit専用parserではなく既存`MoneyForwardInputAdapter`または`YayoiInputAdapter`を使用する。
