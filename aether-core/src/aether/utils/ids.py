from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    clean = prefix.strip().replace(" ", "_").lower()
    return f"{clean}.{uuid.uuid4().hex[:16]}"
