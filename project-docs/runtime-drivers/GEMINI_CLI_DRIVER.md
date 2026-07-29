# Gemini CLI Driver

## Aether identity

```text
driver_id:  google-gemini-cli
adapter_id: runtime.coding.google-gemini-cli
routing:    runtime://coding/google-gemini-cli
```

## Required deployment configuration

```text
AETHER_GEMINI_BIN=/absolute/path/to/gemini
AETHER_GEMINI_API_KEY_FILE=/secure/path/gemini.key
# or AETHER_GEMINI_CREDENTIALS_FILE=/secure/path/application-default.json
AETHER_GEMINI_MODEL=gemini-2.5-flash
```

## Boundary

The translator invokes Gemini headlessly with streaming JSON, a disposable workspace, an isolated home, and an Aether policy that denies shell and web tools. Generated files remain untrusted until Aether independently verifies them.

## Conformance

```bash
python aether_cli.py driver-conformance --driver google-gemini-cli
python aether_cli.py gemini-live-demo
```

A changed executable, version, model, credential reference, manifest, suite, or expired receipt removes the driver from live routing.
