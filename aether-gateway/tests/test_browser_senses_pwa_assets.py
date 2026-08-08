from __future__ import annotations

import json
import re
import struct
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CONSOLE = REPO_ROOT / "aether-gateway/src/aether_gateway/aionui_senses_console"
BROWSER_BUILD = REPO_ROOT / "aether-gateway/browser"


class BrowserSensesPwaAssetsTest(unittest.TestCase):
    def test_manifest_and_complete_icons_are_bounded_to_senses(self) -> None:
        manifest = json.loads((CONSOLE / "manifest.webmanifest").read_text("utf-8"))
        self.assertEqual(manifest["id"], "/senses")
        self.assertEqual(manifest["start_url"], "/senses")
        self.assertEqual(manifest["scope"], "/senses")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(
            {(icon["sizes"], icon["purpose"]) for icon in manifest["icons"]},
            {
                ("192x192", "any"),
                ("512x512", "any"),
                ("512x512", "maskable"),
            },
        )
        for icon in manifest["icons"]:
            path = CONSOLE / "icons" / icon["src"].split("/")[-1].split("?")[0]
            content = path.read_bytes()
            self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(
                struct.unpack(">II", content[16:24]),
                tuple(int(value) for value in icon["sizes"].split("x")),
            )

    def test_livekit_is_exactly_locked_bundled_and_not_loaded_from_a_cdn(self) -> None:
        package = json.loads((BROWSER_BUILD / "package.json").read_text("utf-8"))
        lock = json.loads((BROWSER_BUILD / "package-lock.json").read_text("utf-8"))
        app = (CONSOLE / "app.js").read_text("utf-8")
        bundle = CONSOLE / "vendor/livekit-client-2.17.2.esm.js"

        self.assertEqual(package["dependencies"]["livekit-client"], "2.17.2")
        self.assertEqual(package["devDependencies"]["esbuild"], "0.28.1")
        self.assertEqual(
            lock["packages"]["node_modules/livekit-client"]["version"], "2.17.2"
        )
        self.assertGreater(bundle.stat().st_size, 100_000)
        self.assertIn("./vendor/livekit-client-2.17.2.esm.js", app)
        for public_cdn in ("cdn.jsdelivr.net", "unpkg.com", "esm.sh", "skypack.dev"):
            self.assertNotIn(public_cdn, app)

    def test_service_worker_and_gateway_expose_only_the_static_shell_cache(self) -> None:
        worker = (CONSOLE / "sw.js").read_text("utf-8")
        policy = (CONSOLE / "pwa_cache_policy.js").read_text("utf-8")
        server = (
            REPO_ROOT / "aether-gateway/src/aether_gateway/api/server.py"
        ).read_text("utf-8")

        self.assertIn("NETWORK_ONLY intentionally does not call respondWith", worker)
        self.assertIn("AETHER_CLEAR_CACHES", worker)
        self.assertNotIn("/api/", worker)
        self.assertNotIn("/health", worker)
        self.assertIn("VERSIONED_STATIC_ASSETS", policy)
        self.assertIn("versioned('/senses/capability_actions.js')", policy)
        self.assertIn("url.origin !== allowedOrigin", policy)
        self.assertIn('headers={"Service-Worker-Allowed": "/senses"}', server)
        self.assertIn('path.startswith(("/senses/", "/api/", "/aether/api/"))', server)
        self.assertNotIn("cdn.jsdelivr.net", server)

    def test_every_shell_reference_uses_the_single_cache_build_id(self) -> None:
        policy = (CONSOLE / "pwa_cache_policy.js").read_text("utf-8")
        matched = re.search(r"PWA_BUILD_ID = '([^']+)'", policy)
        self.assertIsNotNone(matched)
        build_id = matched.group(1)
        for path in (
            CONSOLE / "index.html",
            CONSOLE / "app.js",
            CONSOLE / "capability_actions.js",
            CONSOLE / "sw.js",
            CONSOLE / "manifest.webmanifest",
        ):
            references = set(
                re.findall(r"senses-v1-slice-9-[0-9-]+", path.read_text("utf-8"))
            )
            self.assertEqual(references, {build_id}, path.name)


if __name__ == "__main__":
    unittest.main()
