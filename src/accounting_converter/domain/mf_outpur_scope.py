from __future__ import annotations


OUTPUR_TAX_MAPPING_EVIDENCE_ID = "EVID-MF-JDL-35-5-OUTPUR-8471-1111-ROUNDTRIP-001"
OUTPUR_SHAPE_EVIDENCE_IDS = {
    (4, 6): "EVID-MF-JDL-35-5-OUTPUR-4D6C-ROUNDTRIP-001",
    (5, 7): "EVID-MF-JDL-35-5-OUTPUR-5D7C-ROUNDTRIP-001",
    (5, 8): "EVID-MF-JDL-35-5-OUTPUR-5D8C-ROUNDTRIP-001",
}


def outpur_signature(shape: tuple[int, int]) -> tuple[tuple[str, str, str, str], ...]:
    """Exact ordered source-tax/target-identity combinations verified in 0875."""
    if shape not in OUTPUR_SHAPE_EVIDENCE_IDS:
        raise ValueError("unsupported outpur compound shape")
    debit_count, credit_count = shape
    subaccount_credits = 3 if shape == (5, 8) else 2
    return (
        ("DEBIT", "8311", "", "対象外仕入"),
        *(("CREDIT", "3271", "0003", "対象外") for _ in range(subaccount_credits)),
        ("CREDIT", "3221", "", "対象外"),
        *(("DEBIT", "8441", "", "対象外") for _ in range(debit_count - 1)),
        *(("CREDIT", "3221", "", "対象外") for _ in range(credit_count - subaccount_credits - 1)),
    )


def outpur_target_signature(shape: tuple[int, int]) -> tuple[tuple[str, str, str], ...]:
    return tuple((side, account, subaccount) for side, account, subaccount, _ in outpur_signature(shape))
