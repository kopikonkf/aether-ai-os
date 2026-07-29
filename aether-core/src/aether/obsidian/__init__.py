"""Obsidian Cognitive Workspace."""

from .workspace import ensure_vault, vault_path
from .notes import write_note
from .diary import create_daily_log
from .digest import write_source_digest, write_belief_note
from .indexer import build_vault_index, validate_vault
from .frontmatter import parse_frontmatter, dump_frontmatter, apply_frontmatter

__all__ = [
    "ensure_vault",
    "vault_path",
    "write_note",
    "create_daily_log",
    "write_source_digest",
    "write_belief_note",
    "build_vault_index",
    "validate_vault",
    "parse_frontmatter",
    "dump_frontmatter",
    "apply_frontmatter",
]
