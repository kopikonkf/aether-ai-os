import type { AetherOpportunitySnapshot } from '../../../common/aetherOpportunityTypes';
export interface AetherOpportunityServiceConfig { baseUrl: string; operatorToken: string; timeoutMs?: number; }
export class AetherOpportunityService {
  private readonly baseUrl: string; private readonly token: string; private readonly timeoutMs: number;
  constructor(config: AetherOpportunityServiceConfig) {
    const parsed = new URL(config.baseUrl); if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Aether Gateway URL must use http or https');
    if (!config.operatorToken.trim()) throw new Error('Aether operator token is required in the Electron main process');
    this.baseUrl = parsed.toString().replace(/\/$/, ''); this.token = config.operatorToken; this.timeoutMs = Math.max(1000, config.timeoutMs ?? 30000);
  }
  snapshot(): Promise<AetherOpportunitySnapshot> { return this.request('/api/opportunity-intelligence/console'); }
  scout(input: unknown): Promise<unknown> { return this.request('/api/opportunity-intelligence/scout-runs', { method: 'POST', body: JSON.stringify(input) }); }
  score(input: unknown): Promise<unknown> { return this.request('/api/opportunity-intelligence/portfolio/score', { method: 'POST', body: JSON.stringify(input) }); }
  decide(candidateId: string, input: unknown): Promise<unknown> { return this.request(`/api/opportunity-intelligence/candidates/${encodeURIComponent(candidateId)}/decision`, { method: 'POST', body: JSON.stringify(input) }); }
  mandate(candidateId: string, input: unknown): Promise<unknown> { return this.request(`/api/opportunity-intelligence/candidates/${encodeURIComponent(candidateId)}/mandates`, { method: 'POST', body: JSON.stringify(input) }); }
  convert(candidateId: string): Promise<unknown> { return this.request(`/api/opportunity-intelligence/candidates/${encodeURIComponent(candidateId)}/convert-to-mission`, { method: 'POST' }); }
  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, { ...init, signal: controller.signal, headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Aether-Operator-Token': this.token, ...(init.headers ?? {}) } });
      const text = await response.text(); const payload = text ? JSON.parse(text) : {};
      if (!response.ok) throw new Error(`Aether opportunity request failed (${response.status}): ${payload?.detail ?? response.statusText}`);
      if (path.endsWith('/console') && payload.secret_values_exposed !== false) throw new Error('Aether response did not assert secret redaction');
      return payload as T;
    } finally { clearTimeout(timer); }
  }
}
