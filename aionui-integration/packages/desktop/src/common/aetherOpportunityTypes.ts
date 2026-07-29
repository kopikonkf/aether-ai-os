export interface AetherOpportunityCandidate {
  candidate_id: string;
  title: string;
  problem_statement: string;
  category: string;
  risk: string;
  status: string;
  supporting_source_ids: string[];
  contradicting_claim_ids: string[];
  estimated_cost_usd: number;
  score: { utility_score: number; expected_net_value_usd: number; evidence_confidence: number };
}
export interface AetherOpportunitySnapshot {
  generated_at: string;
  status: Record<string, number | string>;
  sources: Array<{ source_id: string; adapter_id: string; name: string; kind: string; capabilities: string[]; metadata: Record<string, unknown> }>;
  source_status: Array<{ adapter_id: string; health: string; reason: string }>;
  runs: Array<{ run_id: string; status: string; source_ids: string[]; snapshot_ids: string[]; claim_ids: string[] }>;
  candidates: AetherOpportunityCandidate[];
  decisions: Array<{ candidate_id: string; decision: string; allocated_budget_usd: number }>;
  mandates: Array<{ mandate_id: string; candidate_id: string; autonomy_level: string; status: string; maximum_cost_usd: number }>;
  authority: Record<string, string | boolean>;
  secret_values_exposed: false;
}
