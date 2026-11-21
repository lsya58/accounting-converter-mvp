"""freee 試験診断（データ取込ページ）の表示内容 (E5A). Pure data: no Qt, no decision of its own.

Everything comes from application.freee_diagnosis (read-only, DIAGNOSE_ONLY). Rules:
- freee is 試験対応・診断のみ. Parsing a journal is never a formal READY: "JDL向け正式READY" is the diagnosis's own
  formal_ready (0 while the direction is not PRODUCTION), shown next to, never merged with, the parsed count;
- the READY-only output for freee is never enabled here (`output_enabled` is False by construction);
- nothing from the customer is shown: no account, partner, description, amount, freee ID or 作成者. Rows are located
  by the file-local display number and the line number in the file; column names and freee tax category names are
  product vocabulary and are shown;
- a code without a label is shown as the code itself (never hidden).
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from accounting_converter.adapters.input.freee.journal_csv import FreeeJournalVariant, classify_header, decode
from accounting_converter.application.freee_diagnosis import FreeeDiagnosis, tax_hint
from accounting_converter.domain.information_retention import RETENTION_ORDER, RetentionStatus
from accounting_converter.ui.home_view import Metric

TRIAL_BADGE = "試験対応・診断のみ"
SCOPE_LINES = (
    "弥生会計・Money Forward: 正式対応（保存済みの会社設定とJDL実機Evidenceの範囲で、正式READYの仕訳だけを出力できます）",
    "freee会計: 試験対応・診断のみ（仕訳を読み取って診断します。JDL用CSVの作成・READYのみ出力はできません）",
)
TRIAL_NOTE = (
    "freeeの仕訳帳CSV（新CSV・旧CSV）を読み取り、どこまで解析できるかを表示します。"
    "会社設定・承認は変更せず、元のファイルも変更しません。"
)
PARSED_IS_NOT_READY = (
    "「正常に解析できた仕訳」は、CSVを読み取れたという意味です。JDL向けの正式READYではありません。"
    "freeeからJDLへの正式な変換は、freee側の追加Evidenceと JDL実機での確認が揃うまで行いません（正式READYは0のまま）。"
)
RETENTION_NOTE = (
    "この表は、値のある列の名前と件数の集計です。列ごとの扱い（区分）を示すもので、"
    "値がJDLに残る・出力できることを示すものではありません。"
    "旧CSVの決算整理仕訳の「0」（通常仕訳）と、空欄の片側の「0／対象外」は、値ではなく印の有無・空欄の形として扱います。"
)
OUTPUT_DISABLED_REASON = (
    "freeeは試験対応のため、READYのみ出力・JDL用CSVの作成はできません。"
    "診断結果の確認だけができます。"
)

VARIANT_LABELS = {
    FreeeJournalVariant.NEW_CSV: "freee 新CSV（仕訳帳・観測97列）",
    FreeeJournalVariant.OLD_CSV: "freee 旧CSV（仕訳帳・観測29列）",
    FreeeJournalVariant.UNKNOWN: "判定できない形式",
}
ENCODING_LABELS = {"utf-8": "UTF-8（BOMなし）", "utf-8-sig": "UTF-8（BOMあり）", "cp932": "Shift-JIS（CP932）"}

OWNER_LABELS = {
    "HUMAN": "人の判断が必要",
    "SYSTEM_EVIDENCE": "確認資料（Evidence）が不足",
    "SYSTEM_IMPLEMENTATION": "変換方向が試験段階",
}
OWNER_ORDER = ("SYSTEM_IMPLEMENTATION", "SYSTEM_EVIDENCE", "HUMAN")

REASON_LABELS = {
    # direction / format
    "SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION": "freee→JDLは診断のみの段階です（正式な変換は未対応）",
    "SYSTEM_EVIDENCE:FREEE_SOURCE_FORMAT_UNVERIFIED": "freeeのCSV形式は観測1サンプルのみで、列の意味が検証済みではありません",
    "SYSTEM_EVIDENCE:FREEE_HEADER_NOT_OBSERVED": "列の構成が観測済みのfreee出力と異なります（列の増減）",
    "SYSTEM_EVIDENCE:FREEE_VARIANT_UNKNOWN": "新CSV・旧CSVのどちらとも判定できません",
    "SYSTEM_EVIDENCE:FREEE_DESCRIPTION_SOURCE_UNKNOWN": "摘要（備考）の列が見つからず、摘要の元が分かりません",
    "SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED": "観測していない値があります（部門・セグメント・未観測の税区分など）",
    "SYSTEM_EVIDENCE:FREEE_JOURNAL_SHAPE_UNOBSERVED": "観測していない仕訳の形です（借方複数・3行以上など）",
    "SYSTEM_EVIDENCE:FREEE_ROW_DESCRIPTION_INCONSISTENT": "同じ行の借方備考と貸方備考が異なります（統合しません）",
    "SYSTEM_EVIDENCE:UNKNOWN_SOURCE_COLUMN": "意味の分からない列に値があります（値は保持しています）",
    "SYSTEM_EVIDENCE:FREEE_CLOSING_MARKER_UNVERIFIED": "決算整理仕訳のJDLでの表し方が未確認です",
    # tax
    "HUMAN:TAX_MAPPING": "freeeの税区分をJDLの課税区分・税区分へ対応付ける判断が必要です",
    "SYSTEM_EVIDENCE:FREEE_TAX_CATEGORY_UNRECOGNISED": "名前から種類の分からない税区分です",
    "SYSTEM_EVIDENCE:FREEE_TAX_INCLUSION_MAPPING_UNVERIFIED": "内税・外税とJDLの税入力方法の対応が未確認です",
    "SYSTEM_EVIDENCE:FREEE_TAX_INCLUSION_UNKNOWN": "内税・外税が分かりません（旧CSVには列がありません）",
    "SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT": "課税の明細に税額がありません（推測・計算しません）",
    "SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ON_UNTAXED_CATEGORY": "課税でない税区分に税額があります",
    "SYSTEM_EVIDENCE:FREEE_TAX_RATE_INCONSISTENT": "税率列と税区分名の税率が一致しません",
    "SYSTEM_EVIDENCE:FREEE_TAX_ACCOUNTING_METHOD_UNMAPPED": "freeeの消費税経理処理方法とJDL会社の設定の対応が未確認です",
    "HUMAN:FREEE_TAX_ACCOUNTING_METHOD_UNKNOWN": "税込経理・税抜経理が分かりません（旧CSVには列がありません）",
    # mapping / information
    "HUMAN:ACCOUNT_MAPPING": "freeeの勘定科目をJDLの科目へ対応付ける判断が必要です",
    "HUMAN:ACCOUNT_DISPLAY_NAME_DIFFERS": "勘定科目と決算書表示名が異なります（置き換えません）",
    "HUMAN:DEPARTMENT_MAPPING": "部門の対応付けが必要です",
    "HUMAN:COUNTERPARTY_POLICY": "取引先をJDLでどう扱うかの判断が必要です",
    "HUMAN:NON_RETAINED_INFORMATION": "JDLに保持先のない情報（品目・メモなど）があります",
    "HUMAN:NEGATIVE_AMOUNT": "負の金額があります",
    "SYSTEM_EVIDENCE:FREEE_ZERO_AMOUNT_LINE_UNOBSERVED": "0円の明細があります（未観測）",
}

ISSUE_LABELS = {
    "UNREADABLE": "ファイルを読み取れませんでした",
    "ENCODING_UNKNOWN": "文字コードを判定できません（UTF-8・Shift-JIS以外）",
    "MALFORMED_CSV": "CSVとして正しく区切られていません",
    "NO_DATA_ROWS": "仕訳の行がありません",
    "VARIANT_UNKNOWN": "freee仕訳帳CSV（新CSV・旧CSV）のヘッダーと判定できません",
    "REQUIRED_COLUMN_MISSING": "必要な列がありません",
    "DUPLICATE_COLUMN": "同じ名前の列が複数あります",
    "COLUMN_COUNT_MISMATCH": "ヘッダーと列数の違う行があります",
    "JOURNAL_NUMBER_MISSING": "仕訳を識別する番号がありません",
    "JOURNAL_NUMBER_REUSED": "同じ仕訳番号が離れた位置に再び出てきます",
    "JOURNAL_ID_INCONSISTENT": "同じ仕訳の行で仕訳番号などが一致しません",
    "LINE_NUMBERING_INCONSISTENT": "仕訳行番号・仕訳行数が一致しません",
    "DATE_FORMAT_UNVERIFIED": "取引日の形式が観測済みの形式と異なるか、日付として正しくありません",
    "MULTIPLE_DATES": "同じ仕訳の行で取引日が異なります",
    "AMOUNT_FORMAT_UNVERIFIED": "金額・税額が整数として読めません",
    "SIDE_WITHOUT_ACCOUNT_OR_AMOUNT": "勘定科目か金額のない片側があります（観測済みの空欄の形と異なります）",
    "EMPTY_ROW": "借方・貸方とも空の行があります",
    "CLOSING_MIXED": "同じ仕訳の行で決算整理仕訳の値が異なります",
    "TAX_ACCOUNTING_METHOD_MIXED": "同じ仕訳の行で消費税経理処理方法が異なります",
    "UNBALANCED": "借方合計と貸方合計が一致しません",
}

RETENTION_LABELS = {
    RetentionStatus.RETAINED: "保持できる情報",
    RetentionStatus.TARGET_DESTINATION_UNCONFIRMED: "JDL側の保持先が未確認の情報",
    RetentionStatus.MEANING_UNCONFIRMED: "意味が確定できない情報",
    RetentionStatus.UNSUPPORTED: "未対応の情報（JDLに保持先なし）",
    RetentionStatus.AUDIT_ONLY: "元データの参照用（出力しない）",
}
RETENTION_REASON_LABELS = {
    "COMMON_MODEL_DATE": "日付として保持",
    "COMMON_MODEL_ACCOUNT": "勘定科目として保持（JDL科目への対応付けは別に必要）",
    "COMMON_MODEL_AMOUNT": "金額として保持",
    "COMMON_MODEL_TAX_AMOUNT": "税額として保持（空欄と0円を区別）",
    "COMMON_MODEL_TAX_RATE": "税率として保持",
    "COMMON_MODEL_TAX_REDUCED": "軽減税率の有無として保持",
    "COMMON_MODEL_DESCRIPTION": "摘要として保持",
    "COMMON_MODEL_DESCRIPTION_COMPOSED_BY_FREEE": "摘要として保持（freeeが取引先・品目・メモ・備考を連結した文字列）",
    "TAX_CATEGORY_JDL_MAPPING_UNCONFIRMED": "税区分名として保持。JDLの課税区分・税区分への対応は未確認",
    "CLOSING_MARKER_JDL_UNVERIFIED": "値「1」を決算整理の印として保持（「0」は印なし）。JDLでの表し方は未確認",
    "DEPARTMENT_JDL_MAPPING_UNCONFIRMED": "部門として保持。JDL部門への対応は未確認",
    "COUNTERPARTY_JDL_POLICY_UNCONFIRMED": "取引先として保持。JDLでの扱い（摘要に入れる等）は未決定",
    "NEEDS_HUMAN_TRANSFORMATION": "取引先として保持。JDLでの扱い（摘要に入れる等）は未決定",
    "TAX_INCLUSION_JDL_MAPPING_UNVERIFIED": "内税・外税の値をそのまま保持。JDLの税入力方法との関係は未確認",
    "TAX_ACCOUNTING_METHOD_UNMAPPED": "値をそのまま保持。JDL会社の経理方式との関係は未確認",
    "PERIOD_END_FLAG_NOT_INTERPRETED": "値をそのまま保持。意味は解釈しません",
    "UNKNOWN_SOURCE_COLUMN": "観測していない列。値はそのまま保持し、意味は解釈しません",
    "VALUE_UNOBSERVED": "観測していない値。値はそのまま保持し、意味は解釈しません",
    "ACCOUNT_DISPLAY_NAME_DIFFERS": "勘定科目と異なる表示名。勘定科目を置き換えません",
    "NO_JDL_COLUMN": "JDLの取込列がありません（非保持の情報として報告）",
    "MAPPING_AID": "科目などの対応付けの参考（出力しない）",
    "SOURCE_IDENTIFIER": "freee内部の識別子（出力しない）",
    "SYSTEM_METADATA": "freeeが付けた日時・状態（出力しない）",
    "PERSONAL_DATA": "作成者などの個人情報（表示・出力しない）",
    "DISPLAY_NUMBER_FILE_LOCAL": "ファイル内の表示用連番（再出力で変わる。識別に使わない）",
}


def reason_label(code: str) -> str:
    return REASON_LABELS.get(code) or ISSUE_LABELS.get(code) or RETENTION_REASON_LABELS.get(code) or code


def owner_of(code: str) -> str:
    return code.split(":", 1)[0] if ":" in code else "SYSTEM_EVIDENCE"


@dataclass(frozen=True)
class FreeeTrialView:
    file_name: str
    readable: bool
    headline: str
    metrics: tuple[Metric, ...]
    format_lines: tuple[str, ...]
    file_problems: tuple[str, ...] = ()
    rejected_rows: tuple[tuple[str, str, str], ...] = ()  # 表示No, 問題のある行, 理由
    reason_rows: tuple[tuple[str, str, str], ...] = ()  # 担当, 理由, 仕訳数
    tax_lines: tuple[str, ...] = ()
    tax_rows: tuple[tuple[str, str, str], ...] = ()  # 税区分, 明細数, 名前から見える種類（参考）
    retention_rows: tuple[tuple[str, str, str, str], ...] = ()  # 区分, 列名, 値のある仕訳数, 扱い
    retention_counts: tuple[tuple[str, int], ...] = ()
    journal_rows: tuple[tuple[str, str, str, str, str], ...] = ()  # 表示No, 行, 結果, 形・種類, 主な理由
    formal_ready: int = 0
    output_enabled: bool = False  # never True for freee (E5A)
    output_reason: str = OUTPUT_DISABLED_REASON
    notes: tuple[str, ...] = field(default=(PARSED_IS_NOT_READY,))

    def plain_text(self) -> str:
        """For 診断情報をコピー: the same content as the screen, no customer values."""
        lines = [f"freee 試験診断（{TRIAL_BADGE}）", f"ファイル: {self.file_name}", self.headline]
        lines += [f"{m.label}: {m.value}" + (f"（{m.hint}）" if m.hint else "") for m in self.metrics]
        lines += self.format_lines + self.file_problems
        if self.rejected_rows:
            lines.append("解析できなかった仕訳:")
            lines += [f"  No {no} / 行 {rows}: {why}" for no, rows, why in self.rejected_rows]
        if self.reason_rows:
            lines.append("正式な変換に必要なこと（理由別）:")
            lines += [f"  [{owner}] {why}: {count}" for owner, why, count in self.reason_rows]
        if self.tax_lines or self.tax_rows:
            lines.append("税の確認:")
            lines += [f"  {line}" for line in self.tax_lines]
            lines += [f"  {name}: {count}（{kind}）" for name, count, kind in self.tax_rows]
        if self.retention_rows:
            lines.append("情報の保持状況:")
            lines.append(f"  {RETENTION_NOTE}")
            lines += [f"  [{status}] {column}: {count} / {why}" for status, column, count, why in self.retention_rows]
        lines += self.notes
        lines.append(self.output_reason)
        return "\n".join(lines)


_TAX_KIND_LABELS = {
    "SALES_TAXABLE": "課税売上", "PURCHASE_TAXABLE": "課税仕入", "NON_TAXABLE_SALES": "非課税売上",
    "NON_TAXABLE_PURCHASE": "非課税仕入", "EXPORT_SALES": "輸出売上", "OUT_OF_SCOPE": "対象外",
    "UNKNOWN": "不明",
}


def _n(value: int) -> str:
    return f"{value:,}"


def _rows_text(rows: tuple[int, ...]) -> str:
    if not rows:
        return "—"
    return ", ".join(str(row) for row in rows) if len(rows) <= 4 else f"{rows[0]}〜{rows[-1]}（{len(rows)}行）"


def present(diagnosis: FreeeDiagnosis, file_name: str) -> FreeeTrialView:
    parse = diagnosis.parse
    header = parse.header
    variant = header.variant if header is not None else FreeeJournalVariant.UNKNOWN
    formal_ready = diagnosis.formal_ready
    format_value = VARIANT_LABELS[variant]
    format_hint = ""
    if header is not None and variant is not FreeeJournalVariant.UNKNOWN and not header.observed:
        format_hint = "観測済みのヘッダーと列の構成が異なります"
    ready_metric = Metric("JDL向け正式READY", _n(formal_ready), "freeeは試験対応のため0です", "block")
    if not diagnosis.parse.file_readable:
        problems = tuple(
            dict.fromkeys(
                ISSUE_LABELS.get(code, code) for code in diagnosis.file_issues
            )
        ) or ("ファイルを読み取れませんでした",)
        columns = [issue.column for issue in parse.issues if issue.column]
        if columns:
            problems += (f"対象の列: {', '.join(dict.fromkeys(c or '（列名なし）' for c in columns))}",)
        return FreeeTrialView(
            file_name=file_name, readable=False,
            headline="このファイルはfreee仕訳帳CSVとして読み込めませんでした。何も推測せず、読み込みを中止しました。",
            metrics=(
                Metric("CSV形式", format_value, format_hint, "block"),
                Metric("読み取った仕訳", "—", "ファイル全体を読み込んでいません"),
                Metric("正常に解析できた仕訳", "—"),
                Metric("未対応の仕訳", "—"),
                ready_metric,
            ),
            format_lines=_format_lines(diagnosis),
            file_problems=problems,
            formal_ready=formal_ready,
        )
    parsed, rejected, read = diagnosis.journals_parsed, diagnosis.journals_rejected, diagnosis.journals_read
    metrics = (
        Metric("CSV形式", format_value, format_hint, "pending" if format_hint else "neutral"),
        Metric("読み取った仕訳", f"{_n(read)}仕訳", f"{_n(parse.data_rows)}行"),
        Metric("正常に解析できた仕訳", f"{_n(parsed)}仕訳", f"{_n(parse.accepted_rows)}行", "ready" if parsed else "neutral"),
        Metric("未対応の仕訳", f"{_n(rejected)}仕訳", f"{_n(parse.rejected_rows)}行" if rejected else "",
               "block" if rejected else "neutral"),
        ready_metric,
    )
    rejected_rows = tuple(
        (journal.display_number or "—", _rows_text(journal.rows), "／".join(reason_label(c) for c in journal.reasons))
        for journal in diagnosis.journals if not journal.parsed
    )
    counter = Counter(code for journal in diagnosis.journals if journal.parsed for code in journal.reasons)
    reason_rows = tuple(
        (OWNER_LABELS.get(owner_of(code), owner_of(code)), reason_label(code), f"{_n(count)}仕訳")
        for code, count in sorted(
            counter.items(),
            key=lambda item: (OWNER_ORDER.index(owner_of(item[0])) if owner_of(item[0]) in OWNER_ORDER else 9,
                              item[0]),
        )
    )
    retention_rows = tuple(
        (RETENTION_LABELS[status], item.field or "（列名なし・先頭列）", f"{_n(item.journals)}仕訳",
         RETENTION_REASON_LABELS.get(item.reason, item.reason))
        for status, items in diagnosis.retention.by_status().items() for item in items
    )
    retention_counts = tuple(
        (RETENTION_LABELS[status], len(items)) for status, items in diagnosis.retention.by_status().items()
    )
    journal_rows = tuple(
        (
            journal.display_number or "—",
            _rows_text(journal.rows),
            "解析済み（正式READYではありません）" if journal.parsed else "未対応（解析できません）",
            _shape_text(journal),
            _main_reason(journal),
        )
        for journal in diagnosis.journals
    )
    if rejected:
        headline = (f"{_n(read)}仕訳のうち{_n(parsed)}仕訳を解析できました。{_n(rejected)}仕訳は解析できませんでした"
                    "（理由を下に表示します）。JDL向け正式READYは0です。")
    else:
        headline = f"{_n(read)}仕訳すべてを解析できました。JDL向け正式READYは0です（解析できたことと正式READYは別です）。"
    return FreeeTrialView(
        file_name=file_name, readable=True, headline=headline, metrics=metrics,
        format_lines=_format_lines(diagnosis), rejected_rows=rejected_rows, reason_rows=reason_rows,
        tax_lines=_tax_lines(diagnosis), tax_rows=_tax_rows(diagnosis), retention_rows=retention_rows,
        retention_counts=retention_counts, journal_rows=journal_rows, formal_ready=formal_ready,
    )


def _format_lines(diagnosis: FreeeDiagnosis) -> tuple[str, ...]:
    header = diagnosis.parse.header
    if header is None:
        return ()
    lines = [
        f"文字コード: {ENCODING_LABELS.get(header.encoding, header.encoding)}　改行: {header.newline}　列数: {len(header.columns)}",
        "ヘッダー: 観測済みのfreee出力と同じ（意味の検証は未完了）" if header.observed
        else "ヘッダー: 観測済みのfreee出力と異なります",
    ]
    if header.unknown_columns:
        lines.append("観測していない列: " + "、".join(c or "（列名なし）" for c in header.unknown_columns))
    if header.missing_observed_columns:
        lines.append("観測済みの列のうち無い列: " + "、".join(c or "（列名なし）" for c in header.missing_observed_columns))
    return tuple(lines)


def _tax_lines(diagnosis: FreeeDiagnosis) -> tuple[str, ...]:
    tax = diagnosis.tax
    lines = []
    if tax.get("tax_amount_column_absent"):
        lines.append(f"税額: このCSVには税額の列がありません（{_n(tax['tax_amount_column_absent'])}明細）。税額は推測・計算しません。")
    explicit = tax.get("tax_amount_explicit_nonzero", 0) + tax.get("tax_amount_explicit_zero", 0)
    if explicit:
        lines.append(f"税額: CSVに明示された税額 {_n(explicit)}明細（0円の明示 {_n(tax.get('tax_amount_explicit_zero', 0))}明細を含む）")
    if tax.get("tax_amount_blank"):
        lines.append(f"税額: 列はあるが空欄 {_n(tax['tax_amount_blank'])}明細（0円とは扱いません）")
    if diagnosis.tax_inclusion_raw:
        lines.append("内税・外税: " + "、".join(f"{k} {_n(v)}明細" for k, v in sorted(diagnosis.tax_inclusion_raw.items()))
                     + "（JDLの税入力方法との対応は未確認）")
    elif tax.get("tax_amount_column_absent"):
        lines.append("内税・外税: このCSVには列がありません（不明）")
    methods = {k: v for k, v in diagnosis.tax_accounting_methods.items()}
    if methods:
        lines.append("消費税経理処理方法: " + "、".join(
            ("列なし（不明）" if k == "(列なし)" else k) + f" {_n(v)}仕訳" for k, v in sorted(methods.items())))
    return tuple(lines)


def _tax_rows(diagnosis: FreeeDiagnosis) -> tuple[tuple[str, str, str], ...]:
    rows = []
    for name, count in sorted(diagnosis.tax_categories.items(), key=lambda item: item[0] or ""):
        hint = tax_hint(name)
        kind = _TAX_KIND_LABELS.get(hint.kind, hint.kind)
        if hint.rate:
            kind += f" {hint.rate}%" + ("（軽減）" if hint.reduced else "")
        observed = name in {"対象外", "課税売上10%", "課対仕入10%", "非課売上"}
        kind += "　名前からの参考。JDLへの対応は確認が必要" + ("" if observed else "　※観測していない税区分")
        rows.append((name or "（空欄）", f"{_n(count)}明細", kind))
    return tuple(rows)


def _shape_text(journal) -> str:
    parts = []
    if journal.shape is not None:
        d, c, r = journal.shape
        parts.append(f"借方{d}・貸方{c}（{r}行）")
    if journal.compound:
        parts.append("複合仕訳")
    if journal.closing:
        parts.append("決算整理")
    return "　".join(parts) or "—"


_MAIN_REASON_PRIORITY = (
    "SYSTEM_EVIDENCE:FREEE_JOURNAL_SHAPE_UNOBSERVED", "SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED",
    "SYSTEM_EVIDENCE:UNKNOWN_SOURCE_COLUMN", "SYSTEM_EVIDENCE:FREEE_HEADER_NOT_OBSERVED",
    "SYSTEM_EVIDENCE:FREEE_ROW_DESCRIPTION_INCONSISTENT", "SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT",
    "SYSTEM_EVIDENCE:FREEE_CLOSING_MARKER_UNVERIFIED", "HUMAN:ACCOUNT_DISPLAY_NAME_DIFFERS",
)


def _main_reason(journal) -> str:
    if not journal.parsed:
        return "／".join(reason_label(code) for code in journal.reasons)
    specific = [code for code in _MAIN_REASON_PRIORITY if code in journal.reasons]
    shown = [reason_label(code) for code in specific[:2]]
    rest = len(journal.reasons) - len(shown)
    return "／".join(shown + [f"ほか{rest}件の確認事項"]) if shown else f"確認事項{len(journal.reasons)}件（理由別の表を参照）"


def detect_freee_variant(path: Path) -> FreeeJournalVariant | None:
    """The freee variant of a file's header row, or None when it is not a freee 仕訳帳CSV header. Reads only."""
    try:
        with path.open("rb") as handle:
            head = handle.read(64 * 1024)
    except OSError:
        return None
    first = head.split(b"\n", 1)[0].rstrip(b"\r")
    decoded = decode(first)
    if decoded is None:
        return None
    try:
        columns = tuple(next(csv.reader(io.StringIO(decoded[0]))))
    except (csv.Error, StopIteration):
        return None
    variant = classify_header(columns)
    return None if variant is FreeeJournalVariant.UNKNOWN else variant


def retention_order_labels() -> tuple[str, ...]:
    return tuple(RETENTION_LABELS[status] for status in RETENTION_ORDER)
