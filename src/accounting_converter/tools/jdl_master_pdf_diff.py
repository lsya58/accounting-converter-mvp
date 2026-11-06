"""Compare two JDL 科目一覧 PDFs (text layer) account by account. Read-only; changes no setting.

Per page line it recovers, in print order:
  coded    "1111  現金 ..."            code, name, 略名称, 使用 ○/×
  parent   "1311- 普通預金 ..."        a coded account that has subaccounts
  uncoded  "            当座１ ..."    a printed account whose code is NOT printed. Its code exists in JDL;
                                       it is identified here only by (name, position after which coded
                                       account). Never treated as "not an account".
  sub      "  -0001 名称 ..."           a subaccount of the last parent
  group    "流動性預金 借"             a group label printed AFTER the accounts it closes
Nothing is inferred from names. `使用 ○/×` is kept apart from existence.

  PYTHONPATH=$pylib:src python3 -m accounting_converter.tools.jdl_master_pdf_diff OLD.pdf NEW.pdf --out data/private/.../diff.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from accounting_converter.application.jdl_account_list_pdf import JdlAccountListPdfTextParser as P

GROUP = re.compile(r"^(?P<name>\S.*?)\s+(?P<side>[借貸])\s*$")


def extract(pdf: Path) -> list[str]:
    from accounting_converter.infrastructure.jdl_account_pdf_draft import PypdfTextExtractor

    return list(PypdfTextExtractor().extract_pages(pdf))


def records(pages: list[str]) -> list[dict]:
    out, last_code, last_parent, order = [], "", None, 0
    for page_number, text in enumerate(pages, 1):
        for line in text.splitlines():
            for kind, pattern in (("parent", P._PARENT_ROW), ("coded", P._CODED_ROW)):
                m = pattern.match(line)
                if m:
                    order += 1
                    out.append({"kind": kind, "code": m["code"], "name": m["name"].strip(), "abbr": m["abbreviation"].strip(),
                                "use": m["use"], "page": page_number, "order": order, "after": last_code})
                    last_code = m["code"]
                    last_parent = (m["code"], m["name"].strip()) if kind == "parent" else None
                    break
            else:
                m = P._SUBACCOUNT_ROW.match(line)
                if m and last_parent:
                    order += 1
                    out.append({"kind": "sub", "parent": last_parent[0], "code": m["code"], "name": m["name"].strip(),
                                "balance": m["balance"], "page": page_number, "order": order})
                    continue
                m = P._UNCODED_ROW.match(line)
                if m:
                    order += 1
                    out.append({"kind": "uncoded", "code": "", "name": m["name"].strip(), "abbr": m["abbreviation"].strip(),
                                "use": m["use"], "page": page_number, "order": order, "after": last_code})
                    continue
                g = GROUP.match(line)
                if g and not line.startswith(" ") and "科目一覧" not in line and "勘定科目" not in line:
                    order += 1
                    out.append({"kind": "group", "name": g["name"].strip(), "side": g["side"], "page": page_number, "order": order})
    # Group labels are printed AFTER the accounts they close (innermost first). An account's group chain is
    # the nearest consecutive run of labels that follows it in print order.
    chain: list[str] = []
    previous_was_group = False
    for record in reversed(out):
        if record["kind"] == "group":
            chain = ([record["name"]] + chain) if previous_was_group else [record["name"]]
            previous_was_group = True
        else:
            if record["kind"] in {"coded", "parent", "uncoded"}:
                record["group_chain"] = list(chain)
            previous_was_group = False
    return out


def _accounts(recs):
    return {r["code"]: r for r in recs if r["kind"] in {"coded", "parent"}}


def diff(old: list[dict], new: list[dict]) -> dict:
    a, b = _accounts(old), _accounts(new)
    added = [b[c] for c in sorted(set(b) - set(a))]
    removed = [a[c] for c in sorted(set(a) - set(b))]
    changed = []
    for code in sorted(set(a) & set(b)):
        delta = {k: (a[code].get(k), b[code].get(k)) for k in ("name", "abbr", "use", "kind") if a[code].get(k) != b[code].get(k)}
        if a[code].get("group_chain") != b[code].get("group_chain"):
            delta["group_chain"] = (a[code].get("group_chain"), b[code].get("group_chain"))
        if delta:
            changed.append({"code": code, **delta})
    names = lambda recs: Counter(r["name"] for r in recs if r["kind"] in {"coded", "parent"} and r["use"] == "○")  # noqa: E731
    dup_names = {"old": sorted(n for n, c in names(old).items() if c > 1), "new": sorted(n for n, c in names(new).items() if c > 1)}
    key = lambda r: (r["after"], r["name"])  # noqa: E731
    u_old, u_new = Counter(key(r) for r in old if r["kind"] == "uncoded"), Counter(key(r) for r in new if r["kind"] == "uncoded")
    subs = lambda recs: {(r["parent"], r["code"]): r["name"] for r in recs if r["kind"] == "sub"}  # noqa: E731
    s_old, s_new = subs(old), subs(new)
    return {
        "coded_accounts": {"old": len(a), "new": len(b)},
        "added": added, "removed": removed, "changed": changed,
        "duplicate_enabled_names": dup_names,
        "uncoded": {"old": sum(u_old.values()), "new": sum(u_new.values()),
                    "appeared": sorted((k, n) for k, n in (u_new - u_old).items()),
                    "disappeared": sorted((k, n) for k, n in (u_old - u_new).items())},
        "subaccounts": {"old": len(s_old), "new": len(s_new),
                        "added": sorted(set(s_new) - set(s_old)), "removed": sorted(set(s_old) - set(s_new)),
                        "renamed": sorted(k for k in set(s_old) & set(s_new) if s_old[k] != s_new[k])},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="full result with real names (under data/private)")
    args = parser.parse_args()
    if "data/private" not in args.out.resolve().as_posix():
        raise SystemExit("the result contains customer names; write it under data/private only")
    old, new = records(extract(args.old)), records(extract(args.new))
    result = diff(old, new)
    result["sources"] = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in (("old", args.old), ("new", args.new))}
    args.out.write_text(json.dumps({"diff": result, "old": old, "new": new}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"coded_accounts": result["coded_accounts"], "added": len(result["added"]), "removed": len(result["removed"]),
                      "changed": len(result["changed"]), "uncoded": {k: v if isinstance(v, int) else len(v) for k, v in result["uncoded"].items()},
                      "subaccounts": {k: v if isinstance(v, int) else len(v) for k, v in result["subaccounts"].items()},
                      "duplicate_enabled_names": {k: len(v) for k, v in result["duplicate_enabled_names"].items()}}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
