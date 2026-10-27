from __future__ import annotations

import hashlib


JDL_DESCRIPTION_LIMIT = 32


def description_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def replacement_is_valid(value: str) -> bool:
    if not 1 <= len(value) <= JDL_DESCRIPTION_LIMIT:
        return False
    try:
        value.encode("cp932", errors="strict")
    except UnicodeEncodeError:
        return False
    return True
