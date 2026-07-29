import type {
  AetherApprovalDecisionReceipt,
  AetherApprovalFilter,
  AetherApprovalSnapshot,
  AetherApprovalStatus,
  AetherApprovalView,
} from '../../../common/aetherApprovalTypes';

export interface AetherApprovalServiceConfig {
  baseUrl: string;
  operatorToken: string;
  timeoutMs?: number;
}

const STATUSES: AetherApprovalStatus[] = [
  'pending',
  'approved',
  'rejected',
  'expired',
  'executing',
  'consumed',
];
const FILTERS = new Set<AetherApprovalFilter>([...STATUSES, 'all']);
const CONTEXT_KEYS = new Set([
  'channel',
  'session_id',
  'runtime_id',
  'workspace_id',
  'mission_id',
  'step_id',
  'correlation_id',
]);
const SAFE_TARGET_KEYS = ['path', 'target', 'url', 'endpoint'] as const;

function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Aether Gateway URL must use http or https');
  }
  parsed.pathname = parsed.pathname.replace(/\/$/, '');
  parsed.search = '';
  parsed.hash = '';
  return parsed.toString().replace(/\/$/, '');
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function bounded(value: unknown, maximum = 500): string {
  const rendered = typeof value === 'string' ? value : String(value ?? '');
  return rendered.length <= maximum ? rendered : `${rendered.slice(0, maximum - 1)}…`;
}

function safeTargetHint(argumentsValue: unknown): string | null {
  const argumentsRecord = record(argumentsValue);
  for (const key of SAFE_TARGET_KEYS) {
    const candidate = argumentsRecord[key];
    if (candidate === undefined || candidate === null) continue;
    const rendered = bounded(candidate, 240);
    if (key === 'url' || key === 'endpoint') {
      try {
        const parsed = new URL(rendered);
        parsed.username = '';
        parsed.password = '';
        parsed.search = '';
        parsed.hash = '';
        return bounded(parsed.toString(), 240);
      } catch {
        return '[invalid URL omitted]';
      }
    }
    return rendered;
  }
  return null;
}

function projectContext(metadataValue: unknown): Record<string, string> {
  const metadata = record(metadataValue);
  return Object.fromEntries(
    Object.entries(metadata)
      .filter(([key, value]) => CONTEXT_KEYS.has(key) && ['string', 'number', 'boolean'].includes(typeof value))
      .map(([key, value]) => [key, bounded(value, 160)]),
  );
}

function normalizeStatus(value: unknown): AetherApprovalStatus {
  const rendered = String(value ?? '');
  if (!STATUSES.includes(rendered as AetherApprovalStatus)) {
    throw new Error(`Unknown approval status from Gateway: ${rendered}`);
  }
  return rendered as AetherApprovalStatus;
}

export class AetherApprovalService {
  private readonly baseUrl: string;
  private readonly operatorToken: string;
  private readonly timeoutMs: number;

  constructor(config: AetherApprovalServiceConfig) {
    if (!config.operatorToken.trim()) {
      throw new Error('Aether operator token is required in the main process');
    }
    this.baseUrl = normalizeBaseUrl(config.baseUrl);
    this.operatorToken = config.operatorToken;
    this.timeoutMs = Math.max(1_000, config.timeoutMs ?? 15_000);
  }

  async snapshot(status: AetherApprovalFilter = 'pending'): Promise<AetherApprovalSnapshot> {
    if (!FILTERS.has(status)) throw new Error(`Unknown approval filter: ${status}`);
    const query = encodeURIComponent(status);
    const [statusPayload, listPayload] = await Promise.all([
      this.request('/api/approvals/status'),
      this.request(`/api/approvals?status=${query}`),
    ]);
    const countsRaw = record(statusPayload);
    const listRaw = record(listPayload).approvals;
    const approvals = Array.isArray(listRaw) ? listRaw.map((item) => this.projectApproval(item)) : [];
    const statusCounts = Object.fromEntries(
      STATUSES.map((item) => [item, Number(countsRaw[item] ?? 0)]),
    ) as Record<AetherApprovalStatus, number>;
    return {
      generated_at: new Date().toISOString(),
      filter: status,
      status_counts: statusCounts,
      approvals,
      authority: {
        gateway_is_execution_authority: true,
        exact_action_hash_required: true,
        operator_token_in_renderer: false,
        raw_action_arguments_in_renderer: false,
      },
      secret_values_exposed: false,
    };
  }

  async get(approvalId: string): Promise<AetherApprovalView> {
    return this.projectApproval(
      await this.request(`/api/approvals/${encodeURIComponent(approvalId)}`),
    );
  }

  approve(
    approvalId: string,
    reason: string,
    expectedActionHash: string,
  ): Promise<AetherApprovalDecisionReceipt> {
    return this.decide(approvalId, true, reason, expectedActionHash);
  }

  reject(
    approvalId: string,
    reason: string,
    expectedActionHash: string,
  ): Promise<AetherApprovalDecisionReceipt> {
    return this.decide(approvalId, false, reason, expectedActionHash);
  }

  private async decide(
    approvalId: string,
    approved: boolean,
    reason: string,
    expectedActionHash: string,
  ): Promise<AetherApprovalDecisionReceipt> {
    const normalizedReason = reason.trim();
    if (normalizedReason.length < 3 || normalizedReason.length > 500) {
      throw new Error('Decision reason must contain 3–500 characters');
    }
    if (!/^[0-9a-f]{64}$/i.test(expectedActionHash)) {
      throw new Error('Expected action hash must be a 64-character SHA-256 value');
    }
    const action = approved ? 'approve' : 'reject';
    const raw = record(await this.request(
      `/api/approvals/${encodeURIComponent(approvalId)}/${action}`,
      {
        method: 'POST',
        body: JSON.stringify({
          reason: normalizedReason,
          expected_action_hash: expectedActionHash,
        }),
      },
    ));
    const expression = record(raw.expression);
    return {
      approval: this.projectApproval(raw.approval),
      replayed: Boolean(raw.replayed),
      expression: Object.keys(expression).length > 0 ? {
        modality: expression.modality ? bounded(expression.modality, 80) : undefined,
        target: expression.target ? bounded(expression.target, 160) : undefined,
        delivered_to_origin: Boolean(expression.delivered_to_origin),
      } : null,
      secret_values_exposed: false,
    };
  }

  private projectApproval(value: unknown): AetherApprovalView {
    const raw = record(value);
    const proposal = record(raw.proposal);
    const argumentsValue = proposal.arguments;
    const argumentsRecord = record(argumentsValue);
    const resultRaw = record(raw.result);
    const actionHash = String(raw.action_hash ?? '');
    if (!/^[0-9a-f]{64}$/i.test(actionHash)) {
      throw new Error('Gateway approval response did not contain a valid action hash');
    }
    return {
      approval_id: bounded(raw.approval_id, 160),
      action_id: bounded(raw.action_id, 160),
      action_hash: actionHash.toLowerCase(),
      status: normalizeStatus(raw.status),
      requested_at: bounded(raw.requested_at, 80),
      expires_at: bounded(raw.expires_at, 80),
      request_channel: raw.request_channel ? bounded(raw.request_channel, 80) : null,
      requested_by: raw.requested_by ? bounded(raw.requested_by, 160) : null,
      decided_at: raw.decided_at ? bounded(raw.decided_at, 80) : null,
      decided_by: raw.decided_by ? bounded(raw.decided_by, 160) : null,
      decision_reason: raw.decision_reason ? bounded(raw.decision_reason, 500) : null,
      decision_channel: raw.decision_channel ? bounded(raw.decision_channel, 80) : null,
      consumed_at: raw.consumed_at ? bounded(raw.consumed_at, 80) : null,
      proposal: {
        target: bounded(proposal.target, 80),
        operation: bounded(proposal.operation, 120),
        reason: bounded(proposal.reason, 500),
        risk: bounded(proposal.risk, 40),
        reversible: Boolean(proposal.reversible),
        required_scopes: Array.isArray(proposal.required_scopes)
          ? proposal.required_scopes.map((item) => bounded(item, 80)).slice(0, 32)
          : [],
        argument_keys: Object.keys(argumentsRecord).sort().slice(0, 64),
        target_hint: safeTargetHint(argumentsValue),
        context: projectContext(proposal.metadata),
      },
      result: Object.keys(resultRaw).length > 0 ? {
        ok: Boolean(resultRaw.ok),
        status: bounded(resultRaw.status, 80),
        error: resultRaw.error ? bounded(resultRaw.error, 500) : null,
      } : null,
    };
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-Aether-Operator-Token': this.operatorToken,
          ...(init.headers ?? {}),
        },
      });
      const text = await response.text();
      let payload: unknown = {};
      if (text) {
        try { payload = JSON.parse(text); }
        catch { throw new Error(`Aether approval response was not valid JSON (${response.status})`); }
      }
      if (!response.ok) {
        const detail = record(payload).detail;
        throw new Error(
          `Aether approval request failed (${response.status}): ${bounded(detail || response.statusText, 500)}`,
        );
      }
      return payload;
    } finally {
      clearTimeout(timer);
    }
  }
}
