from importlib.resources import files

import yaml

from aether.contracts import (
    FleetIncidentKind,
    FleetIncidentSeverity,
    RuntimeFleetBudgetPolicy,
    fleet_incident_fingerprint,
)


def test_runtime_fleet_policy_is_packaged_and_bounded():
    path = files("aether.runtimes").joinpath("runtime_fleet_operations.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["policy_id"] == "aether.runtime-fleet-operations.v1"
    assert data["scheduler"]["jobs"]["health-probe"]["interval_seconds"] >= 5
    assert data["fallback"]["maximum_attempts"] == 3
    assert data["receipt_renewal"]["queue_only_by_default"] is True
    assert data["console"]["token_storage"] == "session-only"


def test_budget_policy_and_incident_fingerprint_are_stable():
    policy = RuntimeFleetBudgetPolicy()
    policy.validate()
    a = fleet_incident_fingerprint(
        kind=FleetIncidentKind.QUOTA_EXHAUSTED,
        driver_id="gemini",
        summary="Quota exhausted",
        details={"status": 429},
    )
    b = fleet_incident_fingerprint(
        kind=FleetIncidentKind.QUOTA_EXHAUSTED,
        driver_id="gemini",
        summary="  quota   EXHAUSTED ",
        details={"status": 429},
    )
    assert a == b
    assert FleetIncidentSeverity.CRITICAL.value == "critical"


def test_conformance_signer_is_an_explicit_replaceable_contract():
    from aether.contracts import (
        RuntimeConformanceAttestation,
        RuntimeConformanceCheck,
        RuntimeConformanceReceipt,
        RuntimeConformanceReceiptSigner,
    )

    class FixtureSigner:
        signer_id = "fixture"
        algorithm = "test-only"

        def sign(self, receipt):
            return RuntimeConformanceAttestation(
                receipt_id=receipt.receipt_id,
                receipt_fingerprint=receipt.fingerprint(),
                signer_id=self.signer_id,
                algorithm=self.algorithm,
                key_id="fixture-key",
                signature="fixture-signature",
                issued_at=receipt.issued_at,
            )

        def verify(self, receipt, attestation):
            return attestation.receipt_fingerprint == receipt.fingerprint()

    receipt = RuntimeConformanceReceipt(
        driver_id="fixture",
        manifest_fingerprint="m",
        executable_path="/fixture",
        executable_sha256="e",
        runtime_version="1",
        protocol="aether.coding-jsonl.v1",
        provider_id="fixture",
        model_id="fixture",
        configuration_hash="c",
        suite_hash="s",
        issued_at="2026-07-28T00:00:00+00:00",
        expires_at="2026-07-29T00:00:00+00:00",
        checks=(RuntimeConformanceCheck("fixture", True),),
        issued_by="founder",
    )
    signer = FixtureSigner()
    assert isinstance(signer, RuntimeConformanceReceiptSigner)
    assert signer.verify(receipt, signer.sign(receipt))
