import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  AetherFleetBridge,
  AetherFleetSnapshot,
  FleetJobKind,
} from '../../../common/aetherFleetTypes';

declare global {
  interface Window {
    aetherFleet: AetherFleetBridge;
  }
}

export function useAetherFleet(refreshMs = 15_000) {
  const [snapshot, setSnapshot] = useState<AetherFleetSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  const apply = useCallback(async (operation: () => Promise<AetherFleetSnapshot>) => {
    setLoading(true);
    setError(null);
    try {
      const next = await operation();
      if (mounted.current) setSnapshot(next);
      return next;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      if (mounted.current) setError(message);
      throw cause;
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  const refresh = useCallback(() => apply(() => window.aetherFleet.snapshot()), [apply]);
  const runDue = useCallback(() => apply(() => window.aetherFleet.runDue()), [apply]);
  const runJob = useCallback((kind: FleetJobKind) => apply(() => window.aetherFleet.runJob(kind)), [apply]);
  const updateJob = useCallback(
    (kind: FleetJobKind, input: { enabled?: boolean; interval_seconds?: number; run_immediately?: boolean }) =>
      apply(() => window.aetherFleet.updateJob(kind, input)),
    [apply],
  );
  const acknowledgeIncident = useCallback(
    (incidentId: string, reason: string) => apply(() => window.aetherFleet.acknowledgeIncident(incidentId, reason)),
    [apply],
  );
  const resolveIncident = useCallback(
    (incidentId: string, reason: string) => apply(() => window.aetherFleet.resolveIncident(incidentId, reason)),
    [apply],
  );

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), Math.max(5_000, refreshMs));
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, [refresh, refreshMs]);

  return {
    snapshot,
    error,
    loading,
    refresh,
    runDue,
    runJob,
    updateJob,
    acknowledgeIncident,
    resolveIncident,
  };
}
