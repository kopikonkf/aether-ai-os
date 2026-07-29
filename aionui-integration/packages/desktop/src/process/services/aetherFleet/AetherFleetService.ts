import type {
  AetherFleetSnapshot,
  FleetJobKind,
} from '../../../common/aetherFleetTypes';

export interface AetherFleetServiceConfig {
  baseUrl: string;
  operatorToken: string;
  timeoutMs?: number;
}

function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Aether Gateway URL must use http or https');
  }
  parsed.pathname = parsed.pathname.replace(/\/$/, '');
  parsed.search = '';
  parsed.hash = '';
  return parsed.toString().replace(/\/$/, '');
}

export class AetherFleetService {
  private readonly baseUrl: string;
  private readonly operatorToken: string;
  private readonly timeoutMs: number;

  constructor(config: AetherFleetServiceConfig) {
    if (!config.operatorToken.trim()) {
      throw new Error('Aether operator token is required in the main process');
    }
    this.baseUrl = normalizeBaseUrl(config.baseUrl);
    this.operatorToken = config.operatorToken;
    this.timeoutMs = Math.max(1_000, config.timeoutMs ?? 15_000);
  }

  snapshot(): Promise<AetherFleetSnapshot> {
    return this.request('/api/runtime-fleet/console');
  }

  runDue(): Promise<AetherFleetSnapshot> {
    return this.request('/api/runtime-fleet/run-due', { method: 'POST' });
  }

  runJob(kind: FleetJobKind): Promise<AetherFleetSnapshot> {
    return this.request(`/api/runtime-fleet/jobs/${encodeURIComponent(kind)}/run`, { method: 'POST' });
  }

  updateJob(
    kind: FleetJobKind,
    input: { enabled?: boolean; interval_seconds?: number; run_immediately?: boolean },
  ): Promise<AetherFleetSnapshot> {
    return this.request(`/api/runtime-fleet/jobs/${encodeURIComponent(kind)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  }

  acknowledgeIncident(incidentId: string, reason: string): Promise<AetherFleetSnapshot> {
    return this.request(
      `/api/runtime-fleet/incidents/${encodeURIComponent(incidentId)}/acknowledge`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    );
  }

  resolveIncident(incidentId: string, reason: string): Promise<AetherFleetSnapshot> {
    return this.request(
      `/api/runtime-fleet/incidents/${encodeURIComponent(incidentId)}/resolve`,
      { method: 'POST', body: JSON.stringify({ reason }) },
    );
  }

  private async request(path: string, init: RequestInit = {}): Promise<AetherFleetSnapshot> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-Aether-Operator-Token': this.operatorToken,
          ...(init.headers ?? {}),
        },
      });
      const text = await response.text();
      const payload = text ? JSON.parse(text) : {};
      if (!response.ok) {
        const detail = typeof payload?.detail === 'string' ? payload.detail : response.statusText;
        throw new Error(`Aether fleet request failed (${response.status}): ${detail}`);
      }
      if (payload.secret_values_exposed !== false) {
        throw new Error('Aether fleet response did not assert secret redaction');
      }
      return payload as AetherFleetSnapshot;
    } finally {
      clearTimeout(timer);
    }
  }
}
