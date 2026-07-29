export type MissionStatus =
  | 'draft' | 'review-required' | 'approved' | 'rejected' | 'running'
  | 'waiting-approval' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'stopped';

export interface AetherOpportunityBrief {
  brief_id: string;
  title: string;
  lane: 'internal-maintenance' | 'external-value';
  problem_statement: string;
  expected_net_value_usd: number;
  independent_support_count: number;
  contradiction_evidence_ids: string[];
  blockers: string[];
}

export interface AetherMissionView {
  status: MissionStatus;
  plan: {
    mission_id: string;
    objective: string;
    lane: 'internal-maintenance' | 'external-value';
    northstar_alignment: string;
    steps: Array<{ step_id: string; title: string }>;
    budget: { max_cost_usd: number; max_duration_seconds: number; max_step_attempts: number };
  };
  brief: AetherOpportunityBrief;
  outcome?: {
    state: 'claimed' | 'realized' | 'verified' | 'no-value';
    claimed_value_usd: number;
    realized_revenue_usd: number;
    verified_revenue_usd: number;
  } | null;
}

export interface AetherMissionSnapshot {
  generated_at: string;
  operator: string;
  status: { briefs: number; missions: number; by_status: Record<MissionStatus, number> };
  opportunities: AetherOpportunityBrief[];
  missions: AetherMissionView[];
  authority: {
    opportunity_evidence_is_not_permission: true;
    claimed_value_is_not_revenue: true;
    model_self_approval: 'forbidden';
  };
  secret_values_exposed: false;
}

export interface AetherMissionBridge {
  snapshot(): Promise<AetherMissionSnapshot>;
  approve(missionId: string, reason: string): Promise<AetherMissionView>;
  reject(missionId: string, reason: string): Promise<AetherMissionView>;
  run(missionId: string, maximumSteps?: number): Promise<AetherMissionView>;
  pause(missionId: string, reason: string): Promise<AetherMissionView>;
  cancel(missionId: string, reason: string): Promise<AetherMissionView>;
}
