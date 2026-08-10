from __future__ import annotations

import os
import pathlib

from aether.paths import load_dotenv_files


class _FakeDotenv:
    """Bound method compatible with load_dotenv(path, override=...)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.vars: dict[str, str] = {}

    def load_dotenv(self, path: str | os.PathLike, *, override: bool = False) -> None:
        p = pathlib.Path(path)
        self.calls.append((str(p), override))
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if override or key not in self.vars:
                self.vars[key] = value


def test_load_dotenv_files_layers_later_overrides_and_skips_missing(tmp_path: pathlib.Path) -> None:
    fake = _FakeDotenv()
    release = tmp_path / "release" / "aether-core"
    home = tmp_path / "aether_home"
    release.mkdir(parents=True)
    home.mkdir(parents=True)
    (release / ".env").write_text("FIRST=from_release\nONLY_RELEASE=yes\n", encoding="utf-8")
    (home / ".env").write_text("FIRST=from_home\n", encoding="utf-8")

    load_dotenv_files(
        fake.load_dotenv,
        [release / ".env", home / ".env", tmp_path / "missing" / ".env"],
        override=True,
    )
    # later file wins per key; missing path skipped
    assert fake.vars["FIRST"] == "from_home"
    assert fake.vars["ONLY_RELEASE"] == "yes"
    loaded = [c[0] for c in fake.calls]
    assert str(release / ".env") in loaded
    assert str(home / ".env") in loaded
    assert not any(c[0].endswith(f"missing{os.sep}.env") for c in fake.calls)
    # override=True so later always applied
    assert all(c[1] is True for c in fake.calls)


def test_load_dotenv_files_none_and_missing_are_noop(tmp_path: pathlib.Path) -> None:
    fake = _FakeDotenv()
    load_dotenv_files(fake.load_dotenv, [None, tmp_path / "no-such-dir" / ".env"], override=False)
    assert fake.calls == []