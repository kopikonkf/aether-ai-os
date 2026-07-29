import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  AetherApprovalBridge,
  AetherApprovalDecisionReceipt,
  AetherApprovalFilter,
  AetherApprovalSnapshot,
  AetherApprovalView,
} from '../../../common/aetherApprovalTypes';

declare global {
  interface Window {
    aetherApproval: AetherApprovalBridge;
  }
}

export function useAetherApprovals(status: AetherApprovalFilter, refreshMs = 10_000) {
  const [snapshot, setSnapshot] = useState<AetherApprovalSnapshot | null>(null);
  const [selected, setSelected] = useState<AetherApprovalView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  const apply = useCallback(async <T,>(operation: () => Promise<T>, refreshAfter = false): Promise<T> => {
    setLoading(true);
    setError(null);
    try {
      const result = await operation();
      if (refreshAfter) {
        const next = await window.aetherApproval.snapshot(status);
        if (mounted.current) setSnapshot(next);
      }
      return result;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      if (mounted.current) setError(message);
      throw cause;
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [status]);

  const refresh = useCallback(async () => {
    const next = await apply(() => window.aetherApproval.snapshot(status));
    if (mounted.current) {
      setSnapshot(next);
      if (selected) {
        setSelected(next.approvals.find((item) => item.approval_id === selected.approval_id) ?? null);
      }
    }
    return next;
  }, [apply, selected, status]);

  const inspect = useCallback(async (approvalId: string) => {
    const next = await apply(() => window.aetherApproval.get(approvalId));
    if (mounted.current) setSelected(next);
    return next;
  }, [apply]);

  const decide = useCallback(async (
    approved: boolean,
    approval: AetherApprovalView,
    reason: string,
  ): Promise<AetherApprovalDecisionReceipt> => {
    const operation = approved
      ? () => window.aetherApproval.approve(approval.approval_id, reason, approval.action_hash)
      : () => window.aetherApproval.reject(approval.approval_id, reason, approval.action_hash);
    const receipt = await apply(operation, true);
    if (mounted.current) setSelected(receipt.approval);
    return receipt;
  }, [apply]);

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
    selected,
    error,
    loading,
    refresh,
    inspect,
    decide,
    clearSelection: () => setSelected(null),
  };
}
