import { useCallback, useEffect, useState } from 'react';
import type { AetherExperimentConsoleSnapshot } from '../../../common/aetherExperimentTypes';
declare global { interface Window { aetherExperiment?: { snapshot(): Promise<AetherExperimentConsoleSnapshot>; configureSource(input: unknown): Promise<unknown>; conform(adapterId: string, input: unknown): Promise<unknown>; refreshEvidence(input: unknown): Promise<unknown>; discover(input: unknown): Promise<unknown>; createPlan(input: unknown): Promise<unknown>; runPlan(planId: string): Promise<unknown>; recordDemand(runId: string, input: unknown): Promise<unknown>; }; } }
export function useAetherExperiments() {
  const [snapshot, setSnapshot] = useState<AetherExperimentConsoleSnapshot>(); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  const api = window.aetherExperiment;
  const refresh = useCallback(async () => { if (!api) { setError('Aether Experiment IPC is not installed'); return; } setLoading(true); try { setSnapshot(await api.snapshot()); setError(''); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setLoading(false); } }, [api]);
  const action = useCallback(async (fn: () => Promise<unknown>) => { setLoading(true); try { const result = await fn(); await refresh(); return result; } catch (e) { setError(e instanceof Error ? e.message : String(e)); throw e; } finally { setLoading(false); } }, [refresh]);
  useEffect(() => { void refresh(); }, [refresh]);
  return { snapshot, loading, error, refresh, conform: (id: string) => action(() => api!.conform(id, { ttl_seconds: 86400 })), refreshEvidence: () => action(() => api!.refreshEvidence({})), discover: () => action(() => api!.discover({ minimum_mentions: 1, maximum_candidates: 50 })), runPlan: (id: string) => action(() => api!.runPlan(id)) };
}
