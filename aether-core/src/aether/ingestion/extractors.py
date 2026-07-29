from __future__ import annotations

import csv
import json
import re
from html import unescape
from pathlib import Path
from typing import Any

CLAIM_MARKERS = [
    " should ", " must ", " can ", " may ", " will ", " is ", " are ",
    " requires ", " improves ", " causes ", " supports ", " indicates ",
]

TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="replace")


def extract_text_from_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        text = _read_text(path)
        source_type = "markdown" if suffix in {".md", ".markdown"} else "local_file"
    elif suffix == ".json":
        data = json.loads(_read_text(path))
        text = json.dumps(data, indent=2, ensure_ascii=False)
        source_type = "json"
    elif suffix == ".csv":
        rows = []
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                rows.append(" | ".join(row))
        text = "\n".join(rows)
        source_type = "csv"
    elif suffix in {".html", ".htm"}:
        raw = _read_text(path)
        text = unescape(TAG_RE.sub(" ", raw))
        text = re.sub(r"\s+", " ", text).strip()
        source_type = "html"
    else:
        text = _read_text(path)
        source_type = "unknown"

    return {
        "text": text.strip(),
        "source_type": source_type,
        "char_count": len(text),
        "line_count": len(text.splitlines()),
    }


def summarize_text(text: str, max_chars: int = 700) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    boundary = cleaned.rfind(".", 0, max_chars)
    if boundary < max_chars // 3:
        boundary = max_chars
    return cleaned[:boundary].strip() + "..."


def extract_claims(text: str, max_claims: int = 20) -> list[str]:
    candidates: list[str] = []
    for part in SENTENCE_RE.split(text):
        sentence = re.sub(r"\s+", " ", part).strip(" -\t\r\n")
        if not sentence:
            continue
        if len(sentence) < 24 or len(sentence) > 400:
            continue
        lowered = " " + sentence.lower() + " "
        if any(marker in lowered for marker in CLAIM_MARKERS) or sentence.startswith(("- ", "* ")):
            candidates.append(sentence.rstrip(".") + ".")

    deduped = []
    seen = set()
    for claim in candidates:
        key = claim.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
        if len(deduped) >= max_claims:
            break
    return deduped
