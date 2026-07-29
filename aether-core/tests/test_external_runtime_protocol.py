from __future__ import annotations

from aether.contracts import (
    AETHER_CODING_STREAM_PROTOCOL,
    ExternalRuntimeHandshake,
    RuntimeStreamFrameType,
)


def test_external_runtime_protocol_contract_is_stable():
    handshake = ExternalRuntimeHandshake(
        protocol=AETHER_CODING_STREAM_PROTOCOL,
        runtime_id="runtime.test",
        runtime_version="1.2.3",
        display_name="Test Runtime",
        operations=("coding.task.execute",),
        capabilities=("coding.edit",),
        runtime_features=("jsonl-stream-v1",),
        max_frame_bytes=65536,
        max_patch_files=10,
    )
    assert handshake.fingerprint() == handshake.fingerprint()
    assert RuntimeStreamFrameType.PATCH.value == "artifact.patch"
    assert AETHER_CODING_STREAM_PROTOCOL == "aether.coding-jsonl.v1"
