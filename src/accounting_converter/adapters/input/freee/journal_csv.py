"""freee会計 仕訳帳CSV (新CSV 97列 / 旧CSV 29列): strict, header-driven reading for DIAGNOSIS ONLY.

Status: NOT a production input adapter (not an `InputAdapter`, not in `production_adapter_registry`).

Evidence (EVIDENCE_ID below; private, not in Git — the originals hold an account e-mail address and
freee internal IDs): one real export of each variant from a freee 個人事業主 test office, six
hand-entered fictitious 振替伝票 (2026-11-15). docs/research/freee_journal_csv_public_spec.md §5
lists what this sample settles and what it does not. From it:

- the exact headers (`OLD_CSV_29_HEADER`, `NEW_CSV_97_HEADER`) are OBSERVED. Observed is not
  verified: `VERIFIED_HEADER_FINGERPRINTS` stays empty, because column MEANINGS beyond what six
  journals show, other plans / settings / freee releases, and any JDL round trip are unverified;
- columns are still read by NAME, never by position; a column not in the observed header of its
  variant is kept verbatim (SourceFieldValue known=False) and blocks;
- a column whose VALUES were all blank in the sample (部門, セグメント, 取引先コード, 管理番号 …) may be
  read, but a non-blank value is reported as unobserved; so is any value outside the small value sets
  seen for enumerated columns (決算整理仕訳 0/1, 内税・外税 内税, 消費税経理処理方法 税込経理, …);
- the 旧CSV leading column (header "") and the 新CSV "No" / "レコード番号" are DISPLAY numbers: the same
  journal was 1 in a one-journal export and 5 in the six-journal one. They group rows inside one file
  only and are never an identity. The journal identity is 仕訳ID (新CSV) / 仕訳番号 (旧CSV);
- an empty side of a compound row is: 新CSV all side columns blank; 旧CSV 勘定科目 "" + 金額 "0" +
  税区分 "対象外" and nothing else. Only that exact shape is an empty side; the row is kept;
- tax: 新CSV has explicit 税金額 / 内税・外税 / 税率 / 軽減税率有無 and a 消費税経理処理方法 column; the
  旧CSV has none of them. Nothing missing is computed or guessed.

Entries use the common model (domain.journal) and the neutral keys of domain.journal_rows and
domain.source_information. Nothing is dropped silently.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path

from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.journal_identity import JOURNAL_CONTENT_IDENTITY_KEY, journal_content_identity
from accounting_converter.domain.journal_rows import (
    LINE_COUNTERPARTY_KEY,
    LINE_ROW_DESCRIPTION_KEY,
    LINE_ROW_KEY,
    ROW_ORDER_KEY,
)
from accounting_converter.domain.source_information import (
    ENTRY_CLOSING_ADJUSTMENT_KEY,
    ENTRY_SOURCE_FIELDS_KEY,
    ENTRY_SOURCE_FORMAT_KEY,
    SourceFieldScope,
    SourceFieldValue,
)

SOURCE_FORMAT_PREFIX = "freee_journal_csv"
EVIDENCE_ID = "EVID-FREEE-JOURNAL-CSV-REAL-EXPORT-20261115-001"

# Entry / line metadata keys (freee-specific; read by application.freee_diagnosis only).
BLANK_SIDES_KEY = "freee_blank_sides"  # tuple[(row_number, "DEBIT"|"CREDIT", representation)]
DISPLAY_NUMBER_KEY = "freee_display_number"  # file-local, NOT an identity
JOURNAL_ID_KIND_KEY = "freee_journal_id_kind"  # "仕訳ID" | "仕訳番号"
UNOBSERVED_VALUES_KEY = "freee_unobserved_values"  # tuple[column names]: non-blank but never seen
TAX_ACCOUNTING_METHOD_KEY = "freee_tax_accounting_method"  # raw 消費税経理処理方法 (新CSV)
PERIOD_END_FLAG_KEY = "freee_period_end_flag"  # raw 期末日取引フラグ (新CSV), not interpreted
REGISTRATION_METHOD_KEY = "freee_registration_method"  # raw 登録した方法 (新CSV)
LINE_SIDE_DESCRIPTION_KEY = "freee_side_description"  # raw 借方備考 / 貸方備考 (新CSV)
LINE_DISPLAY_NAME_KEY = "freee_account_display_name"
LINE_ACCOUNT_CODE_KEY = "freee_account_code"  # freee-side code column; NOT a JDL code
# tuple[(column name, non-blank cells)] of one journal, in header order. Column NAMES and counts only (no values):
# lets a diagnosis account for every non-blank cell, including the ones carried by the common model.
NONBLANK_COLUMNS_KEY = "freee_nonblank_columns"

BLANK_SIDE_NEW_ALL_EMPTY = "NEW_ALL_SIDE_COLUMNS_EMPTY"
BLANK_SIDE_OLD_ZERO_PLACEHOLDER = "OLD_EMPTY_ACCOUNT_ZERO_AMOUNT_OUT_OF_SCOPE"


class FreeeJournalVariant(str, Enum):
    NEW_CSV = "NEW_CSV"  # 「CSVエクスポート」: 97 columns observed
    OLD_CSV = "OLD_CSV"  # 「CSV・PDFエクスポート(旧)」: 29 columns observed (all optional items on)
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------- observed headers

OLD_CSV_29_HEADER: tuple[str, ...] = (
    "", "取引日",
    "借方勘定科目", "借方金額", "借方税区分", "借方品目", "借方部門", "借方メモ",
    "貸方勘定科目", "貸方金額", "貸方税区分", "貸方品目", "貸方部門", "貸方メモ",
    "取引先", "摘要", "決算整理仕訳", "仕訳番号", "借方取引先", "貸方取引先", "管理番号", "作成日時",
    "借方勘定科目コード", "貸方勘定科目コード", "更新日時", "承認状況", "承認者", "承認日時", "作成者",
)

_NEW_SIDE_SUFFIXES: tuple[str, ...] = (
    "勘定科目", "決算書表示名", "勘定科目ショートカット１", "勘定科目ショートカット２（勘定科目コード）",
    "金額", "税区分", "税金額", "内税・外税", "税率", "軽減税率有無",
    "取引先コード", "取引先名", "取引先ショートカット１", "取引先ショートカット２",
    "品目", "品目ショートカット１", "品目ショートカット２",
    "部門", "部門ショートカット１", "部門ショートカット２",
    "メモ", "メモショートカット１", "メモショートカット２",
    "セグメント１", "セグメント１ショートカット１", "セグメント１ショートカット２",
    "セグメント２", "セグメント２ショートカット１", "セグメント２ショートカット２",
    "セグメント３", "セグメント３ショートカット１", "セグメント３ショートカット２",
    "備考",
)
NEW_CSV_97_HEADER: tuple[str, ...] = (
    "No", "取引日", "管理番号",
    *(f"借方{suffix}" for suffix in _NEW_SIDE_SUFFIXES),
    *(f"貸方{suffix}" for suffix in _NEW_SIDE_SUFFIXES),
    "決算整理仕訳", "発行元", "作成日時", "更新日時",
    "承認状況(仕訳承認)", "申請者(仕訳承認)", "申請日時(仕訳承認)", "承認者(仕訳承認)", "承認日時(仕訳承認)",
    "作成者", "消費税経理処理方法", "取引ID", "口座振替ID", "振替伝票ID", "仕訳ID", "仕訳番号",
    "期末日取引フラグ", "取引支払日", "仕訳行番号", "仕訳行数", "レコード番号", "取引内容", "登録した方法",
    "経費精算 申請番号", "支払依頼 申請番号", "ファイル番号", "一次承認者(仕訳承認)", "一次承認日時(仕訳承認)",
)


def header_fingerprint(columns: tuple[str, ...]) -> str:
    return hashlib.sha256("\x1f".join(columns).encode("utf-8")).hexdigest()


OBSERVED_HEADERS: dict[FreeeJournalVariant, tuple[str, ...]] = {
    FreeeJournalVariant.OLD_CSV: OLD_CSV_29_HEADER,
    FreeeJournalVariant.NEW_CSV: NEW_CSV_97_HEADER,
}
OBSERVED_HEADER_FINGERPRINTS: dict[str, FreeeJournalVariant] = {
    header_fingerprint(columns): variant for variant, columns in OBSERVED_HEADERS.items()
}
# Verified = header AND meanings AND a real JDL round trip. Nothing is verified today.
VERIFIED_HEADER_FINGERPRINTS: frozenset[str] = frozenset()


# --------------------------------------------------------------------------- column roles

class Role(str, Enum):
    DISPLAY_NUMBER = "DISPLAY_NUMBER"  # groups rows inside one file; changes on re-export
    RECORD_NUMBER = "RECORD_NUMBER"  # 新CSV レコード番号: file-local row ordinal
    JOURNAL_ID = "JOURNAL_ID"  # 新CSV 仕訳ID
    VOUCHER_ID = "VOUCHER_ID"  # 新CSV 振替伝票ID
    JOURNAL_SERIAL = "JOURNAL_SERIAL"  # 仕訳番号 (both)
    LINE_NUMBER = "LINE_NUMBER"  # 新CSV 仕訳行番号
    LINE_COUNT = "LINE_COUNT"  # 新CSV 仕訳行数
    DATE = "DATE"
    ACCOUNT = "ACCOUNT"
    ACCOUNT_DISPLAY_NAME = "ACCOUNT_DISPLAY_NAME"
    ACCOUNT_CODE = "ACCOUNT_CODE"  # freee-side code (旧 勘定科目コード / 新 ショートカット２（勘定科目コード）)
    AMOUNT = "AMOUNT"
    TAX_CATEGORY = "TAX_CATEGORY"
    TAX_AMOUNT = "TAX_AMOUNT"
    TAX_INCLUSION = "TAX_INCLUSION"  # 内税・外税
    TAX_RATE = "TAX_RATE"
    TAX_REDUCED = "TAX_REDUCED"
    TAX_ACCOUNTING_METHOD = "TAX_ACCOUNTING_METHOD"
    DEPARTMENT = "DEPARTMENT"
    COUNTERPARTY = "COUNTERPARTY"
    ROW_DESCRIPTION = "ROW_DESCRIPTION"  # 旧CSV 摘要 (one per row; composed by freee, see the research doc)
    SIDE_DESCRIPTION = "SIDE_DESCRIPTION"  # 新CSV 借方備考 / 貸方備考
    CLOSING = "CLOSING"  # 決算整理仕訳
    PERIOD_END_FLAG = "PERIOD_END_FLAG"  # 期末日取引フラグ
    REGISTRATION_METHOD = "REGISTRATION_METHOD"  # 登録した方法
    PERSONAL = "PERSONAL"  # 作成者 / 承認者 …: personal data, never reported
    INFORMATION = "INFORMATION"  # kept as a source field; no common-model slot


@dataclass(frozen=True)
class ColumnRole:
    role: Role
    side: Side | None
    values_observed: bool  # a non-blank value was seen in the real sample


def _side(name: str) -> tuple[Side | None, str]:
    if name.startswith("借方"):
        return Side.DEBIT, name[2:]
    if name.startswith("貸方"):
        return Side.CREDIT, name[2:]
    return None, name


_OLD_ROLES = {
    "": Role.DISPLAY_NUMBER, "取引日": Role.DATE, "勘定科目": Role.ACCOUNT, "金額": Role.AMOUNT,
    "税区分": Role.TAX_CATEGORY, "部門": Role.DEPARTMENT, "取引先": Role.COUNTERPARTY,
    "摘要": Role.ROW_DESCRIPTION, "決算整理仕訳": Role.CLOSING, "仕訳番号": Role.JOURNAL_SERIAL,
    "勘定科目コード": Role.ACCOUNT_CODE, "作成者": Role.PERSONAL, "承認者": Role.PERSONAL,
}
_NEW_ROLES = {
    "No": Role.DISPLAY_NUMBER, "レコード番号": Role.RECORD_NUMBER, "仕訳ID": Role.JOURNAL_ID,
    "振替伝票ID": Role.VOUCHER_ID, "仕訳番号": Role.JOURNAL_SERIAL, "仕訳行番号": Role.LINE_NUMBER,
    "仕訳行数": Role.LINE_COUNT, "取引日": Role.DATE, "勘定科目": Role.ACCOUNT,
    "決算書表示名": Role.ACCOUNT_DISPLAY_NAME, "勘定科目ショートカット２（勘定科目コード）": Role.ACCOUNT_CODE,
    "金額": Role.AMOUNT, "税区分": Role.TAX_CATEGORY, "税金額": Role.TAX_AMOUNT,
    "内税・外税": Role.TAX_INCLUSION, "税率": Role.TAX_RATE, "軽減税率有無": Role.TAX_REDUCED,
    "消費税経理処理方法": Role.TAX_ACCOUNTING_METHOD, "部門": Role.DEPARTMENT, "取引先名": Role.COUNTERPARTY,
    "備考": Role.SIDE_DESCRIPTION, "決算整理仕訳": Role.CLOSING, "期末日取引フラグ": Role.PERIOD_END_FLAG,
    "登録した方法": Role.REGISTRATION_METHOD, "作成者": Role.PERSONAL, "申請者(仕訳承認)": Role.PERSONAL,
    "承認者(仕訳承認)": Role.PERSONAL, "一次承認者(仕訳承認)": Role.PERSONAL,
}

# Columns with at least one non-blank value in the 2026-11-15 sample.
_OLD_VALUES_OBSERVED = frozenset({
    "", "取引日", "借方勘定科目", "借方金額", "借方税区分", "借方品目", "借方メモ", "貸方勘定科目", "貸方金額",
    "貸方税区分", "摘要", "決算整理仕訳", "仕訳番号", "借方取引先", "作成日時", "借方勘定科目コード",
    "貸方勘定科目コード", "更新日時", "承認状況", "作成者",
})
_NEW_VALUES_OBSERVED = frozenset({
    "No", "取引日",
    *(f"{prefix}{suffix}" for prefix in ("借方", "貸方") for suffix in (
        "勘定科目", "決算書表示名", "勘定科目ショートカット１", "勘定科目ショートカット２（勘定科目コード）",
        "金額", "税区分", "税金額", "内税・外税", "税率", "軽減税率有無", "備考",
    )),
    "借方取引先名", "借方品目", "借方メモ",
    "決算整理仕訳", "作成日時", "更新日時", "承認状況(仕訳承認)", "作成者", "消費税経理処理方法", "振替伝票ID",
    "仕訳ID", "仕訳番号", "期末日取引フラグ", "取引支払日", "仕訳行番号", "仕訳行数", "レコード番号", "登録した方法",
})

# Enumerated columns (keyed without the 借方/貸方 prefix): only these values were seen. Anything else is
# read but reported as unobserved.
OBSERVED_VALUE_SETS: dict[str, frozenset[str]] = {
    "決算整理仕訳": frozenset({"0", "1"}),
    "期末日取引フラグ": frozenset({"0", "1"}),
    "内税・外税": frozenset({"内税"}),
    "税率": frozenset({"0", "10"}),
    "軽減税率有無": frozenset({"0"}),
    "消費税経理処理方法": frozenset({"税込経理"}),
    "登録した方法": frozenset({"振替伝票"}),
    "承認状況": frozenset({"なし"}),
    "承認状況(仕訳承認)": frozenset({"なし"}),
    # 借方/貸方税区分: the four names in the sample. Any other (課税売上8%(軽), 控80, 輸出 …) is unobserved.
    "税区分": frozenset({"対象外", "課税売上10%", "課対仕入10%", "非課売上"}),
}
# (debit lines, credit lines, physical rows) seen in the sample: 1D1C in one row, and 1D2C over two rows
# with the debit side of row 2 blank. Any other shape (2D2C, 1D3C, blank credit side …) is unobserved.
OBSERVED_JOURNAL_SHAPES: frozenset[tuple[int, int, int]] = frozenset({(1, 1, 1), (1, 2, 2)})


def _roles(columns: tuple[str, ...], table: dict[str, Role], observed: frozenset[str]) -> dict[str, ColumnRole]:
    roles: dict[str, ColumnRole] = {}
    for name in columns:
        side, base = _side(name)
        role = table.get(base)
        roles[name] = ColumnRole(role or Role.INFORMATION, side, name in observed)
    return roles


COLUMN_ROLES: dict[FreeeJournalVariant, dict[str, ColumnRole]] = {
    FreeeJournalVariant.OLD_CSV: _roles(OLD_CSV_29_HEADER, _OLD_ROLES, _OLD_VALUES_OBSERVED),
    FreeeJournalVariant.NEW_CSV: _roles(NEW_CSV_97_HEADER, _NEW_ROLES, _NEW_VALUES_OBSERVED),
}

# Identification: each variant has columns the other does not have; both sets must be present.
NEW_CSV_MARKERS = frozenset({"No", "仕訳ID", "振替伝票ID", "仕訳行番号", "仕訳行数", "借方備考", "貸方備考"})
OLD_CSV_MARKERS = frozenset({"", "摘要", "借方勘定科目コード", "貸方勘定科目コード"})
REQUIRED_COLUMNS: dict[FreeeJournalVariant, tuple[str, ...]] = {
    FreeeJournalVariant.OLD_CSV: ("", "取引日", "借方勘定科目", "借方金額", "借方税区分", "貸方勘定科目",
                                  "貸方金額", "貸方税区分", "仕訳番号", "決算整理仕訳"),
    FreeeJournalVariant.NEW_CSV: ("No", "取引日", "借方勘定科目", "借方金額", "借方税区分", "貸方勘定科目",
                                  "貸方金額", "貸方税区分", "仕訳ID", "振替伝票ID", "仕訳番号", "仕訳行番号",
                                  "仕訳行数", "決算整理仕訳"),
}
# 取引日 format seen per variant.
_DATE_FORMATS = {
    FreeeJournalVariant.OLD_CSV: re.compile(r"(?P<y>[0-9]{4})/(?P<m>[0-9]{2})/(?P<d>[0-9]{2})"),
    FreeeJournalVariant.NEW_CSV: re.compile(r"(?P<y>[0-9]{4})-(?P<m>[0-9]{2})-(?P<d>[0-9]{2})"),
}
_AMOUNT = re.compile(r"-?[0-9]+")
_POSITIVE_INT = re.compile(r"[1-9][0-9]*")


class FreeeIssue(str, Enum):
    # file level (nothing is parsed)
    UNREADABLE = "UNREADABLE"
    ENCODING_UNKNOWN = "ENCODING_UNKNOWN"
    MALFORMED_CSV = "MALFORMED_CSV"
    NO_DATA_ROWS = "NO_DATA_ROWS"
    VARIANT_UNKNOWN = "VARIANT_UNKNOWN"  # neither or both marker sets: never guessed
    REQUIRED_COLUMN_MISSING = "REQUIRED_COLUMN_MISSING"
    DUPLICATE_COLUMN = "DUPLICATE_COLUMN"
    COLUMN_COUNT_MISMATCH = "COLUMN_COUNT_MISMATCH"
    # journal level (that journal is rejected, its rows counted)
    JOURNAL_NUMBER_MISSING = "JOURNAL_NUMBER_MISSING"
    JOURNAL_NUMBER_REUSED = "JOURNAL_NUMBER_REUSED"
    JOURNAL_ID_INCONSISTENT = "JOURNAL_ID_INCONSISTENT"  # 仕訳番号 / 振替伝票ID / No differ inside a journal
    LINE_NUMBERING_INCONSISTENT = "LINE_NUMBERING_INCONSISTENT"  # 仕訳行番号 not 1..n or 仕訳行数 != n
    DATE_FORMAT_UNVERIFIED = "DATE_FORMAT_UNVERIFIED"
    MULTIPLE_DATES = "MULTIPLE_DATES"
    AMOUNT_FORMAT_UNVERIFIED = "AMOUNT_FORMAT_UNVERIFIED"
    SIDE_WITHOUT_ACCOUNT_OR_AMOUNT = "SIDE_WITHOUT_ACCOUNT_OR_AMOUNT"
    EMPTY_ROW = "EMPTY_ROW"
    CLOSING_MIXED = "CLOSING_MIXED"  # rows of one journal disagree on 決算整理仕訳
    TAX_ACCOUNTING_METHOD_MIXED = "TAX_ACCOUNTING_METHOD_MIXED"
    UNBALANCED = "UNBALANCED"


FILE_LEVEL_ISSUES = frozenset({
    FreeeIssue.UNREADABLE, FreeeIssue.ENCODING_UNKNOWN, FreeeIssue.MALFORMED_CSV, FreeeIssue.NO_DATA_ROWS,
    FreeeIssue.VARIANT_UNKNOWN, FreeeIssue.REQUIRED_COLUMN_MISSING, FreeeIssue.DUPLICATE_COLUMN,
    FreeeIssue.COLUMN_COUNT_MISMATCH,
})


@dataclass(frozen=True)
class FreeeHeader:
    columns: tuple[str, ...]
    variant: FreeeJournalVariant
    encoding: str  # "utf-8-sig" | "utf-8" | "cp932"
    newline: str  # "LF" | "CRLF" | "MIXED" | "NONE"
    fingerprint: str
    unknown_columns: tuple[str, ...]  # not in the observed header of this variant
    missing_observed_columns: tuple[str, ...]  # in the observed header, absent here

    @property
    def observed(self) -> bool:
        """Byte-for-byte the header of the real sample (same variant)."""
        return OBSERVED_HEADER_FINGERPRINTS.get(self.fingerprint) is self.variant

    @property
    def verified(self) -> bool:
        return self.fingerprint in VERIFIED_HEADER_FINGERPRINTS

    @property
    def source_format_key(self) -> str:
        return f"{SOURCE_FORMAT_PREFIX}:{self.variant.value}:{self.fingerprint[:16]}"


@dataclass(frozen=True)
class FreeeJournalIssue:
    code: FreeeIssue
    row_number: int | None = None
    journal_number: str | None = None  # display number (file-local) for locating the row
    column: str | None = None


@dataclass
class FreeeParseResult:
    header: FreeeHeader | None
    entries: tuple[JournalEntry, ...] = ()
    issues: tuple[FreeeJournalIssue, ...] = ()
    data_rows: int = 0
    rejected_journals: int = 0
    rejected_rows: int = 0
    _rejected_numbers: tuple[str, ...] = field(default=(), repr=False)

    @property
    def file_readable(self) -> bool:
        return self.header is not None and not any(i.code in FILE_LEVEL_ISSUES for i in self.issues)

    @property
    def accepted_rows(self) -> int:
        return sum(len(entry.metadata.get(ROW_ORDER_KEY, ())) for entry in self.entries)


def decode(raw: bytes) -> tuple[str, str] | None:
    """(text, encoding) using only the encodings freee documents (UTF-8 with/without BOM, Shift-JIS).

    UTF-16 (BOM) and NUL bytes are rejected: CP932 would otherwise "decode" them into garbage.
    The real 旧/新CSV sample is UTF-8 without BOM; Shift-JIS output of these two is not observed.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw:
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig", errors="strict"), "utf-8-sig"
        except UnicodeDecodeError:
            return None
    for encoding in ("utf-8", "cp932"):
        try:
            return raw.decode(encoding, errors="strict"), encoding
        except UnicodeDecodeError:
            continue
    return None


def _newline(raw: bytes) -> str:
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if crlf and lf:
        return "MIXED"
    return "CRLF" if crlf else ("LF" if lf else "NONE")


def classify_header(columns: tuple[str, ...]) -> FreeeJournalVariant:
    """NEW / OLD only when that variant's markers are ALL present and none of the other's are."""
    names = set(columns)
    new_all, old_all = NEW_CSV_MARKERS <= names, OLD_CSV_MARKERS <= names
    new_any, old_any = bool(names & NEW_CSV_MARKERS), bool(names & OLD_CSV_MARKERS)
    if new_all and not old_any:
        return FreeeJournalVariant.NEW_CSV
    if old_all and not new_any:
        return FreeeJournalVariant.OLD_CSV
    return FreeeJournalVariant.UNKNOWN


def _side_columns(header: FreeeHeader, side: Side) -> tuple[str, ...]:
    prefix = "借方" if side is Side.DEBIT else "貸方"
    return tuple(name for name in header.columns if name.startswith(prefix))


class FreeeJournalCsvParser:
    def parse_path(self, path: Path) -> FreeeParseResult:
        try:
            raw = path.read_bytes()
        except OSError:
            return FreeeParseResult(None, issues=(FreeeJournalIssue(FreeeIssue.UNREADABLE),))
        return self.parse_bytes(raw, file_name=path.name)

    def parse_bytes(self, raw: bytes, file_name: str = "<memory>") -> FreeeParseResult:
        decoded = decode(raw)
        if decoded is None:
            return FreeeParseResult(None, issues=(FreeeJournalIssue(FreeeIssue.ENCODING_UNKNOWN),))
        text, encoding = decoded
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error:
            return FreeeParseResult(None, issues=(FreeeJournalIssue(FreeeIssue.MALFORMED_CSV),))
        if not rows:
            return FreeeParseResult(None, issues=(FreeeJournalIssue(FreeeIssue.NO_DATA_ROWS),))
        columns = tuple(rows[0])
        issues: list[FreeeJournalIssue] = []
        variant = classify_header(columns)
        observed = OBSERVED_HEADERS.get(variant, ())
        header = FreeeHeader(
            columns=columns,
            variant=variant,
            encoding=encoding,
            newline=_newline(raw),
            fingerprint=header_fingerprint(columns),
            unknown_columns=tuple(name for name in columns if name not in observed),
            missing_observed_columns=tuple(name for name in observed if name not in columns),
        )
        if variant is FreeeJournalVariant.UNKNOWN:
            issues.append(FreeeJournalIssue(FreeeIssue.VARIANT_UNKNOWN, 1))
        duplicates = sorted({name for name in columns if columns.count(name) > 1})
        issues += [FreeeJournalIssue(FreeeIssue.DUPLICATE_COLUMN, 1, column=name) for name in duplicates]
        issues += [
            FreeeJournalIssue(FreeeIssue.REQUIRED_COLUMN_MISSING, 1, column=name)
            for name in REQUIRED_COLUMNS.get(variant, ()) if name not in columns
        ]
        data = rows[1:]
        if not data:
            issues.append(FreeeJournalIssue(FreeeIssue.NO_DATA_ROWS))
        issues += [
            FreeeJournalIssue(FreeeIssue.COLUMN_COUNT_MISMATCH, index)
            for index, row in enumerate(data, start=2) if len(row) != len(columns)
        ]
        if any(issue.code in FILE_LEVEL_ISSUES for issue in issues):
            return FreeeParseResult(header, issues=tuple(issues), data_rows=len(data))
        return _JournalBuilder(header, file_name).build(data, issues)


class _JournalBuilder:
    def __init__(self, header: FreeeHeader, file_name: str) -> None:
        self.header = header
        self.file_name = file_name
        self.variant = header.variant
        self.roles = COLUMN_ROLES[header.variant]
        self.new = header.variant is FreeeJournalVariant.NEW_CSV
        self.group_column = "仕訳ID" if self.new else ""
        self.id_column = "仕訳ID" if self.new else "仕訳番号"
        self.display_column = "No" if self.new else ""

    def role(self, name: str) -> ColumnRole | None:
        return self.roles.get(name)

    # ------------------------------------------------------------------ rows -> journals

    def build(self, data, issues) -> FreeeParseResult:
        records = [(index, dict(zip(self.header.columns, row))) for index, row in enumerate(data, start=2)]
        groups: list[tuple[str, list[tuple[int, dict]]]] = []
        seen: set[str] = set()
        reused: set[str] = set()
        for row_number, record in records:
            key = record.get(self.group_column, "").strip()
            if not key:
                issues.append(FreeeJournalIssue(
                    FreeeIssue.JOURNAL_NUMBER_MISSING, row_number, record.get(self.display_column), self.group_column,
                ))
                groups.append(("", [(row_number, record)]))
                continue
            if groups and groups[-1][0] == key:
                groups[-1][1].append((row_number, record))
                continue
            if key in seen:
                reused.add(key)
            seen.add(key)
            groups.append((key, [(row_number, record)]))
        # 旧CSV: groups by the display number; the journal identity 仕訳番号 must not repeat either.
        if not self.new:
            serial_groups: dict[str, set[str]] = {}
            for key, rows in groups:
                if key:
                    for _, record in rows:
                        serial_groups.setdefault(record.get("仕訳番号", ""), set()).add(key)
            reused |= {key for keys in serial_groups.values() if len(keys) > 1 for key in keys}
        entries: list[JournalEntry] = []
        rejected: list[str] = []
        rejected_rows = 0
        for key, rows in groups:
            display = rows[0][1].get(self.display_column)
            if not key:
                rejected_rows += len(rows)
                rejected.append("")
                continue
            if key in reused:
                issues.append(FreeeJournalIssue(FreeeIssue.JOURNAL_NUMBER_REUSED, rows[0][0], display))
                rejected_rows += len(rows)
                rejected.append(display or "")
                continue
            entry, journal_issues = self._entry(rows)
            issues += journal_issues
            if entry is None:
                rejected_rows += len(rows)
                rejected.append(display or "")
            else:
                entries.append(entry)
        return FreeeParseResult(
            self.header, tuple(entries), tuple(issues), data_rows=len(records),
            rejected_journals=len(rejected), rejected_rows=rejected_rows, _rejected_numbers=tuple(rejected),
        )

    def _consistency(self, rows) -> FreeeJournalIssue | None:
        first_row, first = rows[0]
        display = first.get(self.display_column)
        same = ["仕訳番号", self.display_column] + (["振替伝票ID", "仕訳行数"] if self.new else [])
        for name in same:
            if len({record.get(name, "") for _, record in rows}) != 1:
                return FreeeJournalIssue(FreeeIssue.JOURNAL_ID_INCONSISTENT, first_row, display, name)
        if not first.get(self.id_column, "").strip():
            return FreeeJournalIssue(FreeeIssue.JOURNAL_NUMBER_MISSING, first_row, display, self.id_column)
        if self.new:
            numbers = [record.get("仕訳行番号", "") for _, record in rows]
            count = first.get("仕訳行数", "")
            if (
                not all(_POSITIVE_INT.fullmatch(value) for value in (*numbers, count))
                or [int(value) for value in numbers] != list(range(1, len(rows) + 1))
                or int(count) != len(rows)
            ):
                return FreeeJournalIssue(FreeeIssue.LINE_NUMBERING_INCONSISTENT, first_row, display, "仕訳行番号")
        return None

    def _entry(self, rows):
        first_row, first = rows[0]
        display = first.get(self.display_column)
        problem = self._consistency(rows)
        if problem is not None:
            return None, [problem]
        dates = {record.get("取引日", "") for _, record in rows}
        if len(dates) != 1:
            return None, [FreeeJournalIssue(FreeeIssue.MULTIPLE_DATES, first_row, display)]
        entry_date = self._date(next(iter(dates)))
        if entry_date is None:
            return None, [FreeeJournalIssue(FreeeIssue.DATE_FORMAT_UNVERIFIED, first_row, display, "取引日")]
        closing_values = {record.get("決算整理仕訳", "") for _, record in rows}
        if len(closing_values) != 1:
            return None, [FreeeJournalIssue(FreeeIssue.CLOSING_MIXED, first_row, display, "決算整理仕訳")]
        methods = {record.get("消費税経理処理方法", "") for _, record in rows}
        if len(methods) != 1:
            return None, [FreeeJournalIssue(
                FreeeIssue.TAX_ACCOUNTING_METHOD_MIXED, first_row, display, "消費税経理処理方法",
            )]

        issues: list[FreeeJournalIssue] = []
        lines: list[JournalLine] = []
        fields: list[SourceFieldValue] = []
        blank_sides: list[tuple[int, str, str]] = []
        unobserved: list[str] = []
        nonblank: dict[str, int] = {}
        for row_number, record in rows:
            row_lines: list[JournalLine] = []
            row_problems: list[FreeeJournalIssue] = []
            row_description = self._row_description(record)
            for side in (Side.DEBIT, Side.CREDIT):
                line, problem, blank = self._line(row_number, record, side, row_description, display)
                if problem is not None:
                    row_problems.append(problem)
                elif blank is not None:
                    blank_sides.append((row_number, side.value, blank))
                elif line is not None:
                    row_lines.append(line)
            if not row_lines and not row_problems:
                row_problems.append(FreeeJournalIssue(FreeeIssue.EMPTY_ROW, row_number, display))
            issues += row_problems
            lines += row_lines
            for name in self.header.columns:
                value = record.get(name, "")
                if not value:
                    continue
                nonblank[name] = nonblank.get(name, 0) + 1
                role = self.role(name)
                if role is None:  # not in the observed header: kept verbatim, never interpreted
                    fields.append(SourceFieldValue(name, value, SourceFieldScope.ROW, row_number, known=False))
                    continue
                allowed = OBSERVED_VALUE_SETS.get(_side(name)[1])
                if not role.values_observed or (allowed is not None and value not in allowed):
                    unobserved.append(name)
                if role.role in _COMMON_MODEL_ROLES:
                    continue
                scope = SourceFieldScope(role.side.value) if role.side is not None else SourceFieldScope.ROW
                fields.append(SourceFieldValue(name, value, scope, row_number))
        if issues:
            return None, issues
        closing = next(iter(closing_values))
        journal_id = first[self.id_column].strip()
        entry = JournalEntry(
            id=f"freee:{self.variant.value}:{journal_id}",
            source_reference=SourceReference(self.file_name, first_row, journal_id),
            date=entry_date,
            lines=lines,
            description=_single({self._row_description(record) or "" for _, record in rows}),
            metadata={
                "source": SOURCE_FORMAT_PREFIX,
                "evidence_level": "OBSERVED_REAL_EXPORT_SINGLE_SAMPLE",
                "evidence_id": EVIDENCE_ID,
                "production_registry_enabled": False,
                "freee_variant": self.variant.value,
                "freee_header_fingerprint": self.header.fingerprint,
                "freee_header_observed": self.header.observed,
                ENTRY_SOURCE_FORMAT_KEY: self.header.source_format_key,
                ENTRY_SOURCE_FIELDS_KEY: tuple(fields),
                # Only the observed value "1" is a closing marker; "0" is an ordinary journal.
                **({ENTRY_CLOSING_ADJUSTMENT_KEY: closing} if closing not in {"", "0"} else {}),
                ROW_ORDER_KEY: tuple(row_number for row_number, _ in rows),
                BLANK_SIDES_KEY: tuple(blank_sides),
                DISPLAY_NUMBER_KEY: display,
                JOURNAL_ID_KIND_KEY: self.id_column,
                UNOBSERVED_VALUES_KEY: tuple(dict.fromkeys(unobserved)),
                NONBLANK_COLUMNS_KEY: tuple((name, nonblank[name]) for name in self.header.columns if name in nonblank),
                **({TAX_ACCOUNTING_METHOD_KEY: next(iter(methods))} if next(iter(methods)) else {}),
                **({PERIOD_END_FLAG_KEY: first["期末日取引フラグ"]} if first.get("期末日取引フラグ") else {}),
                **({REGISTRATION_METHOD_KEY: first["登録した方法"]} if first.get("登録した方法") else {}),
                JOURNAL_CONTENT_IDENTITY_KEY: journal_content_identity(
                    self.header.source_format_key,
                    entry_date.isoformat(),
                    tuple(
                        tuple(
                            record.get(name, "") for name in self.header.columns
                            if (self.role(name) or ColumnRole(Role.INFORMATION, None, False)).role
                            not in {Role.DISPLAY_NUMBER, Role.RECORD_NUMBER}
                        )
                        for _, record in rows
                    ),
                ),
                "transaction_number_scope": "SOURCE_FILE_LOCAL_DISPLAY_NUMBER",
            },
        )
        if not entry.is_balanced():
            return None, [FreeeJournalIssue(FreeeIssue.UNBALANCED, first_row, display)]
        return entry, []

    def _date(self, value: str) -> date | None:
        match = _DATE_FORMATS[self.variant].fullmatch(value)
        if match is None:
            return None
        try:
            return date(int(match["y"]), int(match["m"]), int(match["d"]))
        except ValueError:
            return None

    def _row_description(self, record: dict) -> str | None:
        """旧CSV: 摘要. 新CSV: the side 備考 when both sides agree (or one is blank); None when they differ."""
        if not self.new:
            return record.get("摘要", "")
        values = {record.get("借方備考", ""), record.get("貸方備考", "")} - {""}
        if len(values) > 1:
            return None
        return next(iter(values), "")

    def _blank_side(self, record: dict, side: Side) -> str | None:
        columns = _side_columns(self.header, side)
        prefix = "借方" if side is Side.DEBIT else "貸方"
        values = {name: record.get(name, "") for name in columns}
        if not any(values.values()):
            return BLANK_SIDE_NEW_ALL_EMPTY if self.new else None
        if self.new:
            return None
        rest = {name: value for name, value in values.items()
                if name not in {f"{prefix}勘定科目", f"{prefix}金額", f"{prefix}税区分"}}
        if (
            values.get(f"{prefix}勘定科目") == "" and values.get(f"{prefix}金額") == "0"
            and values.get(f"{prefix}税区分") == "対象外" and not any(rest.values())
        ):
            return BLANK_SIDE_OLD_ZERO_PLACEHOLDER
        return None

    def _line(self, row_number, record, side: Side, row_description: str | None, display):
        """(line, problem, blank-side representation): exactly one of the three is not None."""
        prefix = "借方" if side is Side.DEBIT else "貸方"
        blank = self._blank_side(record, side)
        if blank is not None:
            return None, None, blank
        account = record.get(f"{prefix}勘定科目", "")
        amount_text = record.get(f"{prefix}金額", "")
        # Anything else without an account or an amount (incl. a fully blank 旧CSV side, never observed).
        if not account or not amount_text:
            return None, FreeeJournalIssue(
                FreeeIssue.SIDE_WITHOUT_ACCOUNT_OR_AMOUNT, row_number, display, prefix,
            ), None
        amount = _parse_amount(amount_text)
        if amount is None:
            return None, FreeeJournalIssue(
                FreeeIssue.AMOUNT_FORMAT_UNVERIFIED, row_number, display, f"{prefix}金額",
            ), None
        tax_category = record.get(f"{prefix}税区分", "")
        tax_column = f"{prefix}税金額"
        tax_amount_text = record.get(tax_column, "")
        tax_amount = None
        if tax_amount_text:
            tax_amount = _parse_amount(tax_amount_text)
            if tax_amount is None:
                return None, FreeeJournalIssue(
                    FreeeIssue.AMOUNT_FORMAT_UNVERIFIED, row_number, display, tax_column,
                ), None
        rate_text = record.get(f"{prefix}税率", "")
        reduced_text = record.get(f"{prefix}軽減税率有無", "")
        inclusion = record.get(f"{prefix}内税・外税", "")
        tax_info = TaxInfo(
            category=tax_category or None,
            # 税率 is an explicit column (新CSV). Nothing is derived from the 税区分 name here.
            rate=Decimal(rate_text) if _AMOUNT.fullmatch(rate_text) else None,
            # The 新CSV value (内税/外税) is kept raw: its relation to JDL 税入力方法 is unverified.
            tax_inclusion=None,
            reduced_rate={"0": False}.get(reduced_text),
            tax_amount=tax_amount,
            metadata={
                "source_format": SOURCE_FORMAT_PREFIX,
                "tax_amount_column_present": tax_column in record,
                "tax_amount_blank": tax_column in record and not tax_amount_text,
                "freee_tax_inclusion_raw": inclusion or None,
                "freee_tax_rate_raw": rate_text or None,
                "freee_reduced_rate_raw": reduced_text or None,
                "tax_inclusion_source": "FREEE_COLUMN_RAW" if inclusion else "NOT_IN_EXPORT",
            },
        ) if tax_category or tax_amount_text or rate_text or inclusion else None
        counterparty = record.get(f"{prefix}取引先名", "") or record.get(f"{prefix}取引先", "")
        display_name = record.get(f"{prefix}決算書表示名", "")
        code = record.get(f"{prefix}勘定科目コード", "") or record.get(f"{prefix}勘定科目ショートカット２（勘定科目コード）", "")
        side_description = record.get(f"{prefix}備考", "")
        return JournalLine(
            side=side,
            account=account,
            amount=amount,
            source_reference=SourceReference(self.file_name, row_number, record.get(self.id_column, "")),
            sub_account=None,  # freee exports no 補助科目 column; never derived (口座・タグ are Human decisions)
            department=record.get(f"{prefix}部門", "") or None,
            tax_info=tax_info,
            metadata={
                LINE_ROW_KEY: row_number,
                # When the two side 備考 differ the row has no single description: each line carries its own
                # and journal_physical_rows() reports the row semantics as inconsistent (never merged).
                LINE_ROW_DESCRIPTION_KEY: row_description if row_description is not None else side_description,
                **({LINE_COUNTERPARTY_KEY: counterparty} if counterparty else {}),
                **({LINE_DISPLAY_NAME_KEY: display_name} if display_name else {}),
                **({LINE_ACCOUNT_CODE_KEY: code} if code else {}),
                **({LINE_SIDE_DESCRIPTION_KEY: side_description} if self.new else {}),
            },
        ), None, None


# Values carried by the common model (or by the dedicated metadata keys) rather than as source fields.
_COMMON_MODEL_ROLES = frozenset({
    Role.DATE, Role.ACCOUNT, Role.AMOUNT, Role.TAX_CATEGORY, Role.TAX_AMOUNT, Role.TAX_RATE, Role.TAX_REDUCED,
    Role.TAX_INCLUSION, Role.DEPARTMENT, Role.ROW_DESCRIPTION, Role.SIDE_DESCRIPTION, Role.CLOSING,
    Role.DISPLAY_NUMBER, Role.RECORD_NUMBER,
})


def _parse_amount(value: str) -> Decimal | None:
    return Decimal(value) if _AMOUNT.fullmatch(value) else None


def _single(values: set[str]) -> str | None:
    values = {value for value in values if value}
    return next(iter(values)) if len(values) == 1 else None
