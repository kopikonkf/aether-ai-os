# Aether Coding JSONL Protocol v1

Protocol identifier:

```text
aether.coding-jsonl.v1
```

## Handshake

Aether invokes the configured argv with:

```text
--aether-handshake
```

The runtime must print exactly one JSON object and exit successfully:

```json
{
  "protocol": "aether.coding-jsonl.v1",
  "runtime": {
    "id": "vendor.runtime-id",
    "version": "1.0.0",
    "display_name": "Runtime Name",
    "operations": ["coding.task.execute"],
    "capabilities": ["coding.edit", "coding.verify"],
    "features": ["external-cli", "jsonl-stream-v1"]
  },
  "limits": {
    "max_frame_bytes": 65536,
    "max_patch_files": 10
  }
}
```

The handshake is capability and version discovery only. It does not grant workspace or action authority.

## Task execution

Aether invokes the same argv with:

```text
--aether-run
```

A single `task.start` JSON object is written to stdin. The workspace path points to a staging copy, never the canonical production root.

The runtime emits one JSON object per stdout line. Every frame must contain:

```text
type
protocol
task_id
sequence
payload
```

Sequence values must be strictly increasing.

Allowed frame types:

```text
task.accepted
task.progress
task.log
artifact.patch
task.completed
task.error
```

## Patch frame

```json
{
  "type": "artifact.patch",
  "protocol": "aether.coding-jsonl.v1",
  "task_id": "coding-task.example",
  "sequence": 3,
  "payload": {
    "path": "src/example.py",
    "kind": "upsert",
    "before_sha256": "...",
    "content": "complete resulting file content",
    "diff": "optional runtime-generated unified diff"
  }
}
```

The runtime-provided diff is informational. Aether computes the authoritative diff from the actual before and after bytes.

## Security and boundedness

Aether rejects:

- unknown frame types;
- malformed JSON;
- protocol or task mismatch;
- out-of-order sequence values;
- frames, stdout, stderr, or frame counts above policy limits;
- absolute paths and traversal;
- duplicate artifact paths;
- files outside the workspace binding allowlist;
- missing or incorrect `before_sha256` for existing files;
- patches without independent verification;
- production files whose hashes changed during runtime execution.

Provider and operator credentials are not inherited by the external process. Process execution uses argv with `shell=false`. Kernel-enforced network or filesystem isolation is not provided in v0.12; production adapters should run inside a stronger sandbox when handling untrusted runtimes.
