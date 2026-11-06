from __future__ import annotations

import hashlib

from accounting_converter.profiles.jdl_official import JDL_DESCRIPTION_CHAR_LIMIT, jdl_description_fits

JDL_DESCRIPTION_LIMIT = JDL_DESCRIPTION_CHAR_LIMIT


def description_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def has_control_character(value: str) -> bool:
    """CR/LF/tab etc. cannot be kept inside one JDL CSV description field."""
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)


def replacement_is_valid(value: str) -> bool:
    if not value or not jdl_description_fits(value):
        return False
    if has_control_character(value):
        return False
    try:
        value.encode("cp932", errors="strict")
    except UnicodeEncodeError:
        return False
    return True
