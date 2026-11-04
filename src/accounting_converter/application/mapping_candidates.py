"""Ranked JDL target candidates for a source account or subaccount (any source).

Local only: no data leaves the machine. A candidate is a suggestion with its
kind and basis; it is never a decision. The Human selects and confirms; until
then the mapping stays unconfirmed and conversion stays blocked.

Kinds, strongest first:
  APPROVED   the Human already confirmed this target in this company
  EXACT      same name (formal name, display name or abbreviation)
  NORMALIZED same after width / spaces / 等 / 輌→両 normalization
  ALIAS      a general accounting synonym (ALIASES; not company data)
  CONTAINS   one name contains the other
  SIMILAR    character similarity (shown as a number, not as correctness)

A category check compares the source account's tax usage with the JDL
account's normal balance (sales → credit side, purchases/expenses → debit
side). A conflict is shown as a warning and lowers the rank; the candidate is
not hidden, so the Human can still choose it knowingly.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

KIND_LABEL = {
    "APPROVED": "この会社で承認済み",
    "EXACT": "名前が同じ",
    "NORMALIZED": "表記ゆれ（全角半角・空白など）",
    "ALIAS": "一般的な言い換え",
    "CONTAINS": "名前の一部が同じ",
    "SIMILAR": "文字が似ている",
}
_KIND_RANK = {"APPROVED": 6, "EXACT": 5, "NORMALIZED": 4, "ALIAS": 3, "CONTAINS": 2, "SIMILAR": 1}

# General accounting synonyms (not customer data). Each group is one meaning.
ALIASES: tuple[frozenset[str], ...] = tuple(frozenset(group) for group in (
    {"売上高", "売上", "売上金"},
    {"仕入高", "仕入", "商品仕入高"},
    {"普通預金", "普通"},
    {"当座預金", "当座"},
    {"支払手数料", "手数料"},
    {"租税公課", "公租公課"},
    {"旅費交通費", "交通費", "旅費"},
    {"消耗品費", "消耗品"},
    {"事務用品費", "事務用品"},
    {"地代家賃", "家賃", "賃借料"},
    {"水道光熱費", "水道光熱"},
    {"仮払消費税等", "仮払消費税"},
    {"仮受消費税等", "仮受消費税"},
    {"未払消費税等", "未払消費税"},
    {"未払法人税等", "未払法人税"},
    {"減価償却費", "償却費"},
    {"福利厚生費", "厚生費"},
    {"法定福利費", "法定福利"},
    {"給料手当", "給料", "給与手当", "給与"},
    {"役員報酬", "役員給与"},
    {"広告宣伝費", "広告費", "宣伝費"},
    {"雑収入", "雑収益"},
    {"雑損失", "雑損"},
    {"預り金", "預かり金"},
    {"短期借入金", "借入金"},
    {"長期借入金", "借入金"},
    {"工具器具備品", "器具備品", "工具器具"},
    {"車両運搬具", "車輌運搬具"},
    {"車両費", "車輌費"},
    {"期首商品棚卸高", "期首棚卸高"},
    {"期末商品棚卸高", "期末棚卸高"},
    {"通信費", "通信料"},
    {"保険料", "支払保険料"},
    {"支払利息", "支払利息割引料"},
    {"受取利息", "受取利息配当金"},
))


@dataclass(frozen=True)
class TargetAccount:
    code: str
    name: str
    abbreviation: str = ""
    normal_balance: str = ""  # DEBIT / CREDIT / "" (unknown)


@dataclass(frozen=True)
class MappingCandidate:
    code: str
    name: str
    kind: str
    basis: str
    similarity: float
    warning: str = ""

    @property
    def label(self) -> str:
        return KIND_LABEL[self.kind]


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = "".join(text.split()).replace("輌", "両").replace("（", "(").replace("）", ")")
    for suffix in ("等",):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]
    return text


def similarity(a: str, b: str) -> float:
    x, y = normalize(a), normalize(b)
    grams_x = {x[i:i + 2] for i in range(len(x) - 1)} or {x}
    grams_y = {y[i:i + 2] for i in range(len(y) - 1)} or {y}
    return len(grams_x & grams_y) / len(grams_x | grams_y)


def _alias(a: str, b: str) -> bool:
    na, nb = normalize(a), normalize(b)
    return any(na in {normalize(v) for v in group} and nb in {normalize(v) for v in group} for group in ALIASES)


def expected_balance(tax_usage: Iterable[str]) -> str:
    """Normal balance implied by how the source account is taxed (or "")."""
    usage = set(tax_usage)
    sales = {"JDL_SALES_10_EXTERNAL", "JDL_NON_TAXABLE_SALES"} & usage
    purchases = {"JDL_PURCHASE_10_INTERNAL", "JDL_NON_TAXABLE_PURCHASE"} & usage
    if sales and not purchases:
        return "CREDIT"
    if purchases and not sales:
        return "DEBIT"
    return ""


def rank_candidates(
    source_name: str,
    targets: Sequence[TargetAccount],
    *,
    approved_code: str | None = None,
    tax_usage: Iterable[str] = (),
    limit: int = 5,
) -> tuple[MappingCandidate, ...]:
    """Ranked suggestions. Codes are never a reason to exclude a target."""
    expected = expected_balance(tax_usage)
    found: list[tuple[int, float, MappingCandidate]] = []
    for target in targets:
        names = {target.name, target.abbreviation} - {""}
        score = max((similarity(source_name, name) for name in names), default=0.0)
        if approved_code and target.code == approved_code:
            kind, basis = "APPROVED", "この会社で以前に承認した対応"
        elif source_name in names:
            kind, basis = "EXACT", "名前が同じ"
        elif any(normalize(source_name) == normalize(name) for name in names):
            kind, basis = "NORMALIZED", "全角半角・空白・「等」などを除くと同じ"
        elif any(_alias(source_name, name) for name in names):
            kind, basis = "ALIAS", "会計でよく使う言い換え（一般辞書）"
        elif any(
            len(normalize(name)) >= 2 and (normalize(name) in normalize(source_name) or normalize(source_name) in normalize(name))
            for name in names
        ):
            kind, basis = "CONTAINS", "一方の名前がもう一方を含む"
        elif score >= 0.3:
            kind, basis = "SIMILAR", f"文字の重なり {score:.2f}（会計上の正しさを示すものではありません）"
        else:
            continue
        warning = ""
        rank = _KIND_RANK[kind]
        if expected and target.normal_balance and target.normal_balance != expected and kind != "APPROVED":
            warning = ("使われ方（売上側）と、JDL科目の貸借（借方）が逆です" if expected == "CREDIT"
                       else "使われ方（仕入・費用側）と、JDL科目の貸借（貸方）が逆です")
            rank -= 2
        found.append((rank, score, MappingCandidate(target.code, target.name, kind, basis, round(score, 2), warning)))
    found.sort(key=lambda item: (-item[0], -item[1], item[2].code))
    return tuple(item[2] for item in found[:limit])
