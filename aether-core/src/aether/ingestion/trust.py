from __future__ import annotations

BASE_TRUST = {
    "manual": 0.70,
    "local_file": 0.60,
    "markdown": 0.62,
    "json": 0.55,
    "csv": 0.50,
    "html": 0.45,
    "url_placeholder": 0.25,
    "unknown": 0.30,
}


def trust_score(source_type: str, char_count: int = 0, claim_count: int = 0) -> float:
    base = BASE_TRUST.get(source_type, BASE_TRUST["unknown"])
    if char_count > 2000:
        base += 0.03
    if claim_count:
        base += min(0.05, claim_count * 0.005)
    return round(max(0.0, min(1.0, base)), 4)
