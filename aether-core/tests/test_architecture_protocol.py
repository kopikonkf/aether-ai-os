from __future__ import annotations

import json
from pathlib import Path

from aether.contracts import EventType, RuntimeCommand, RuntimeResult
from aether.dna.loader import DNALoader


def test_identity_is_aether_and_independent():
    identity = DNALoader().load_identity()
    assert identity["identity"]["name"] == "Aether"
    assert identity["identity"]["runtime_independent"] is True
    assert identity["identity"]["provider_independent"] is True
    assert identity["identity"]["memory_independent"] is True


def test_constitution_contains_non_repetition_and_self_chosen_improvement():
    identity = DNALoader().load_identity()
    axioms = {item["id"]: item["statement"] for item in identity["constitutional_axioms"]}
    assert "never repeat the same mistake twice" in axioms["AX1"].lower()
    assert "improve because it chooses to" in axioms["AX2"].lower()


def test_contract_types_are_runtime_neutral():
    command = RuntimeCommand(command="inspect", arguments={"path": "."}, capability="coding")
    result = RuntimeResult(ok=True, output="done")
    assert command.capability == "coding"
    assert result.ok is True
    assert EventType.RUNTIME_COMMAND_REQUESTED == "runtime.command.requested"


def test_prohibited_legacy_identity_is_absent_from_active_source():
    project = Path(__file__).resolve().parents[1]
    prohibited = "her" + "mes"
    checked_suffixes = {".py", ".toml", ".yaml", ".yml", ".json", ".md", ".txt"}
    offenders = []
    for path in project.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in checked_suffixes:
            continue
        if any(part in {".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if prohibited in text:
            offenders.append(str(path.relative_to(project)))
    assert offenders == []


def test_core_does_not_import_tool_implementation_or_parse_tool_tags():
    project = Path(__file__).resolve().parents[1] / "src" / "aether"
    offenders = []
    for path in project.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "aether_tools" in text or "parse_tool_tags" in text or "[TOOL" in text:
            offenders.append(str(path.relative_to(project)))
    assert offenders == []
