"""Office confirmation sheet for one Yayoi → JDL company: write it, then apply it.

write: one CSV (UTF-8 with BOM, opens in Excel) listing every decision the
       office must make, what the current candidate is, and what to do in JDL.
       Written only under data/private. Nothing is confirmed by writing it.
apply: reads the sheet back and saves ONLY rows the office filled in:
         判断 = OK      → accept the shown candidate
         JDLコード      → use that JDL code (must exist in the company's JDL list)
         意味           → required for 部門 / 生成元 / 付箋 policies
       Blank rows stay unconfirmed. Exact-name candidates are never accepted
       without an explicit OK. Prints counts only.

The sheet is a Human decision record, so each saved mapping carries the
sheet's SHA-256.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application.yayoi_jdl_workflow import YayoiJdlWorkflow
from accounting_converter.application.yayoi_review import (
    DEPARTMENT_FIELD,
    candidate_semantic,
    confirm_optional_field_policy,
    confirm_tax_identity,
    field_of,
    non_retained_values,
)
from accounting_converter.application.yayoi_sources import detect_format, format_for_identity_key
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.tools.generate_mf_exact_shape_probe import _atomic_write

HEADER = ("No", "区分", "キー", "弥生の内容", "親科目（補助のみ）", "影響仕訳数", "現在の候補",
          "判断の選択肢", "JDLでの操作", "【記入】判断", "【記入】JDLコード", "【記入】意味・メモ", "注意")
SEMANTIC_LABEL = {
    JdlTaxSemantic.NO_TAX: "対象外（税なし）",
    JdlTaxSemantic.PURCHASE_10_INTERNAL: "課税仕入 10% 内税",
    JdlTaxSemantic.SALES_10_EXTERNAL: "課税売上 10% 外税",
    JdlTaxSemantic.NON_TAXABLE_PURCHASE: "非課税仕入",
    JdlTaxSemantic.NON_TAXABLE_SALES: "非課税売上",
}
# Accounts on which JDL Evidence for 10% sales exists (see moneyforward_tax_excluded_evidence).
SALES10_VERIFIED = ("6121", "9251")


def _store(path: Path):
    profiles = ConversionProfileStore(path / "profiles")
    return profiles, CompanySettingStore(path / "companies", profiles)


def build_rows(source: Path, profile, context) -> list[tuple]:
    source_format = format_for_identity_key(profile.source_format_identity.stable_key) or detect_format(source)
    entries = source_format.read(source)
    accounts_by_name = {}
    for item in context.account_master:
        accounts_by_name.setdefault(item.mapping_value, []).append(item)
    subs_by_parent = Counter(item.parent_account_code for item in context.subaccounts)
    journals = lambda predicate: sum(1 for entry in entries if any(predicate(line) for line in entry.lines))  # noqa: E731
    rows = []
    sales_accounts = {line.account for entry in entries for line in entry.lines
                      if line.tax_info and candidate_semantic(line.tax_info.category) is JdlTaxSemantic.SALES_10_EXTERNAL}
    for name in sorted({line.account for entry in entries for line in entry.lines}):
        exact = accounts_by_name.get(name, [])
        candidate = f"{exact[0].target_master_code} {exact[0].target_formal_name}" if len(exact) == 1 else ""
        note = ""
        if name in sales_accounts:
            note = ("売上10%の行あり。会計上正しいJDL科目を選んでください。"
                    f"JDLでの実機確認が済んでいる売上科目は {'・'.join(SALES10_VERIFIED)} だけなので、"
                    "それ以外を選んだ場合はアプリ側で実機検証を1回追加します（科目選びの理由にはしないでください）")
        rows.append((
            "科目", name, name, "", journals(lambda line, n=name: line.account == n), candidate,
            "候補でよければ OK / 別のJDL科目ならコードを記入" if candidate else
            "使うJDL科目のコードを記入（JDLにない場合は先にJDLで科目登録）",
            "なし" if candidate else "JDLに無ければ科目登録",
            note,
        ))
    pairs = sorted({(line.account, line.sub_account) for entry in entries for line in entry.lines if line.sub_account})
    for parent, sub in pairs:
        parent_candidates = accounts_by_name.get(parent, [])
        parent_code = parent_candidates[0].target_master_code if len(parent_candidates) == 1 else None
        same = [item for item in context.subaccounts
                if item.parent_account_code == parent_code and item.output_name == sub]
        candidate = f"{same[0].target_master_code} {same[0].output_name}" if len(same) == 1 else ""
        rows.append((
            "補助科目", f"{parent}｜{sub}", sub, parent,
            journals(lambda line, p=parent, s=sub: line.account == p and line.sub_account == s), candidate,
            "候補でよければ OK / 別の補助ならJDL補助コードを記入" if candidate else
            "JDLに補助を登録してその補助コードを記入（弥生の補助がJDLに残る）",
            "なし" if candidate else "JDLで親科目の下に補助を登録",
            "親科目だけで出す方法は、補助の情報がJDLに残らないため現在は選べません"
            + ("（このJDL会社は補助が0件）" if not subs_by_parent else ""),
        ))
    for identity in sorted({line.tax_info.category for entry in entries for line in entry.lines
                            if line.tax_info and line.tax_info.category}):
        semantic = candidate_semantic(identity)
        rows.append((
            "税区分", identity, identity, "",
            journals(lambda line, i=identity: bool(line.tax_info) and line.tax_info.category == i),
            SEMANTIC_LABEL.get(semantic, "（候補なし）") if semantic else "（候補なし）",
            "候補でよければ OK" if semantic else "候補がないため実機の書き方確認が先",
            "なし", "",
        ))
    values_by_field: dict[str, set[str]] = {}
    for entry in entries:
        for _, name, value in non_retained_values(entry):
            values_by_field.setdefault(field_of(name), set()).add(value)
    fields = Counter(field_of(name) for entry in entries for name in {n for _, n, _ in non_retained_values(entry)})
    for field, count in sorted(fields.items()):
        rows.append((
            "JDLに入らない情報", field, field, "", count, describe_field(field, values_by_field[field]),
            "説明でよければ OK（違う場合は【記入】意味・メモに書く）→ JDLには出さず、元の値を監査記録ファイルに残す",
            "なし",
            "このJDL会社は部門なし。JDLで部門を使う場合は会社設定の変更が必要（今回は対象外）"
            if field == DEPARTMENT_FIELD else "",
        ))
    return [(index, *row[:8], "", "", "", row[8]) for index, row in enumerate(rows, 1)]


# Official 弥生インポート形式: 生成元 values listed on the spec page; 付箋 0-5.
OFFICIAL_ORIGIN_VALUES = frozenset({"受手", "支手", "償却", "預金", "借入", "一括", "按分", "給与", "販売", "会OL"})


def describe_field(field: str, values: set[str]) -> str:
    """Factual description from the official spec and the observed values (no customer values)."""
    if field == DEPARTMENT_FIELD:
        return f"弥生の部門（{len(values)}種類）"
    if field == "生成元":
        listed = sum(value in OFFICIAL_ORIGIN_VALUES for value in values)
        return (f"弥生の生成元（仕訳を作った機能・{len(values)}種類）。"
                + ("公式資料の一覧にある値" if listed == len(values) else "公式資料の一覧にない値を含む（一覧は網羅と書かれていない）"))
    if field in {"付箋1", "付箋2"}:
        outside = sum(not (value.isdigit() and int(value) <= 5) for value in values)
        return (f"弥生の{field}（{len(values)}種類）。"
                + (f"公式の範囲0〜5の外の値が{outside}種類あり、意味は公式資料から特定できない" if outside
                   else "公式の範囲0〜5の値"))
    return f"弥生の{field}（{len(values)}種類）"


def write(args) -> int:
    if "data/private" not in args.output.resolve().as_posix():
        raise SystemExit("the sheet contains customer data; write it under data/private only")
    profiles, companies = _store(args.company_store)
    resolved = companies.resolve(args.company_id)
    if resolved.context is None:
        raise SystemExit("company setting is not confirmed yet")
    rows = build_rows(args.source, resolved.profile, resolved.context)
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows([HEADER, *rows])
    _atomic_write(args.output, buffer.getvalue().encode("utf-8-sig"))
    print(json.dumps({"written": True, "rows": dict(Counter(row[1] for row in rows))}, ensure_ascii=False))
    return 0


def apply(args) -> int:
    raw = args.sheet.read_bytes()
    sheet_sha = hashlib.sha256(raw).hexdigest()
    records = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    profiles, companies = _store(args.company_store)
    resolved = companies.resolve(args.company_id)
    context = resolved.context
    if context is None:
        raise SystemExit("company setting is not confirmed yet")
    profile_id = resolved.profile.profile_id
    by_code = {item.target_master_code: item for item in context.account_master}
    counts: Counter = Counter()
    errors: Counter = Counter()
    profile = profiles.get(profile_id)
    accounts = dict(profile.account_mappings)
    subs = dict(profile.subaccount_context_mappings)
    now = datetime.now(timezone.utc).isoformat()
    for record in records:
        kind, key = record["区分"], record["キー"]
        decision = record["【記入】判断"].strip().upper()
        code = record["【記入】JDLコード"].strip()
        meaning = record["【記入】意味・メモ"].strip()
        if not decision and not code:
            counts[f"{kind}:unfilled"] += 1
            continue
        if kind == "科目":
            target_code = code or (record["現在の候補"].split(" ", 1)[0] if decision == "OK" else "")
            target = by_code.get(target_code)
            if target is None:
                errors["科目:JDLコードが科目一覧にない"] += 1
                continue
            accounts[key] = MappingValue(key, target.mapping_value, MappingStatus.USER_CONFIRMED, metadata={
                "target_code": target.target_master_code, "target_printed_name": target.mapping_value,
                "target_formal_name": target.target_formal_name, "confirmed_via": "office_sheet",
                "office_sheet_sha256": sheet_sha, "confirmed_at": now})
            counts["科目:confirmed"] += 1
        elif kind == "補助科目":
            parent = record["親科目（補助のみ）"]
            parent_mapping = accounts.get(parent)
            parent_code = parent_mapping.metadata.get("target_code") if parent_mapping else None
            if not code and decision == "OK":
                code = record["現在の候補"].split(" ", 1)[0]
            matches = [item for item in context.subaccounts
                       if item.parent_account_code == parent_code and item.target_master_code == code.zfill(4)]
            if not code or len(matches) != 1:
                errors["補助科目:親科目未確定またはJDL補助コードが一覧にない"] += 1
                continue
            target = matches[0]
            subs[MappingKey(MappingType.SUBACCOUNT, record["弥生の内容"], parent)] = MappingValue(
                record["弥生の内容"], target.output_name, MappingStatus.USER_CONFIRMED, parent_account=parent,
                metadata={"output_code": target.output_code, "target_code": target.target_master_code,
                          "output_name": target.output_name, "confirmed_via": "office_sheet",
                          "office_sheet_sha256": sheet_sha, "confirmed_at": now})
            counts["補助科目:confirmed"] += 1
        elif kind == "税区分":
            semantic = candidate_semantic(key)
            if decision != "OK" or semantic is None:
                errors["税区分:OK以外または候補なし"] += 1
                continue
            counts["税区分:confirmed"] += 1
        elif kind == "JDLに入らない情報":
            if decision != "OK" or not (meaning or record["現在の候補"].strip()):
                errors["JDLに入らない情報:OKと意味の両方が必要"] += 1
                continue
            counts["JDLに入らない情報:confirmed"] += 1
    profiles.update(replace(profile, account_mappings=accounts, subaccount_context_mappings=subs,
                            updated_at=datetime.now(timezone.utc)))
    for record in records:
        decision = record["【記入】判断"].strip().upper()
        if record["区分"] == "税区分" and decision == "OK" and candidate_semantic(record["キー"]) is not None:
            confirm_tax_identity(profiles, profile_id, context, record["キー"], candidate_semantic(record["キー"]))
        meaning = record["【記入】意味・メモ"].strip() or record["現在の候補"].strip()
        if record["区分"] == "JDLに入らない情報" and decision == "OK" and meaning:
            confirm_optional_field_policy(profiles, profile_id, record["キー"], meaning)
    companies.replace_profile(args.company_id, profile_id)
    resolved = companies.resolve(args.company_id)
    assessment = YayoiJdlWorkflow().assess(args.source, resolved.profile, resolved.context)
    print(json.dumps({
        "applied": dict(counts), "rejected": dict(errors),
        "ready_journals": assessment.ready_journals, "total_journals": assessment.entry_count,
        "by_blocker": assessment.blocker_counts(),
        "likely_after_tax_confirmation": assessment.likely_blocker_counts(),
        "information_fully_retained": assessment.information_fully_retained,
    }, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "apply"):
        command = sub.add_parser(name)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--company-store", type=Path, required=True)
        command.add_argument("--company-id", required=True)
    sub.choices["write"].add_argument("--output", type=Path, required=True)
    sub.choices["apply"].add_argument("--sheet", type=Path, required=True)
    args = parser.parse_args()
    return write(args) if args.command == "write" else apply(args)


if __name__ == "__main__":
    raise SystemExit(main())
