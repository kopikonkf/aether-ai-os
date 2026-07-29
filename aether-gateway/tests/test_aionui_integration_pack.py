from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "aionui-integration"


def test_aionui_pack_has_native_renderer_main_and_ipc_boundaries():
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["authority"] == "operator-shell-only"
    assert manifest["security"]["renderer_receives_operator_token"] is False
    assert manifest["security"]["renderer_may_approve_actions"] is False
    assert manifest["security"]["mission_plan_approval_does_not_approve_step_actions"] is True

    renderer = (PACK / "packages/desktop/src/renderer/pages/runtime-operations/index.tsx").read_text(encoding="utf-8")
    hook = (PACK / "packages/desktop/src/renderer/pages/runtime-operations/useAetherFleet.ts").read_text(encoding="utf-8")
    service = (PACK / "packages/desktop/src/process/services/aetherFleet/AetherFleetService.ts").read_text(encoding="utf-8")
    bridge = (PACK / "packages/desktop/src/process/bridge/aetherFleetBridge.ts").read_text(encoding="utf-8")

    assert "@arco-design/web-react" in renderer
    assert "@icon-park/react" in renderer
    assert "window.aetherFleet" in hook
    assert "X-Aether-Operator-Token" not in renderer + hook
    assert "operatorToken" in service
    assert "X-Aether-Operator-Token" in service
    assert "ipcMain.handle" in bridge
    assert "shell=True" not in service + bridge + renderer + hook

    mission_renderer = (PACK / "packages/desktop/src/renderer/pages/mission-operations/index.tsx").read_text(encoding="utf-8")
    mission_hook = (PACK / "packages/desktop/src/renderer/pages/mission-operations/useAetherMissions.ts").read_text(encoding="utf-8")
    mission_service = (PACK / "packages/desktop/src/process/services/aetherMission/AetherMissionService.ts").read_text(encoding="utf-8")
    mission_bridge = (PACK / "packages/desktop/src/process/bridge/aetherMissionBridge.ts").read_text(encoding="utf-8")
    assert "@arco-design/web-react" in mission_renderer
    assert "@icon-park/react" in mission_renderer
    assert "window.aetherMission" in mission_hook
    assert "X-Aether-Operator-Token" not in mission_renderer + mission_hook
    assert "operatorToken" in mission_service
    assert "X-Aether-Operator-Token" in mission_service
    assert "ipcMain.handle" in mission_bridge
    assert "aether:mission" in mission_bridge


def test_installer_validates_aionui_v2_and_never_rewrites_shared_bootstrap(tmp_path: Path):
    checkout = tmp_path / "AionUi"
    checkout.mkdir()
    (checkout / "package.json").write_text(
        json.dumps({"name": "AionUi", "version": "2.1.41"}),
        encoding="utf-8",
    )
    installer = PACK / "scripts/install_aionui_integration.py"
    completed = subprocess.run(
        [sys.executable, str(installer), str(checkout)],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["status"] == "installed"
    assert (checkout / "packages/desktop/src/process/bridge/aetherFleetBridge.ts").is_file()
    assert (checkout / "packages/desktop/src/renderer/pages/runtime-operations/index.tsx").is_file()
    assert (checkout / "packages/desktop/src/process/bridge/aetherMissionBridge.ts").is_file()
    assert (checkout / "packages/desktop/src/renderer/pages/mission-operations/index.tsx").is_file()
    assert (checkout / "AETHER_AIONUI_WIRING.md").is_file()
    assert not (checkout / "packages/desktop/src/preload.ts").exists()

    duplicate = subprocess.run(
        [sys.executable, str(installer), str(checkout)],
        text=True,
        capture_output=True,
    )
    assert duplicate.returncode != 0
    assert "Refusing to overwrite" in duplicate.stderr


def test_installer_can_wire_known_unified_senses_route(tmp_path: Path):
    checkout = tmp_path / "AionUi"
    router = checkout / "packages/desktop/src/renderer/components/layout/Router.tsx"
    router.parent.mkdir(parents=True)
    (checkout / "package.json").write_text(json.dumps({"name": "AionUi", "version": "2.1.41"}), encoding="utf-8")
    router.write_text(
        "import React from 'react';\n"
        "const ScheduledTasksPage = React.lazy(() => import('@renderer/pages/cron/ScheduledTasksPage'));\n"
        "export const routes = <>\n"
        "          <Route path='/scheduled' element={withRouteFallback(ScheduledTasksPage)} />\n"
        "</>;\n",
        encoding="utf-8",
    )
    installer = PACK / "scripts/install_aionui_integration.py"
    completed = subprocess.run(
        [sys.executable, str(installer), str(checkout), "--wire-router"],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    patched = router.read_text(encoding="utf-8")
    assert payload["router"]["changed"] is True
    assert "@renderer/pages/unified-senses" in patched
    assert "path='/senses'" in patched
    assert (checkout / "packages/desktop/src/renderer/pages/unified-senses/index.tsx").is_file()
