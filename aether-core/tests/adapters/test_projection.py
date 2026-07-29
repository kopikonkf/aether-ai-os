from pathlib import Path
from aether.adapters.projection import project_soul, project_memory


def test_project_soul_writes_file(tmp_path: Path):
    out = project_soul(tmp_path)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Aether" in text or "Aether" in text or "Genome" in text
    assert "DO NOT EDIT" in text


def test_project_memory_operational_only(tmp_path: Path):
    out = project_memory(tmp_path, facts=["cwd is /app", "telegram allowed"])
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "cwd is /app" in text
    assert "BELIEF" not in text.upper() or "no beliefs" in text.lower()
