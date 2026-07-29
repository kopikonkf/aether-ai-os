# Native AionUi Live Web & Experiments Integration

The v0.19 integration pack follows the AionUi process boundary:

```text
React renderer
  → preload IPC
  → Electron main process
  → authenticated Aether Gateway
```

The renderer receives eight bounded operations and never receives the operator token. Source configuration, conformance, experiment execution, demand evidence, and review decisions are sent through `AetherExperimentService` in the main process.

Install non-destructively:

```bash
python aionui-integration/scripts/install_aionui_integration.py /path/to/AionUi
```

The installer copies feature files and writes a checklist. Shared router, sidebar, preload, and bootstrap wiring remain explicit upstream changes.
