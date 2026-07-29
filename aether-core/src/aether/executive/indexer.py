from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.jsonio import read_jsonl, write_json
from aether.obsidian import build_vault_index
from aether.utils.time import utc_now
from aether.executive.workspace import ensure_executive_workspace, decisions_path, heartbeats_path, runs_path, executive_index_path


def build_executive_index(root: Path, write: bool = True) -> dict[str, Any]:
    ensure_executive_workspace(root)
    decisions = read_jsonl(decisions_path(root))
    runs = read_jsonl(runs_path(root))
    heartbeats = read_jsonl(heartbeats_path(root))
    by_type: dict[str, int] = {}
    by_initiative: dict[str, int] = {}
    for decision in decisions:
        dtype = decision.get('decision_type', 'unknown')
        by_type[dtype] = by_type.get(dtype, 0) + 1
        iid = decision.get('initiative_id') or 'none'
        by_initiative[iid] = by_initiative.get(iid, 0) + 1
    index = {
        'generated_at': utc_now(),
        'decision_count': len(decisions),
        'run_count': len(runs),
        'heartbeat_count': len(heartbeats),
        'decisions_by_type': by_type,
        'decisions_by_initiative': by_initiative,
        'latest_decision': decisions[-1] if decisions else None,
        'latest_run': runs[-1] if runs else None,
        'latest_heartbeat': heartbeats[-1] if heartbeats else None,
        'decisions': decisions,
        'runs': runs,
        'heartbeats': heartbeats,
    }
    if write:
        write_json(executive_index_path(root), index)
        write_json(root / 'runtime_state' / 'executive' / 'indexes' / 'decisions.json', decisions)
        write_json(root / 'runtime_state' / 'executive' / 'indexes' / 'runs.json', runs)
        target = root / 'obsidian' / 'vault' / '00_System' / 'indexes' / 'Executive_Index.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_index_md(index), encoding='utf-8')
        write_json(root / 'runtime_state' / 'reports' / 'executive_index_latest.json', index)
        build_vault_index(root, write=True)
    return index


def _index_md(index: dict[str, Any]) -> str:
    lines = [
        '# Executive Index',
        '',
        f"Generated: {index['generated_at']}",
        f"Decisions: {index['decision_count']}",
        f"Runs: {index['run_count']}",
        f"Heartbeats: {index['heartbeat_count']}",
        '',
        '## Decisions by Type',
    ]
    for dtype, count in sorted(index['decisions_by_type'].items()):
        lines.append(f'- {dtype}: {count}')
    latest = index.get('latest_decision') or {}
    if latest:
        lines.extend(['', '## Latest Decision', f"- {latest.get('decision_type')} — {latest.get('initiative_id') or 'none'} / {latest.get('task_id') or 'none'}"])
    return '\n'.join(lines) + '\n'


def executive_status(root: Path) -> dict[str, Any]:
    index = build_executive_index(root, write=True)
    return {
        'ok': True,
        'decision_count': index['decision_count'],
        'run_count': index['run_count'],
        'heartbeat_count': index['heartbeat_count'],
        'latest_decision': index['latest_decision'],
        'index_exists': executive_index_path(root).exists(),
    }


def validate_executive_workspace(root: Path) -> dict[str, Any]:
    status = executive_status(root)
    errors = []
    required = [
        root / 'runtime_state' / 'executive',
        root / 'runtime_state' / 'executive' / 'index.json',
        root / 'obsidian' / 'vault' / '09_Decisions',
        root / 'obsidian' / 'vault' / '10_Reports',
        root / 'obsidian' / 'vault' / '00_System' / 'indexes' / 'Executive_Index.md',
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing: {path.relative_to(root).as_posix()}")
    for decision in read_jsonl(decisions_path(root)):
        if decision.get('decision_type') != 'no_action' and not decision.get('rationale'):
            errors.append(f"decision without rationale: {decision.get('decision_id')}")
    status['errors'] = errors
    status['ok'] = not errors
    return status
