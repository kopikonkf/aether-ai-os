from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.jsonio import write_json
from aether.utils.time import utc_now

VAULT_REL = Path("obsidian") / "vault"
FOLDERS = [
    "00_System",
    "00_System/indexes",
    "01_Objectives",
    "02_Projects",
    "03_Sources",
    "04_Digests",
    "05_Knowledge",
    "06_Beliefs",
    "07_Experiments",
    "08_Reflections",
    "08_Reflections/Daily",
    "09_Decisions",
    "10_Reports",
    "90_Archive",
]


def vault_path(root: Path) -> Path:
    return root / VAULT_REL


def ensure_vault(root: Path) -> dict[str, Any]:
    vault = vault_path(root)
    created = []
    for rel in FOLDERS:
        path = vault / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(path.relative_to(root).as_posix())

    system_index = vault / "00_System" / "Aether_Workspace_Index.md"
    if not system_index.exists():
        system_index.write_text(
            "# Aether Workspace Index\n\n"
            "This vault is the human-readable cognitive workspace for Aether.\n\n"
            "## Core Indexes\n"
            "- [[indexes/Vault_Index]]\n"
            "- [[indexes/Tag_Index]]\n"
            "- [[indexes/Link_Graph]]\n\n"
            "## Folders\n"
            "- 01_Objectives\n- 02_Projects\n- 03_Sources\n- 04_Digests\n"
            "- 05_Knowledge\n- 06_Beliefs\n- 07_Experiments\n- 08_Reflections\n"
            "- 09_Decisions\n- 10_Reports\n",
            encoding="utf-8",
        )

    report = {"ok": True, "vault_path": vault.relative_to(root).as_posix(), "created_or_confirmed": created, "timestamp": utc_now()}
    write_json(root / "runtime_state" / "reports" / "obsidian_workspace_init.json", report)
    return report
