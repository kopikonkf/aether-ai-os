const SOURCES = Object.freeze(['camera', 'screen']);
const MODES = Object.freeze(['one-shot', 'bounded']);


function requireSource(source) {
  if (!SOURCES.includes(source)) throw new Error('vision source must be camera or screen');
}


function normalizeLease(lease) {
  requireSource(lease?.source);
  if (!MODES.includes(lease?.mode)) throw new Error('unknown vision consent mode');
  if (!String(lease?.consent_id || '').trim() || !String(lease?.receipt_id || '').trim()) {
    throw new Error('vision transmission requires an authoritative consent receipt');
  }
  const expiresAt = Date.parse(lease.expires_at);
  if (!Number.isFinite(expiresAt)) throw new Error('vision consent lease requires an expiry');
  if (lease.mode === 'bounded' && lease.capture_interval_seconds !== 15) {
    throw new Error('bounded vision requires the frozen 15-second interval');
  }
  return {
    consentId: lease.consent_id,
    receiptId: lease.receipt_id,
    source: lease.source,
    mode: lease.mode,
    expiresAt,
    expiresAtText: lease.expires_at,
    captureIntervalSeconds: lease.capture_interval_seconds ?? null,
    nextSequence: 1,
    lastCaptureAt: null,
  };
}


export function createVisionCaptureCoordinator({ now = () => new Date() } = {}) {
  const leases = { camera: null, screen: null };

  return Object.freeze({
    grant(lease) {
      const normalized = normalizeLease(lease);
      if (normalized.expiresAt <= now().getTime()) {
        throw new Error('vision consent lease is expired');
      }
      leases[normalized.source] = normalized;
      return this.snapshot()[normalized.source];
    },

    envelope(source, frame, prompt) {
      requireSource(source);
      const lease = leases[source];
      if (!lease) throw new Error('vision transmission requires a server-authoritative consent lease');
      const capturedAt = now();
      if (lease.expiresAt <= capturedAt.getTime()) {
        leases[source] = null;
        throw new Error('vision consent lease is expired');
      }
      if (
        lease.mode === 'bounded'
        && lease.lastCaptureAt !== null
        && capturedAt.getTime() - lease.lastCaptureAt < 15000
      ) {
        throw new Error('bounded vision requires the frozen 15-second interval');
      }
      const envelope = {
        ...frame,
        prompt: String(prompt || '').trim(),
        consent_id: lease.consentId,
        source,
        sequence_number: lease.nextSequence,
        captured_at: capturedAt.toISOString(),
      };
      lease.nextSequence += 1;
      lease.lastCaptureAt = capturedAt.getTime();
      if (lease.mode === 'one-shot') leases[source] = null;
      return envelope;
    },

    stop(source) {
      requireSource(source);
      const stopped = leases[source];
      leases[source] = null;
      return stopped ? { ...stopped } : null;
    },

    snapshot() {
      return Object.fromEntries(
        SOURCES.map((source) => [source, leases[source] ? { ...leases[source] } : null]),
      );
    },
  });
}
