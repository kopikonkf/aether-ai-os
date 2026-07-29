export interface AetherLiveSourceSnapshot {
  adapter_id: string;
  source_id: string;
  endpoint: string;
  allowed_domains: string[];
  enabled: boolean;
  credential_handle_present: boolean;
  configuration_hash: string;
}
export interface AetherExperimentRunSnapshot {
  run_id: string;
  plan_id: string;
  status: string;
  cost_usd: number;
  artifact_ids: string[];
  preview_id?: string | null;
  stop_reason?: string | null;
}
export interface AetherExperimentConsoleSnapshot {
  web: { status: Record<string, number | string>; sources: AetherLiveSourceSnapshot[]; conformance: unknown[]; freshness: Array<Record<string, unknown>>; discoveries: Array<Record<string, unknown>> };
  experiments: { status: Record<string, number | string>; plans: Array<Record<string, unknown>>; runs: AetherExperimentRunSnapshot[]; artifacts: Array<Record<string, unknown>>; previews: Array<Record<string, unknown>>; signals: Array<Record<string, unknown>>; reviews: Array<Record<string, unknown>> };
  authority: Record<string, boolean>;
}
