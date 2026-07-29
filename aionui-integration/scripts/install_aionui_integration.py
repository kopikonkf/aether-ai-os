#!/usr/bin/env python3
"""Install Aether feature pages into AionUi v2 with optional bounded router wiring."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROUTER = Path("packages/desktop/src/renderer/components/layout/Router.tsx")


def wire_senses_route(root: Path) -> dict[str, object]:
    path = root / ROUTER
    if not path.is_file():
        raise SystemExit(f"AionUi router not found: {path}")
    text = path.read_text(encoding="utf-8")
    changed = False
    import_line = "const UnifiedSenses = React.lazy(() => import('@renderer/pages/unified-senses'));"
    if import_line not in text:
        anchor = "const ScheduledTasksPage = React.lazy(() => import('@renderer/pages/cron/ScheduledTasksPage'));"
        if anchor not in text:
            raise SystemExit("AionUi router layout changed; refusing unsafe automatic patch")
        text = text.replace(anchor, anchor + "\n" + import_line)
        changed = True
    route_line = "          <Route path='/senses' element={withRouteFallback(UnifiedSenses)} />"
    if route_line not in text:
        anchor = "          <Route path='/scheduled' element={withRouteFallback(ScheduledTasksPage)} />"
        if anchor not in text:
            raise SystemExit("AionUi route anchor changed; refusing unsafe automatic patch")
        text = text.replace(anchor, route_line + "\n" + anchor)
        changed = True
    if changed:
        path.write_text(text, encoding="utf-8")
    return {"path": str(ROUTER), "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("aionui_root", type=Path)
    parser.add_argument("--force", action="store_true", help="replace files previously installed by this pack")
    parser.add_argument("--wire-router", action="store_true", help="safely add the /senses route using known AionUi v2 anchors")
    args = parser.parse_args()
    root = args.aionui_root.resolve()
    package_json = root / "package.json"
    if not package_json.is_file():
        raise SystemExit(f"AionUi package.json not found: {package_json}")
    package = json.loads(package_json.read_text(encoding="utf-8"))
    if str(package.get("name", "")).lower() != "aionui":
        raise SystemExit("Target package is not AionUi")
    major = int(str(package.get("version", "0")).split(".", 1)[0])
    if major != 2:
        raise SystemExit(f"This pack targets AionUi major version 2; found {package.get('version')}")

    pack_root = Path(__file__).resolve().parents[1]
    source_root = pack_root / "packages" / "desktop" / "src"
    target_root = root / "packages" / "desktop" / "src"
    copied: list[str] = []
    for source in sorted(source_root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        target = target_root / relative
        if target.exists() and not args.force:
            raise SystemExit(f"Refusing to overwrite existing file: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(str(target.relative_to(root)))

    wiring = wire_senses_route(root) if args.wire_router else {"changed": False, "reason": "--wire-router not requested"}
    checklist = root / "AETHER_AIONUI_WIRING.md"
    checklist.write_text(
        "# Aether AionUi wiring checklist\n\n"
        "1. The Unified Senses page is available at `/#/senses` after router wiring.\n"
        "2. Add protected `/approvals` and `/senses` routes using the supplied snippets.\n"
        "3. Add SiderNav entries for Approval Inbox and Unified Senses using current AionUi conventions.\n"
        "4. Register AetherApprovalService/bridge in the main process and expose only the typed preload bridge.\n"
        "5. Route `/api/approvals*`, `/senses*`, and `/api/browser-senses*` to Aether Gateway.\n"
        "6. Keep AETHER_OPERATOR_TOKEN and LiveKit API secrets outside renderer code.\n"
        "7. Verify the approval renderer receives no raw action arguments or result output.\n"
        "8. Run AionUi lint, unit tests, WebUI start, and package build.\n\n"
        "Only the known Unified Senses router anchors are eligible for automatic modification.\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "installed", "version": package.get("version"), "files": copied, "router": wiring, "checklist": str(checklist)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
