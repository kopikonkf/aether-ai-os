import { useCallback, useEffect, useRef, useState } from 'react';
import type { AetherMissionBridge, AetherMissionSnapshot } from '../../../common/aetherMissionTypes';

declare global { interface Window { aetherMission: AetherMissionBridge } }

export function useAetherMissions(refreshMs = 15_000) {
  const [snapshot, setSnapshot] = useState<AetherMissionSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);
  const apply = useCallback(async (operation: () => Promise<unknown>) => {
    setLoading(true); setError(null);
    try {
      await operation();
      const next = await window.aetherMission.snapshot();
      if (mounted.current) setSnapshot(next);
      return next;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      if (mounted.current) setError(message);
      throw cause;
    } finally { if (mounted.current) setLoading(false); }
  }, []);
  const refresh = useCallback(() => apply(() => Promise.resolve()), [apply]);
  const approve = useCallback((id: string, reason: string) => apply(() => window.aetherMission.approve(id, reason)), [apply]);
  const reject = useCallback((id: string, reason: string) => apply(() => window.aetherMission.reject(id, reason)), [apply]);
  const run = useCallback((id: string) => apply(() => window.aetherMission.run(id, 5)), [apply]);
  const pause = useCallback((id: string, reason: string) => apply(() => window.aetherMission.pause(id, reason)), [apply]);
  const cancel = useCallback((id: string, reason: string) => apply(() => window.aetherMission.cancel(id, reason)), [apply]);
  useEffect(() => {
    mounted.current = true; void refresh();
    const timer = window.setInterval(() => void refresh(), Math.max(5_000, refreshMs));
    return () => { mounted.current = false; window.clearInterval(timer); };
  }, [refresh, refreshMs]);
  return { snapshot, error, loading, refresh, approve, reject, run, pause, cancel };
}
