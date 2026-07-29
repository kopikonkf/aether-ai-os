# Feminine Browser Voice Profile

## Immediate browser path

The overlay adds a Voice selector, rate, pitch, and preview button under **Connection and privacy**.

Default ranking prefers:

1. Microsoft Gadis Indonesian voice, when exposed by Windows/browser;
2. an Aoede-named voice, if present;
3. Google Bahasa Indonesia;
4. another Indonesian voice;
5. a known feminine voice available on the current device.

Default profile:

- language: `id-ID`
- rate: `1.02`
- pitch: `1.12`

The preference is stored in browser `localStorage`; the operator token remains memory-only and is not persisted.

## Consistent Google provider path

For a stable voice across devices and transports, create a dedicated Google Cloud Text-to-Speech adapter rather than relying on browser voices. The recommended Indonesian female target is `id-ID-Chirp3-HD-Aoede`.

That adapter is a later transport upgrade. It should synthesize audio server-side and return an audio stream/asset to Telegram, Browser Senses, and LiveKit without changing Aether's cognitive core.
