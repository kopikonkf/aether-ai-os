# Aether v0.19.2 — First Live Integration Recovery

## Current accepted evidence

The deterministic 13-step first pulse passed and the Windows Gateway is healthy. The remaining failures are communication-boundary configuration, not Core boot failures.

## Root cause 1 — stale process environment

`aether-core/.env` is loaded once when the Gateway process starts. Editing provider or Telegram values does not mutate the environment of an already-running process.

After every `.env` change:

```powershell
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Restart
```

## Browser Senses first connection

The UI intentionally does not read or persist the trusted operator token. Copy it locally:

```powershell
.\AETHER_WINDOWS_DIAGNOSE.ps1 -Area Browser -CopyOperatorToken -OpenSenses
```

Then:

1. Expand **Connection and privacy**.
2. Paste into **Founder/operator token**.
3. Click **Connect Sense**.
4. When LiveKit is unavailable, the UI should still create an Aether browser session and enable text plus browser-native speech fallback.

`OFFLINE` and `Transport not initialized` are initial UI state labels. They should change only after successful session issuance.

## Telegram recovery

Required `.env` shape:

```dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<BotFather token>
TELEGRAM_ALLOWED_USER_IDS=<numeric founder user id>
```

Run:

```powershell
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Restart
.\AETHER_WINDOWS_DIAGNOSE.ps1 -Area Telegram
```

The diagnostic checks:

- stale process environment;
- Bot API token validity via `getMe`;
- existing webhook conflicts;
- numeric allowlist format;
- Gateway stderr.

If a webhook exists, explicitly remove it:

```powershell
.\AETHER_WINDOWS_DIAGNOSE.ps1 -Area Telegram -DeleteTelegramWebhook
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Restart
```

Test DM in this order:

```text
/start
/status
Halo Aether
```

For group rooms, start with `/status@YourBotUsername`. Telegram privacy mode normally prevents ordinary group text from reaching the bot. To receive all group text, either make the bot an administrator or disable privacy through BotFather and re-add the bot to the group.

## Logs

```powershell
Get-Content .\.aether-windows\logs\gateway.stderr.log -Tail 120
Get-Content .\.aether-windows\logs\gateway.stdout.log -Tail 120
```
