import type { AetherMissionSnapshot, AetherMissionView } from '../../../common/aetherMissionTypes';

export interface AetherMissionServiceConfig {
  baseUrl: string;
  operatorToken: string;
  timeoutMs?: number;
}

function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Aether Gateway URL must use http or https');
  parsed.pathname = parsed.pathname.replace(/\/$/, '');
  parsed.search = '';
  parsed.hash = '';
  return parsed.toString().replace(/\/$/, '');
}

export class AetherMissionService {
  private readonly baseUrl: string;
  private readonly operatorToken: string;
  private readonly timeoutMs: number;

  constructor(config: AetherMissionServiceConfig) {
    if (!config.operatorToken.trim()) throw new Error('Aether operator token is required in the main process');
    this.baseUrl = normalizeBaseUrl(config.baseUrl);
    this.operatorToken = config.operatorToken;
    this.timeoutMs = Math.max(1_000, config.timeoutMs ?? 20_000);
  }

  snapshot(): Promise<AetherMissionSnapshot> {
    return this.request('/api/mission-operations/console');
  }

  approve(missionId: string, reason: string): Promise<AetherMissionView> {
    return this.request(`/api/missions/${encodeURIComponent(missionId)}/approve`, {
      method: 'POST', body: JSON.stringify({ reason }),
    });
  }

  reject(missionId: string, reason: string): Promise<AetherMissionView> {
    return this.request(`/api/missions/${encodeURIComponent(missionId)}/reject`, {
      method: 'POST', body: JSON.stringify({ reason }),
    });
  }

  run(missionId: string, maximumSteps = 5): Promise<AetherMissionView> {
    return this.request(`/api/missions/${encodeURIComponent(missionId)}/run`, {
      method: 'POST', body: JSON.stringify({ maximum_steps: maximumSteps }),
    });
  }

  pause(missionId: string, reason: string): Promise<AetherMissionView> {
    return this.request(`/api/missions/${encodeURIComponent(missionId)}/pause`, {
      method: 'POST', body: JSON.stringify({ reason }),
    });
  }

  cancel(missionId: string, reason: string): Promise<AetherMissionView> {
    return this.request(`/api/missions/${encodeURIComponent(missionId)}/cancel`, {
      method: 'POST', body: JSON.stringify({ reason }),
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
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
        throw new Error(`Aether mission request failed (${response.status}): ${detail}`);
      }
      if (path === '/api/mission-operations/console' && payload.secret_values_exposed !== false) {
        throw new Error('Aether mission response did not assert secret redaction');
      }
      return payload as T;
    } finally {
      clearTimeout(timer);
    }
  }
}
