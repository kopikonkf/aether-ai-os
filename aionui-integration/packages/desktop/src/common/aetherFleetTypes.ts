export type FleetJobKind =
  | 'health-probe'
  | 'receipt-renewal'
  | 'budget-evaluation'
  | 'incident-sweep';

export type FleetIncidentState = 'open' | 'acknowledged' | 'resolved';
export type FleetState = 'healthy' | 'degraded' | 'critical';

export interface AetherFleetJob {
  job_id: string;
  kind: FleetJobKind;
  interval_seconds: number;
  state: 'active' | 'paused';
  next_run_at: string;
  metadata: Record<string, unknown>;
}

export interface AetherFleetIncident {
  incident_id: string;
  fingerprint: string;
  kind: string;
  severity: 'info' | 'warning' | 'high' | 'critical';
  state: FleetIncidentState;
  driver_id?: string | null;
  summary: string;
  occurrence_count: number;
  first_seen_at: string;
  last_seen_at: string;
  cee_trigger_id?: string | null;
  evidence: Record<string, unknown>;
}

export interface AetherFleetDriver {
  driver_id: string;
  availability: string;
  conformance_state: string;
  routing_eligible: boolean;
  runtime_version?: string | null;
  provider_id?: string | null;
  model_id?: string | null;
  quota_state: string;
  renewal_due: boolean;
  reason?: string | null;
  reliability?: {
    score?: number;
    consecutive_failures?: number;
    effective_priority_penalty?: number;
  };
  metadata?: Record<string, unknown>;
}

export interface AetherFleetBudget {
  window_start: string;
  invocation_count: number;
  invocation_limit: number;
  known_cost_usd: number;
  cost_limit_usd: number;
  unknown_cost_invocations: number;
  invocation_budget_exceeded: boolean;
  cost_budget_exceeded: boolean;
}

export interface AetherFleetSnapshot {
  policy_id: string;
  generated_at: string;
  fleet_state: FleetState;
  routing_eligible_count: number;
  renewal_due_count: number;
  open_incident_count: number;
  critical_incident_count: number;
  drivers: AetherFleetDriver[];
  jobs: AetherFleetJob[];
  incidents: AetherFleetIncident[];
  recent_runs: Array<Record<string, unknown>>;
  budget: AetherFleetBudget;
  fallback_policy: Record<string, unknown>;
  scheduler: Record<string, unknown>;
  secret_values_exposed: false;
}

export interface AetherFleetBridge {
  snapshot(): Promise<AetherFleetSnapshot>;
  runDue(): Promise<AetherFleetSnapshot>;
  runJob(kind: FleetJobKind): Promise<AetherFleetSnapshot>;
  updateJob(
    kind: FleetJobKind,
    input: { enabled?: boolean; interval_seconds?: number; run_immediately?: boolean },
  ): Promise<AetherFleetSnapshot>;
  acknowledgeIncident(incidentId: string, reason: string): Promise<AetherFleetSnapshot>;
  resolveIncident(incidentId: string, reason: string): Promise<AetherFleetSnapshot>;
}
