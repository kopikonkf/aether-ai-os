from pathlib import Path


def test_native_experiment_integration_pack_has_bounded_ipc_and_no_renderer_secret():
    root = Path(__file__).resolve().parents[2] / "aionui-integration"
    required = [
        "packages/desktop/src/common/aetherExperimentTypes.ts",
        "packages/desktop/src/process/services/aetherExperiment/AetherExperimentService.ts",
        "packages/desktop/src/process/bridge/aetherExperimentBridge.ts",
        "packages/desktop/src/renderer/pages/live-web-experiments/index.tsx",
        "packages/desktop/src/renderer/pages/live-web-experiments/useAetherExperiments.ts",
        "packages/desktop/src/renderer/pages/live-web-experiments/LiveWebExperiments.module.css",
        "integration-snippets/experiment-preload.ts.txt",
    ]
    for path in required:
        assert (root / path).exists(), path
    service = (root / required[1]).read_text(encoding="utf-8")
    renderer = (root / required[3]).read_text(encoding="utf-8")
    bridge = (root / required[2]).read_text(encoding="utf-8")
    assert "X-Aether-Operator-Token" in service
    assert "operatorToken" not in renderer
    assert bridge.count("ipcMain.handle") == 8
    assert "@arco-design/web-react" in renderer
    assert "@icon-park/react" in renderer
