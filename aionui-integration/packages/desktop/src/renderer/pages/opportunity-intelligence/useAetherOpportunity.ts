import { useCallback, useEffect, useState } from 'react';
import type { AetherOpportunitySnapshot } from '../../../common/aetherOpportunityTypes';
declare global { interface Window { aetherOpportunity?: { snapshot(): Promise<AetherOpportunitySnapshot>; scout(input: unknown): Promise<unknown>; score(input: unknown): Promise<unknown>; decide(candidateId: string, input: unknown): Promise<unknown>; mandate(candidateId: string, input: unknown): Promise<unknown>; convert(candidateId: string): Promise<unknown>; }; } }
export function useAetherOpportunity() {
  const [snapshot, setSnapshot] = useState<AetherOpportunitySnapshot>(); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  const api = window.aetherOpportunity;
  const refresh = useCallback(async () => { if (!api) { setError('Aether Opportunity IPC is not installed'); return; } setLoading(true); try { setSnapshot(await api.snapshot()); setError(''); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setLoading(false); } }, [api]);
  const action = useCallback(async (fn: () => Promise<unknown>) => { setLoading(true); try { await fn(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); throw e; } finally { setLoading(false); } }, [refresh]);
  useEffect(() => { void refresh(); }, [refresh]);
  return { snapshot, loading, error, refresh, scout: (input: unknown) => action(() => api!.scout(input)), decide: (id: string, input: unknown) => action(() => api!.decide(id, input)), mandate: (id: string, input: unknown) => action(() => api!.mandate(id, input)), convert: (id: string) => action(() => api!.convert(id)) };
}
