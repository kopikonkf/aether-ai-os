from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.ids import new_id
from aether.obsidian.frontmatter import apply_frontmatter
from aether.obsidian.slug import slugify
from aether.obsidian.workspace import ensure_vault, vault_path
from aether.utils.time import utc_now

TYPE_FOLDERS = {
    "objective": "01_Objectives",
    "project": "02_Projects",
    "source": "03_Sources",
    "digest": "04_Digests",
    "knowledge": "05_Knowledge",
    "belief": "06_Beliefs",
    "experiment": "07_Experiments",
    "reflection": "08_Reflections",
    "diary": "08_Reflections/Daily",
    "decision": "09_Decisions",
    "report": "10_Reports",
}


def default_folder(note_type: str) -> str:
    return TYPE_FOLDERS.get(note_type, "05_Knowledge")


def note_path(root: Path, note_type: str, title: str, folder: str | None = None) -> Path:
    vault = vault_path(root)
    folder_rel = folder or default_folder(note_type)
    return vault / folder_rel / f"{slugify(title)}.md"


def write_note(
    root: Path,
    note_type: str,
    title: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    folder: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    ensure_vault(root)
    path = note_path(root, note_type, title, folder=folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Note already exists: {path}")
    now = utc_now()
    meta = {
        "id": new_id(note_type),
        "type": note_type,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "tags": [f"aether/{note_type}"],
    }
    if metadata:
        meta.update(metadata)
    path.write_text(apply_frontmatter(meta, body), encoding="utf-8")
    return {"ok": True, "path": path.relative_to(root).as_posix(), "metadata": meta}
