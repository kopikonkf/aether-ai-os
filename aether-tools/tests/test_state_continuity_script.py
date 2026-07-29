from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "aether_state_continuity.py"
    spec = importlib.util.spec_from_file_location("aether_state_continuity", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_preservation_is_inert_and_secret_safe(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "legacy"
    home = tmp_path / "aether-home"
    (source / "skills").mkdir(parents=True)
    (source / "obsidian" / "vault").mkdir(parents=True)
    (source / "20_Dee_Workspace").mkdir(parents=True)
    (source / "skills" / "debug.md").write_text("legacy skill", encoding="utf-8")
    (source / "obsidian" / "vault" / "reflection.md").write_text("legacy note", encoding="utf-8")
    (source / "20_Dee_Workspace" / "decision.md").write_text("founder context", encoding="utf-8")
    (source / "API_Keys_Backup.md").write_text("never copy me", encoding="utf-8")
    (source / "hermes_hub.db").write_bytes(b"legacy-db")

    dry_run = module.migrate_legacy(source, home, apply=False)
    assert dry_run["schema"] == "aether.legacy-state-preservation.v2"
    assert dry_run["promotion_boundary"]["automatic_imports_authorized"] == 0
    assert dry_run["quarantined_file_count"] == 1
    assert not home.exists()

    applied = module.migrate_legacy(source, home, apply=True)
    archive_root = Path(applied["archive_root"])
    assert (archive_root / "payload" / "skills" / "debug.md").read_text(encoding="utf-8") == "legacy skill"
    assert (archive_root / "payload" / "obsidian" / "vault" / "reflection.md").is_file()
    assert (archive_root / "payload" / "hermes_hub.db").read_bytes() == b"legacy-db"
    assert not (archive_root / "payload" / "API_Keys_Backup.md").exists()
    assert not (home / "memory").exists()
    assert not (home / "skills" / "skill-factory.sqlite3").exists()
    assert not (home / "obsidian" / "vault").exists()
    manifest_path = Path(applied["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["security"]["archive_indexing_authorized"] is False
    assert manifest["semantic_migration"]["performed"] is False
