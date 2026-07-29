export type AetherApprovalStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'expired'
  | 'executing'
  | 'consumed';

export type AetherApprovalFilter = AetherApprovalStatus | 'all';

export interface AetherApprovalProposalProjection {
  target: string;
  operation: string;
  reason: string;
  risk: string;
  reversible: boolean;
  required_scopes: string[];
  argument_keys: string[];
  target_hint?: string | null;
  context: Record<string, string>;
}

export interface AetherApprovalResultProjection {
  ok: boolean;
  status: string;
  error?: string | null;
}

export interface AetherApprovalView {
  approval_id: string;
  action_id: string;
  action_hash: string;
  status: AetherApprovalStatus;
  requested_at: string;
  expires_at: string;
  request_channel?: string | null;
  requested_by?: string | null;
  decided_at?: string | null;
  decided_by?: string | null;
  decision_reason?: string | null;
  decision_channel?: string | null;
  consumed_at?: string | null;
  proposal: AetherApprovalProposalProjection;
  result?: AetherApprovalResultProjection | null;
}

export interface AetherApprovalSnapshot {
  generated_at: string;
  filter: AetherApprovalFilter;
  status_counts: Record<AetherApprovalStatus, number>;
  approvals: AetherApprovalView[];
  authority: {
    gateway_is_execution_authority: true;
    exact_action_hash_required: true;
    operator_token_in_renderer: false;
    raw_action_arguments_in_renderer: false;
  };
  secret_values_exposed: false;
}

export interface AetherApprovalDecisionReceipt {
  approval: AetherApprovalView;
  replayed: boolean;
  expression?: {
    modality?: string;
    content?: string;
    target?: string | null;
    delivered_to_origin?: boolean;
  } | null;
  secret_values_exposed: false;
}

export interface AetherApprovalBridge {
  snapshot(status?: AetherApprovalFilter): Promise<AetherApprovalSnapshot>;
  get(approvalId: string): Promise<AetherApprovalView>;
  approve(
    approvalId: string,
    reason: string,
    expectedActionHash: string,
  ): Promise<AetherApprovalDecisionReceipt>;
  reject(
    approvalId: string,
    reason: string,
    expectedActionHash: string,
  ): Promise<AetherApprovalDecisionReceipt>;
}
