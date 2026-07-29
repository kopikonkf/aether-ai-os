from __future__ import annotations

import re


def slugify(title: str) -> str:
    text = title.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "untitled"
