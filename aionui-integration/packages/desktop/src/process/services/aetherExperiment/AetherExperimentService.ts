import type { AetherExperimentConsoleSnapshot } from '../../../common/aetherExperimentTypes';
export interface AetherExperimentServiceConfig { baseUrl: string; operatorToken: string; timeoutMs?: number; }
export class AetherExperimentService {
  private readonly baseUrl: string; private readonly token: string; private readonly timeoutMs: number;
  constructor(config: AetherExperimentServiceConfig) {
    const parsed = new URL(config.baseUrl);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Aether Gateway URL must use http or https');
    if (!config.operatorToken.trim()) throw new Error('Aether operator token is required in the Electron main process');
    this.baseUrl = parsed.toString().replace(/\/$/, ''); this.token = config.operatorToken; this.timeoutMs = Math.max(1000, config.timeoutMs ?? 30000);
  }
  snapshot(): Promise<AetherExperimentConsoleSnapshot> { return this.request('/api/experiments/console'); }
  configureSource(input: unknown): Promise<unknown> { return this.request('/api/web-intelligence/configurations', { method: 'POST', body: JSON.stringify(input) }); }
  conform(adapterId: string, input: unknown): Promise<unknown> { return this.request(`/api/web-intelligence/sources/${encodeURIComponent(adapterId)}/conform`, { method: 'POST', body: JSON.stringify(input) }); }
  refreshEvidence(input: unknown): Promise<unknown> { return this.request('/api/web-intelligence/freshness/run', { method: 'POST', body: JSON.stringify(input) }); }
  discover(input: unknown): Promise<unknown> { return this.request('/api/web-intelligence/discover', { method: 'POST', body: JSON.stringify(input) }); }
  createPlan(input: unknown): Promise<unknown> { return this.request('/api/experiments/plans', { method: 'POST', body: JSON.stringify(input) }); }
  runPlan(planId: string): Promise<unknown> { return this.request(`/api/experiments/plans/${encodeURIComponent(planId)}/run`, { method: 'POST' }); }
  recordDemand(runId: string, input: unknown): Promise<unknown> { return this.request(`/api/experiments/runs/${encodeURIComponent(runId)}/demand-signals`, { method: 'POST', body: JSON.stringify(input) }); }
  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, { ...init, signal: controller.signal, headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Aether-Operator-Token': this.token, ...(init.headers ?? {}) } });
      const text = await response.text(); const payload = text ? JSON.parse(text) : {};
      if (!response.ok) throw new Error(`Aether experiment request failed (${response.status}): ${payload?.detail ?? response.statusText}`);
      return payload as T;
    } finally { clearTimeout(timer); }
  }
}
