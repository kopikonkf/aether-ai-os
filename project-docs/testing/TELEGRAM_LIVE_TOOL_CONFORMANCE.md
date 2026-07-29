# Telegram Live Tool Conformance

## Why this test is required

The deterministic `action-demo --mode tool` already proved that the tool registry and governed action path work. It did not prove that a live model, reached through Telegram, requests a tool correctly.

The original Aether/Hermes code parsed literal `[TOOL ...]` tags. v0.19.2 instead exposes provider-native function tools through `ConfiguredModelProvider`. The persona still contains legacy tag language. Therefore model-to-tool calling is not Founder-proven until a real Telegram turn produces an `action.completed` receipt.

## Create proof file

```powershell
.\AETHER_TOOL_PROOF.ps1 -Action Create
```

Copy the generated `telegram_prompt` exactly into Telegram.

Success requires both:

1. Aether replies with the exact nonce from the file.
2. The action event ledger contains an authoritative receipt.

Verify the receipt:

```powershell
.\AETHER_TOOL_PROOF.ps1 -Action Verify
```

Expected:

```json
{
  "verified": true,
  "interpretation": "Founder-proven model→governance→read-tool→result loop"
}
```

## Failure interpretation

- Literal `[TOOL ...]` in the reply: provider followed legacy prompt text but no parser executed it. Add a governed legacy-tag compatibility bridge or remove tag instructions for that provider.
- `Access denied`: the requested file is outside configured `read_roots` or the wrong `AETHER_HOME` was used.
- Hallucinated nonce with no ledger receipt: failure; a text answer is not execution evidence.
- Pending approval: inspect `/approvals`; read should normally be low-risk and auto-approved.
