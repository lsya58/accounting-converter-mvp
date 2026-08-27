from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DocumentedSpecificationStatus(str, Enum):
    OFFICIAL_DOCUMENTED = "OFFICIAL_DOCUMENTED"
    REAL_DATA_VERIFICATION_PENDING = "REAL_DATA_VERIFICATION_PENDING"


@dataclass(frozen=True)
class YayoiOfficialColumnDefinition:
    position: int
    name: str
    required: bool = False
    max_length: int | None = None
    data_type: str | None = None


@dataclass(frozen=True)
class YayoiOfficialImportSpecification:
    name: str
    product_family: str
    documented_version: str
    source_title: str
    source_url: str
    statuses: tuple[DocumentedSpecificationStatus, ...]
    columns: tuple[YayoiOfficialColumnDefinition, ...]
    identifier_flags: tuple[str, ...]
    is_formal_format_profile: bool = False

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


YAYOI_ACCOUNTING_05_OFFICIAL_IMPORT_COLUMNS: tuple[
    YayoiOfficialColumnDefinition,
    ...,
] = (
    YayoiOfficialColumnDefinition(1, "識別フラグ", required=True, max_length=4, data_type="文字"),
    YayoiOfficialColumnDefinition(2, "伝票No.", max_length=6, data_type="数字"),
    YayoiOfficialColumnDefinition(3, "決算", max_length=4, data_type="文字"),
    YayoiOfficialColumnDefinition(4, "取引日付", required=True, max_length=10, data_type="日付"),
    YayoiOfficialColumnDefinition(5, "借方勘定科目", data_type="文字"),
    YayoiOfficialColumnDefinition(6, "借方補助科目", data_type="文字"),
    YayoiOfficialColumnDefinition(7, "借方部門", data_type="文字"),
    YayoiOfficialColumnDefinition(8, "借方税区分", data_type="文字"),
    YayoiOfficialColumnDefinition(9, "借方金額", required=True, data_type="金額"),
    YayoiOfficialColumnDefinition(10, "借方税金額", data_type="金額"),
    YayoiOfficialColumnDefinition(11, "貸方勘定科目", data_type="文字"),
    YayoiOfficialColumnDefinition(12, "貸方補助科目", data_type="文字"),
    YayoiOfficialColumnDefinition(13, "貸方部門", data_type="文字"),
    YayoiOfficialColumnDefinition(14, "貸方税区分", data_type="文字"),
    YayoiOfficialColumnDefinition(15, "貸方金額", required=True, data_type="金額"),
    YayoiOfficialColumnDefinition(16, "貸方税金額", data_type="金額"),
    YayoiOfficialColumnDefinition(17, "摘要", max_length=30, data_type="文字"),
    YayoiOfficialColumnDefinition(18, "番号", data_type="文字"),
    YayoiOfficialColumnDefinition(19, "期日", data_type="日付"),
    YayoiOfficialColumnDefinition(20, "タイプ", data_type="数字"),
    YayoiOfficialColumnDefinition(21, "生成元", data_type="文字"),
    YayoiOfficialColumnDefinition(22, "仕訳メモ", data_type="文字"),
    YayoiOfficialColumnDefinition(23, "付箋1", max_length=1, data_type="数字"),
    YayoiOfficialColumnDefinition(24, "付箋2", data_type="数字"),
    YayoiOfficialColumnDefinition(25, "調整", data_type="文字"),
)


def yayoi_accounting_05_official_import_spec() -> YayoiOfficialImportSpecification:
    return YayoiOfficialImportSpecification(
        name="弥生取り込み（インポート）形式（弥生会計05以降）",
        product_family="弥生会計",
        documented_version="05以降",
        source_title=(
            "仕訳データの項目と記述形式"
            "（他製品から仕訳データをインポートする場合など）"
        ),
        source_url="https://support.yayoi-kk.co.jp/subcontents.html?page_id=18545",
        statuses=(
            DocumentedSpecificationStatus.OFFICIAL_DOCUMENTED,
            DocumentedSpecificationStatus.REAL_DATA_VERIFICATION_PENDING,
        ),
        columns=YAYOI_ACCOUNTING_05_OFFICIAL_IMPORT_COLUMNS,
        identifier_flags=("2000", "2111", "2110", "2100", "2101"),
        is_formal_format_profile=False,
    )
