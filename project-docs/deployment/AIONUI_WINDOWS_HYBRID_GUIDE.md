# AionUi on Windows — Aether Hybrid Deployment Guide

This document is the deployment-level companion to `FOUNDER_START_HERE_WINDOWS.md`.

## Architecture authority

- Aether is the cognitive authority.
- AionUi is a replaceable operator shell.
- Aether must remain bootable and diagnosable when AionUi is absent or unhealthy.
- The Windows bring-up path therefore uses staged hybrid activation.

## Packaging truth

The Aether v0.19.2 release includes the AionUi **integration source pack**, but not the upstream application or installer.

The Linux Compose adapter clones and builds AionUi during image creation. The Windows-native alpha adapter intentionally does not do that. On Windows, AionUi is installed separately after Aether localhost acceptance.

## Supported paths

### Aether-only

No AionUi installation. Use `http://127.0.0.1:8000/senses`.

### Hybrid Lite

Install the official prebuilt AionUi Windows application, run its WebUI on `127.0.0.1:25808`, and keep Aether Gateway on `127.0.0.1:8000`.

This is the recommended first VPS topology.

### Hybrid Integrated

Clone a compatible AionUi v2 source tree, apply `aionui-integration/scripts/install_aionui_integration.py --wire-router`, build AionUi, and route same-origin `/senses` to Aether Gateway.

This is an integration refinement, not a first-boot requirement.

## Operational invariants

1. AionUi never owns Aether DNA, memory, cognition, governance, or CEE state.
2. AionUi failure must not stop Aether Gateway.
3. Aether and AionUi have separate logs, PIDs, and data paths.
4. Public ingress is configured only after both local services pass health checks.
5. `/#/senses` is not expected in an unmodified prebuilt AionUi installer.
