import os
from pathlib import Path


def _absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def resolve_path(path: str, roots: list[Path]) -> Path | None:
    """Resolve an absolute or root-relative path without escaping allowed roots."""
    if not str(path or "").strip():
        return None
    candidate_input = Path(path)
    for root in roots:
        root_abs = _absolute(root)

        candidate = _absolute(candidate_input)
        try:
            candidate.relative_to(root_abs)
            return candidate
        except ValueError:
            pass

        # Path joining with an absolute child intentionally returns the child;
        # the relative_to check below still rejects it when it is out of scope.
        joined_abs = _absolute(root_abs / candidate_input)
        try:
            joined_abs.relative_to(root_abs)
            return joined_abs
        except ValueError:
            pass
    return None


def resolve_write_path(path: str, write_roots: list[Path]) -> Path | None:
    return resolve_path(path, write_roots)


def allowed_roots_text(roots: list[Path]) -> str:
    return ", ".join(str(_absolute(root)) for root in roots)
