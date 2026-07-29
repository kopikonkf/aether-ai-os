"""Knowledge ingestion pipeline."""

from .workspace import ensure_ingestion_workspace, manifest_path, inbox_dir, processed_dir, rejected_dir, archive_dir
from .extractors import extract_text_from_file, extract_claims, summarize_text
from .pipeline import ingest_file, ingest_text, register_url, process_inbox
from .indexer import build_ingestion_index, ingestion_status, validate_ingestion_workspace
from .trust import trust_score

__all__ = [
    "ensure_ingestion_workspace",
    "manifest_path",
    "inbox_dir",
    "processed_dir",
    "rejected_dir",
    "archive_dir",
    "extract_text_from_file",
    "extract_claims",
    "summarize_text",
    "ingest_file",
    "ingest_text",
    "register_url",
    "process_inbox",
    "build_ingestion_index",
    "ingestion_status",
    "validate_ingestion_workspace",
    "trust_score",
]
