from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from aether.utils.jsonio import write_json
from aether.obsidian.frontmatter import parse_frontmatter
from aether.obsidian.workspace import ensure_vault, vault_path
from aether.utils.time import utc_now

WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
HASH_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_\-/]+)")


def _extract_links(body: str) -> list[str]:
    links = []
    for match in WIKI_LINK_RE.findall(body):
        links.append(match.split("|")[0].strip())
    return sorted(set(links))


def _extract_tags(meta: dict[str, Any], body: str) -> list[str]:
    tags = set()
    raw = meta.get("tags", [])
    if isinstance(raw, str):
        tags.add(raw)
    elif isinstance(raw, list):
        for item in raw:
            tags.add(str(item))
    for tag in HASH_TAG_RE.findall(body):
        tags.add(tag)
    return sorted(t.strip().lstrip("#") for t in tags if str(t).strip())


def build_vault_index(root: Path, write: bool = True) -> dict[str, Any]:
    ensure_vault(root)
    vault = vault_path(root)
    notes = []
    tag_index: dict[str, list[str]] = {}
    link_edges = []
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault).as_posix()
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        links = _extract_links(body)
        tags = _extract_tags(meta, body)
        note = {
            "path": rel,
            "title": meta.get("title") or path.stem,
            "id": meta.get("id"),
            "type": meta.get("type"),
            "status": meta.get("status"),
            "tags": tags,
            "links": links,
        }
        notes.append(note)
        for tag in tags:
            tag_index.setdefault(tag, []).append(rel)
        for link in links:
            link_edges.append({"from": rel, "to": link})

    index = {
        "generated_at": utc_now(),
        "vault_path": vault.relative_to(root).as_posix(),
        "note_count": len(notes),
        "notes": notes,
        "tags": tag_index,
        "links": link_edges,
    }

    if write:
        index_dir = vault / "00_System" / "indexes"
        index_dir.mkdir(parents=True, exist_ok=True)
        write_json(index_dir / "vault_index.json", index)
        write_json(index_dir / "tag_index.json", tag_index)
        write_json(index_dir / "link_graph.json", link_edges)
        (index_dir / "Vault_Index.md").write_text(_vault_index_md(index), encoding="utf-8")
        (index_dir / "Tag_Index.md").write_text(_tag_index_md(tag_index), encoding="utf-8")
        (index_dir / "Link_Graph.md").write_text(_link_graph_md(link_edges), encoding="utf-8")
        write_json(root / "runtime_state" / "reports" / "obsidian_index_latest.json", index)
    return index


def _vault_index_md(index: dict[str, Any]) -> str:
    lines = ["# Vault Index", "", f"Generated: {index['generated_at']}", "", "## Notes"]
    for note in index["notes"]:
        lines.append(f"- `{note['path']}` - {note.get('type') or 'unknown'} - {note.get('title')}")
    return "\n".join(lines) + "\n"


def _tag_index_md(tags: dict[str, list[str]]) -> str:
    lines = ["# Tag Index", ""]
    for tag, paths in sorted(tags.items()):
        lines.append(f"## #{tag}")
        for path in paths:
            lines.append(f"- `{path}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def _link_graph_md(edges: list[dict[str, str]]) -> str:
    lines = ["# Link Graph", ""]
    for edge in edges:
        lines.append(f"- `{edge['from']}` -> `[[{edge['to']}]]`")
    return "\n".join(lines) + "\n"


def validate_vault(root: Path) -> dict[str, Any]:
    index = build_vault_index(root, write=True)
    errors = []
    for note in index["notes"]:
        path = note["path"]
        if path.startswith("00_System/indexes/"):
            continue
        if path.endswith("/README.md") or path == "README.md":
            continue
        if path == "00_System/SNIPER_Workspace_Index.md":
            continue
        if note.get("type") is None:
            errors.append(f"missing type: {note['path']}")
        if note.get("id") is None:
            errors.append(f"missing id: {note['path']}")
    return {"ok": not errors, "note_count": index["note_count"], "errors": errors, "index_path": "obsidian/vault/00_System/indexes/vault_index.json"}
