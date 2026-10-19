from __future__ import annotations

import hashlib
import uuid


MAX_REVISION_PROFILE_ID_LENGTH = 96


def revised_profile_id(current_profile_id: str, operation: str) -> str:
    """Create a bounded, unique ID while retaining privacy-safe lineage."""
    if not operation or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in operation
    ):
        raise ValueError("profile revision operation is invalid")
    lineage = hashlib.sha256(current_profile_id.encode("utf-8")).hexdigest()[:12]
    result = f"profile-{operation}-{lineage}-{uuid.uuid4().hex}"
    if len(result) > MAX_REVISION_PROFILE_ID_LENGTH:
        raise ValueError("profile revision ID is too long")
    return result
