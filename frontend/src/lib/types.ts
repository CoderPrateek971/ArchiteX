export type NodeKind = "file" | "class" | "function" | "module";

export type GraphNodeData = {
  label: string;
  kind: NodeKind | string;
  path?: string;
  highlighted?: boolean;
  [key: string]: unknown;
};

export type GraphNode = {
  id: string;
  type?: string;
  position: { x: number; y: number };
  data: GraphNodeData;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type?: string;
  label?: string;
  data?: { kind?: string };
};

export type GraphPayload = {
  workspace_id?: string;
  repo_root?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  files?: string[];
  file_map?: Record<string, string>;
};

export type Severity = "Low" | "Medium" | "High";

export type RemediationStep = {
  step_number: number;
  phase: string;
  file_name: string;
  action: string;
  details: string;
};

export type StructuredRemediationPlan = {
  target_file: string;
  severity: Severity;
  upstream_dependencies: string[];
  downstream_dependencies: string[];
  affected_symbols: string[];
  steps: RemediationStep[];
  proposed_code: string;
  diff_summary: string;
  blast_radius: string;
};

export type DebtFinding = {
  id?: string;
  file_name: string;
  title?: string;
  description: string;
  severity: Severity;
  category?: string;
  line_number?: number | null;
  dependencies?: string[];
  suggested_fix: string;
  proposed_code?: string | null;
  structured_plan?: StructuredRemediationPlan | null;
  status?: string;
};

export type DebtReport = {
  findings: DebtFinding[];
  model?: string | null;
  fallback_used?: boolean;
  summary_counts?: {
    High?: number;
    Medium?: number;
    Low?: number;
    Total?: number;
  };
};

export type LedgerChangedBy = "AI" | "User";
export type LedgerStatus = "active" | "rolled_back";
export type LedgerSeverity = "low" | "medium" | "high";

export type LedgerEntry = {
  id: number;
  timestamp: string;
  file_path: string;
  previous_code: string;
  new_code: string;
  severity: LedgerSeverity;
  changed_by: LedgerChangedBy;
  details?: string;
  status: LedgerStatus;
};

export type LedgerLogRequest = {
  file_path: string;
  previous_code: string;
  new_code: string;
  severity: string;
  changed_by: LedgerChangedBy;
  details?: string;
  workspace_root?: string;
};
