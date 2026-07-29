from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "aionui-integration"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_gateway_routes_use_shared_hash_bound_approval_service() -> None:
    server = read("aether-gateway/src/aether_gateway/api/server.py")

    assert "ApprovalCoordinator, ApprovalInboxService" in server
    assert "approval_inbox = ApprovalInboxService(approval_coordinator)" in server
    assert "return approval_inbox.status_counts()" in server
    assert "outcome = await approval_inbox.decide(" in server
    assert "expected_action_hash=req.expected_action_hash" in server
    assert "except (ApprovalStateError, ValueError)" in server


def test_aionui_approval_pack_files_and_security_manifest() -> None:
    required = [
        "aionui-integration/packages/desktop/src/common/aetherApprovalTypes.ts",
        "aionui-integration/packages/desktop/src/process/services/aetherApproval/AetherApprovalService.ts",
        "aionui-integration/packages/desktop/src/process/bridge/aetherApprovalBridge.ts",
        "aionui-integration/packages/desktop/src/renderer/pages/approval-inbox/index.tsx",
        "aionui-integration/packages/desktop/src/renderer/pages/approval-inbox/useAetherApprovals.ts",
        "aionui-integration/packages/desktop/src/renderer/pages/approval-inbox/ApprovalInbox.module.css",
        "aionui-integration/integration-snippets/approval-preload.ts.txt",
        "aionui-integration/integration-snippets/approval-bridge-registration.ts.txt",
        "aionui-integration/integration-snippets/approval-route.tsx.txt",
        "aionui-integration/integration-snippets/approval-sidebar.tsx.txt",
        "project-docs/aionui/NATIVE_APPROVAL_INBOX_INTEGRATION.md",
    ]
    assert all((ROOT / path).is_file() for path in required)

    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    feature = manifest["features"]["generic_approval_inbox"]
    security = manifest["security"]
    assert feature["ipc_prefix"] == "aether:approval"
    assert feature["aionui_route"] == "/#/approvals"
    assert security["operator_token_owner"] == "AionUi main process"
    assert security["renderer_receives_operator_token"] is False
    assert security["renderer_may_approve_actions"] is False
    assert security["renderer_may_request_approval_decisions"] is True
    assert security["renderer_receives_raw_action_arguments"] is False
    assert security["approval_decisions_require_expected_action_hash"] is True


def test_main_process_sanitizes_before_renderer_projection() -> None:
    service = read(
        "aionui-integration/packages/desktop/src/process/services/aetherApproval/AetherApprovalService.ts"
    )
    types = read("aionui-integration/packages/desktop/src/common/aetherApprovalTypes.ts")

    assert "private readonly operatorToken" in service
    assert "X-Aether-Operator-Token" in service
    assert "expected_action_hash: expectedActionHash" in service
    assert "argument_keys: Object.keys(argumentsRecord)" in service
    assert "target_hint: safeTargetHint(argumentsValue)" in service
    assert "raw_action_arguments_in_renderer: false" in service
    assert "secret_values_exposed: false" in service
    assert "resultRaw.output" not in service
    assert "arguments: Record" not in types
    assert "argument_keys: string[]" in types
    assert "operatorToken" not in types
    assert "X-Aether-Operator-Token" not in types


def test_renderer_has_explicit_hash_bound_decision_flow_without_token() -> None:
    page = read("aionui-integration/packages/desktop/src/renderer/pages/approval-inbox/index.tsx")
    hook = read("aionui-integration/packages/desktop/src/renderer/pages/approval-inbox/useAetherApprovals.ts")
    preload = read("aionui-integration/integration-snippets/approval-preload.ts.txt")

    assert "Exact action SHA-256" in page
    assert "Approve exact action" in page
    assert "Decision reason" in page
    assert "selected.action_hash" in page
    assert "approval.action_hash" in hook
    assert "expectedActionHash" in preload
    assert "AETHER_OPERATOR_TOKEN" not in page
    assert "AETHER_OPERATOR_TOKEN" not in hook
    assert "raw action body" in page


def test_installer_checklist_requires_target_checkout_conformance() -> None:
    installer = read("aionui-integration/scripts/install_aionui_integration.py")
    readme = read("aionui-integration/README.md")

    assert "Register AetherApprovalService/bridge" in installer
    assert "receives no raw action arguments" in installer
    assert "bun run lint" in readme
    assert "bun run test" in readme
    assert "does not contain the complete upstream AionUi dependency tree" in readme


def test_installer_copies_approval_inbox_into_bounded_aionui_checkout(tmp_path: Path) -> None:
    target = tmp_path / "AionUi"
    router = target / "packages/desktop/src/renderer/components/layout/Router.tsx"
    router.parent.mkdir(parents=True)
    (target / "package.json").write_text(
        json.dumps({"name": "aionui", "version": "2.9.0"}), encoding="utf-8"
    )
    router.write_text(
        "const ScheduledTasksPage = React.lazy(() => import('@renderer/pages/cron/ScheduledTasksPage'));\n"
        "          <Route path='/scheduled' element={withRouteFallback(ScheduledTasksPage)} />\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(PACK / "scripts/install_aionui_integration.py"),
            str(target),
            "--wire-router",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["status"] == "installed"
    assert (target / "packages/desktop/src/renderer/pages/approval-inbox/index.tsx").is_file()
    assert (target / "packages/desktop/src/process/services/aetherApproval/AetherApprovalService.ts").is_file()
    checklist = (target / "AETHER_AIONUI_WIRING.md").read_text(encoding="utf-8")
    assert "Approval Inbox" in checklist
    assert "receives no raw action arguments" in checklist
