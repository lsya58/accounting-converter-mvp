from __future__ import annotations

import hashlib
import json


def observed_master_identity_sha256(observation) -> str:
    accounts = (
        (item.code, item.name, item.abbreviation)
        for item in observation.printed_accounts
        if item.enabled
    )
    subaccounts = (
        (
            item.parent_account_code,
            item.parent_account_name,
            item.code,
            item.name,
        )
        for item in observation.subaccounts
    )
    return _master_identity_sha256(accounts, subaccounts)


def target_context_master_identity_sha256(context) -> str:
    accounts = (
        (item.target_master_code, item.target_formal_name, item.target_name)
        for item in context.account_master
    )
    subaccounts = (
        (
            item.parent_account_code,
            item.parent_account,
            item.target_master_code,
            item.target_name or item.output_name,
        )
        for item in context.subaccounts
    )
    return _master_identity_sha256(accounts, subaccounts)


def _master_identity_sha256(accounts, subaccounts) -> str:
    payload = {
        "accounts": sorted(tuple(item) for item in accounts),
        "subaccounts": sorted(tuple(item) for item in subaccounts),
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
