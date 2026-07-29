from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("aether_home_snapshot", ROOT / "scripts" / "aether_home_snapshot.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_export_and_import_snapshot_excludes_wal_sidecars(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "workspace").mkdir()
    (source / "workspace" / "proof.md").write_text("proof", encoding="utf-8")
    db = source / "memory" / "canonical.sqlite3"
    db.parent.mkdir()
    with sqlite3.connect(db) as conn:
        conn.execute("create table items(value text)")
        conn.execute("insert into items values ('aether')")
    (db.parent / "canonical.sqlite3-wal").write_bytes(b"ignored")

    snapshot = tmp_path / "snapshot"
    result = module.export_snapshot(source, snapshot)
    assert result["databases"] == 1
    assert not (snapshot / "memory" / "canonical.sqlite3-wal").exists()
    assert module.verify_snapshot(snapshot)["status"] == "ok"

    destination = tmp_path / "destination"
    imported = module.import_snapshot(snapshot, destination)
    assert imported["status"] == "imported"
    assert (destination / "workspace" / "proof.md").read_text() == "proof"
    with sqlite3.connect(destination / "memory" / "canonical.sqlite3") as conn:
        assert conn.execute("select value from items").fetchone()[0] == "aether"
