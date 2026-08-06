import json

from aether.runtime.founder_acceptance import FounderAcceptance
from aether.runtime.ingress import AetherCloudflareIngress, REQUIRED_CLOUDFLARE_ROUTES
from aether.runtime.mvp20 import AetherMvp20Release


def ok_probe():
    return {
        "base_url": "https://aether.example.com",
        "cloudflare_tunnel": True,
        "cloudflared_service_status": "Running",
        "routes": [
            {"path": path, "status_code": 200, "ok": True, "latency_ms": 12.0}
            for path in REQUIRED_CLOUDFLARE_ROUTES
        ],
    }


def test_cloudflare_ingress_record_writes_latest_and_log(tmp_path):
    ingress = AetherCloudflareIngress(tmp_path)
    record = ingress.record_probe(ok_probe())

    assert record["schema"] == "aether.cloudflare-ingress.v1"
    assert record["status"] == "ok"
    assert record["secret_values_exposed"] is False

    latest = json.loads((tmp_path / "runtime" / "ingress" / "latest_cloudflare_probe.json").read_text())
    assert latest["status"] == "ok"
    assert "cloudflare.ingress.probed" in (tmp_path / "runtime" / "ingress" / "cloudflare-probes.jsonl").read_text()


def test_founder_acceptance_reads_cloudflare_receipt_as_public_probe(tmp_path):
    AetherCloudflareIngress(tmp_path).record_probe(ok_probe())
    packet = FounderAcceptance(tmp_path).build_packet()

    statuses = {item["id"]: item["status"] for item in packet["criteria"]}
    assert statuses["public_host_probe"] == "pass"


def test_mvp20_reads_cloudflare_receipt_as_optional_probe(tmp_path):
    AetherCloudflareIngress(tmp_path).record_probe(ok_probe())
    packet = AetherMvp20Release(tmp_path).build_packet(persist=False)

    statuses = {item["id"]: item["status"] for item in packet["criteria"]}
    assert statuses["public_host_probe"] == "pass"
