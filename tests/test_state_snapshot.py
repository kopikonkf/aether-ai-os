from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "aether_home_snapshot",
    ROOT / "scripts" / "aether_home_snapshot.py",
)
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


class SnapshotWindowsPortabilityTests(unittest.TestCase):
    def test_sqlite_check_closes_read_connection(self) -> None:
        class FakeCursor:
            def fetchone(self):
                return ("ok",)

        class FakeConnection:
            def __init__(self) -> None:
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, statement: str) -> FakeCursor:
                self.statement = statement
                return FakeCursor()

            def close(self) -> None:
                self.closed = True

        connection = FakeConnection()
        with mock.patch.object(module.sqlite3, "connect", return_value=connection):
            self.assertEqual(module.sqlite_check(Path("state.sqlite3")), "ok")

        self.assertTrue(connection.closed)

    def test_sqlite_backup_closes_connections_before_returning(self) -> None:
        class FakeConnection:
            def __init__(self) -> None:
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def backup(self, destination) -> None:
                self.destination = destination

            def execute(self, statement: str) -> None:
                self.statement = statement

            def close(self) -> None:
                self.closed = True

        source_connection = FakeConnection()
        destination_connection = FakeConnection()
        connections = iter((source_connection, destination_connection))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "snapshot.sqlite3"
            with (
                mock.patch.object(module, "sqlite_check", return_value="ok"),
                mock.patch.object(
                    module.sqlite3,
                    "connect",
                    side_effect=lambda *args, **kwargs: next(connections),
                ),
            ):
                module.backup_sqlite(Path(directory) / "source.sqlite3", destination)

        self.assertTrue(source_connection.closed)
        self.assertTrue(destination_connection.closed)

    def test_sqlite_backup_closes_connections_after_backup_failure(self) -> None:
        class FakeConnection:
            def __init__(self, *, fail_backup: bool = False) -> None:
                self.closed = False
                self.fail_backup = fail_backup

            def backup(self, destination) -> None:
                if self.fail_backup:
                    raise sqlite3.OperationalError("simulated backup failure")

            def execute(self, statement: str) -> None:
                self.statement = statement

            def close(self) -> None:
                self.closed = True

        source_connection = FakeConnection(fail_backup=True)
        destination_connection = FakeConnection()
        connections = iter((source_connection, destination_connection))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "snapshot.sqlite3"
            with (
                mock.patch.object(module, "sqlite_check", return_value="ok"),
                mock.patch.object(
                    module.sqlite3,
                    "connect",
                    side_effect=lambda *args, **kwargs: next(connections),
                ),
            ):
                with self.assertRaisesRegex(sqlite3.OperationalError, "simulated backup failure"):
                    module.backup_sqlite(Path(directory) / "source.sqlite3", destination)

        self.assertTrue(source_connection.closed)
        self.assertTrue(destination_connection.closed)

    def test_export_retries_transient_windows_publish_denial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "proof.txt").write_text("proof", encoding="utf-8")
            output = root / "snapshot"
            real_replace = module.os.replace
            attempts = 0

            def flaky_replace(source_path, destination_path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("simulated transient Windows lock")
                real_replace(source_path, destination_path)

            with (
                mock.patch.object(module, "_is_windows", return_value=True),
                mock.patch.object(module.os, "replace", side_effect=flaky_replace),
                mock.patch.object(module.time, "sleep", return_value=None),
            ):
                result = module.export_snapshot(source, output)

            self.assertEqual(attempts, 3)
            self.assertEqual(result["publish_method"], "replace")
            self.assertEqual(result["publish_attempts"], 3)
            self.assertEqual(module.verify_snapshot(output)["status"], "ok")

    def test_export_falls_back_to_verified_copy_after_windows_denials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "proof.txt").write_text("proof", encoding="utf-8")
            database = source / "memory" / "canonical.sqlite3"
            database.parent.mkdir()
            with sqlite3.connect(database) as connection:
                connection.execute("create table proof(value text)")
                connection.execute("insert into proof values ('aether')")
            output = root / "snapshot"

            with (
                mock.patch.object(module, "_is_windows", return_value=True),
                mock.patch.object(
                    module.os,
                    "replace",
                    side_effect=PermissionError("simulated persistent Windows lock"),
                ),
                mock.patch.object(module.time, "sleep", return_value=None),
            ):
                result = module.export_snapshot(source, output)

            self.assertEqual(result["publish_method"], "verified-copy")
            self.assertEqual(
                result["publish_attempts"],
                module.WINDOWS_PUBLISH_RETRY_ATTEMPTS,
            )
            self.assertEqual(module.verify_snapshot(output)["status"], "ok")
            with sqlite3.connect(
                output / "memory" / "canonical.sqlite3"
            ) as connection:
                self.assertEqual(
                    connection.execute("select value from proof").fetchone(),
                    ("aether",),
                )
            self.assertEqual(list(root.glob(".snapshot.*")), [])

    def test_export_rejects_corrupt_windows_fallback_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "proof.txt").write_text("proof", encoding="utf-8")
            output = root / "snapshot"
            real_copytree = module.shutil.copytree

            def corrupt_copy(source_path, destination_path, **kwargs):
                result = real_copytree(source_path, destination_path, **kwargs)
                (Path(destination_path) / "proof.txt").write_text(
                    "corrupt",
                    encoding="utf-8",
                )
                return result

            with (
                mock.patch.object(module, "_is_windows", return_value=True),
                mock.patch.object(
                    module.os,
                    "replace",
                    side_effect=PermissionError("simulated persistent Windows lock"),
                ),
                mock.patch.object(module.shutil, "copytree", side_effect=corrupt_copy),
                mock.patch.object(module.time, "sleep", return_value=None),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "fallback snapshot verification failed",
                ):
                    module.export_snapshot(source, output)

            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".snapshot.*")), [])

    def test_export_does_not_fallback_for_non_windows_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "proof.txt").write_text("proof", encoding="utf-8")
            output = root / "snapshot"

            with (
                mock.patch.object(module, "_is_windows", return_value=False),
                mock.patch.object(
                    module.os,
                    "replace",
                    side_effect=PermissionError("simulated permission error"),
                ),
            ):
                with self.assertRaisesRegex(PermissionError, "simulated permission error"):
                    module.export_snapshot(source, output)

            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".snapshot.*")), [])


if __name__ == "__main__":
    unittest.main()
