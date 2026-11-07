"""Subaccounts that need a JDL registration or an explicit JDL target: sheet, then bulk apply.

write  one CSV (UTF-8 with BOM) of every open subaccount whose JDL parent has subaccounts but
       none with the same name (parent-only is impossible there). Sorted so the few that need
       thought come first (`application.subaccount_registration`). Written only under
       data/private. Nothing is selected or confirmed by writing it.
apply  reads the filled sheet. Checks EVERY filled row against the company's CURRENT JDL master
       (exact code + name, unique, usable under that parent) and the currently open items; any
       problem stops everything. Without --apply it only checks. With --apply it saves the rows
       marked 済 in one call through the app's own mapping save path (all-or-nothing; the store
       is restored if anything fails). 保留 / blank rows stay open and keep blocking.

After registering subaccounts in JDL, reload the JDL 科目一覧 PDF in the app first; until then a
新規登録 row fails the check ("not in the current JDL master"), by design.

Prints counts only.

  PYTHONPATH=src python3 -m accounting_converter.tools.yayoi_subaccount_registration write \\
      --source ... --company-store ... --company-id ... --output data/private/.../補助登録シート.csv
  PYTHONPATH=src python3 -m accounting_converter.tools.yayoi_subaccount_registration apply \\
      --source ... --company-store ... --company-id ... --sheet ... [--apply --backup-dir ...]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from accounting_converter.application import parent_subaccount_policy as policy
from accounting_converter.application import subaccount_registration as reg
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.ui.controllers import AccountingConverterController

HEADER = (
    "順", "分類", "説明", "弥生親科目", "弥生補助名称", "JDL親科目コード", "影響仕訳数",
    "一致したJDL補助（コード 名称）", "参考：似た名前（別の相手の可能性。自動では選ばない）",
    "弥生名称はJDLの名前欄（20バイト）に入るか", "新規登録する場合の名称案",
    "【記入】判断（既存補助／新規登録／保留）", "【記入】JDL補助コード", "【記入】JDL補助名称", "【記入】確認済み（済）",
)
INPUT = tuple(name for name in HEADER if name.startswith("【記入】"))


def _controller(store: Path, prefs: Path) -> AccountingConverterController:
    profiles = ConversionProfileStore(store / "profiles")
    companies = CompanySettingStore(store / "companies", profiles)
    return AccountingConverterController(profile_store=profiles, company_store=companies,
                                         preferences_store=ApplicationPreferencesStore(prefs))


def _review(controller, company_id: str, source: Path):
    controller.load_company_settings()
    controller.select_file(source)
    controller.select_company_setting(company_id)
    return controller.review_company_mapping_updates(company_id, source)


def _jdl_subs(context) -> tuple[reg.JdlSub, ...]:
    return (tuple(reg.JdlSub(s.parent_account_code, s.target_master_code, s.output_name, True) for s in context.subaccounts)
            + tuple(reg.JdlSub(s.parent_account_code, s.code, s.name, False) for s in context.unusable_subaccounts))


def open_items(review, context, source: Path):
    """(item, jdl parent code, distinct journals) for every open class-C subaccount."""
    code_of = {a.mapping_value: a.target_master_code for a in context.account_master}
    wanted = {}
    for group in policy.parent_groups(review):
        for member in group.unconfirmed:
            if member.item.mapping_type == "SUBACCOUNT" and member.klass == policy.NEEDS_JDL_SUB:
                wanted[(member.item.parent_account or "", member.item.source_value)] = (member.item, code_of.get(member.parent_target or "", ""))
    journals: dict[tuple[str, str], set] = defaultdict(set)
    for entry in detect_format(source).diagnose(source).entries:
        for line in entry.lines:
            key = (line.account, line.sub_account or "")
            if key in wanted:
                journals[key].add(entry.id)
    return [(item, parent_code, len(journals[key])) for key, (item, parent_code) in wanted.items()]


def build_rows(review, context, source: Path) -> list[reg.RegistrationRow]:
    subs = _jdl_subs(context)
    return reg.sort_rows(reg.classify(item.parent_account or "", item.source_value, parent_code, count, subs)
                         for item, parent_code, count in open_items(review, context, source))


def _private(path: Path) -> None:
    if "data/private" not in path.resolve().as_posix():
        raise SystemExit("the sheet contains customer names: write it under data/private only")


def write(args) -> int:
    _private(args.output)
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory) / "store"
        shutil.copytree(args.company_store, scratch)  # read-only use of the real store
        controller = _controller(scratch, Path(directory) / "prefs.json")
        review = _review(controller, args.company_id, args.source)
        context = controller.company_store.resolve(args.company_id).context
        rows = build_rows(review, context, args.source)
    buffer = io.StringIO()
    out = csv.writer(buffer, lineterminator="\r\n")
    out.writerow(HEADER)
    for number, row in enumerate(rows, 1):
        out.writerow((
            number, reg.ORDER.index(row.category) + 1, row.label, row.source_parent, row.source_name,
            row.jdl_parent_code, row.journals,
            " / ".join(f"{m.code} {m.name}" for m in row.matched),
            " / ".join(row.similar_for_reference),
            "入る" if row.source_name_fits_jdl else "入らない（短い名前をHumanが決める）",
            row.suggested_new_name if row.category != reg.NOTATION_DIFF else "", "", "", "", "",
        ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("﻿" + buffer.getvalue(), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "by_category": dict(Counter(r.category for r in rows)),
                      "journals_per_category": {k: sum(r.journals for r in rows if r.category == k) for k in reg.ORDER},
                      "source_name_does_not_fit_jdl": sum(not r.source_name_fits_jdl for r in rows)},
                     ensure_ascii=False, indent=1))
    return 0


def _read(path: Path) -> list[dict]:
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SystemExit("the sheet is not UTF-8 (saved by Excel in another encoding?)")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or tuple(rows[0]) != HEADER:
        raise SystemExit("the sheet header differs (columns added, removed or reordered)")
    return [dict(zip(HEADER, row)) for row in rows[1:] if any(cell.strip() for cell in row)]


def plan(args, controller, review):
    context = controller.company_store.resolve(args.company_id).context
    items = {(item.parent_account or "", item.source_value): (item, parent_code)
             for item, parent_code, _count in open_items(review, context, args.source)}
    filled, problems = [], []
    for number, record in enumerate(_read(args.sheet), 2):
        key = (record["弥生親科目"], record["弥生補助名称"])
        decision = record["【記入】判断（既存補助／新規登録／保留）"].strip()
        done = record["【記入】確認済み（済）"].strip()
        if done not in {"", "済"}:
            problems.append((number, "確認済みの欄は 済 か空欄"))
            continue
        if key not in items:
            if decision or done:
                problems.append((number, "この補助は現在の確認待ち（JDL補助が必要な補助）に無い（確認済み・別の親科目・古いシート）"))
            continue
        item, parent_code = items[key]
        if record["JDL親科目コード"] != parent_code:
            problems.append((number, "JDL親科目コードが現在の設定と違う（古いシート）"))
            continue
        filled.append(reg.FilledRow(number, key[0], key[1], parent_code, decision,
                                    record["【記入】JDL補助コード"].strip(), record["【記入】JDL補助名称"].strip(), done == "済"))
    ready, more = reg.check_filled_rows(filled, _jdl_subs(context))
    problems += more
    selections = {items[(row.source_parent, row.source_name)][0].key: row.name for row in ready}
    return selections, problems, len(filled) - len(ready)


def apply(args) -> int:
    controller = _controller(args.company_store, args.company_store / "_unused_prefs.json") if args.apply else None
    with tempfile.TemporaryDirectory() as directory:
        # The check always runs on a scratch copy; the real store is written only by --apply below.
        scratch = Path(directory) / "store"
        shutil.copytree(args.company_store, scratch)
        check_controller = _controller(scratch, Path(directory) / "prefs.json")
        review = _review(check_controller, args.company_id, args.source)
        selections, problems, still_open = plan(args, check_controller, review)
        if problems:
            print(json.dumps({"check": "FAIL", "applied": False,
                              "problems": [{"sheet_row": r, "reason": why} for r, why in problems]},
                             ensure_ascii=False, indent=1))
            return 2
        # Dry run of the real save path on the scratch copy: it must accept every selection.
        if selections:
            check_controller.apply_company_mapping_updates(review, selections, set(selections), {}, set())
    if not args.apply:
        print(json.dumps({"check": "PASS", "applied": False, "would_save": len(selections), "still_open_rows": still_open},
                         ensure_ascii=False, indent=1))
        return 0
    if not selections:
        print(json.dumps({"check": "PASS", "applied": False, "would_save": 0}, ensure_ascii=False, indent=1))
        return 0
    paths = [args.company_store / "profiles", args.company_store / "companies" / args.company_id]
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / "snapshot"
        for path in paths:
            shutil.copytree(path, snapshot / path.relative_to(args.company_store))
        if args.backup_dir:
            shutil.copytree(snapshot, args.backup_dir, dirs_exist_ok=False)
        try:
            review = _review(controller, args.company_id, args.source)
            selections, problems, still_open = plan(args, controller, review)
            if problems:
                raise RuntimeError("the store changed between check and apply")
            saved = controller.apply_company_mapping_updates(review, selections, set(selections), {}, set())
        except Exception:
            for path in paths:
                shutil.rmtree(path)
                shutil.copytree(snapshot / path.relative_to(args.company_store), path)
            raise
    print(json.dumps({"check": "PASS", "applied": True, "saved": saved, "still_open_rows": still_open},
                     ensure_ascii=False, indent=1))
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
    sub.choices["apply"].add_argument("--apply", action="store_true", help="save; without it only checks")
    sub.choices["apply"].add_argument("--backup-dir", type=Path, help="copy the company's settings here before saving")
    args = parser.parse_args()
    return write(args) if args.command == "write" else apply(args)


if __name__ == "__main__":
    raise SystemExit(main())
