export type NodeKind = "file" | "class" | "function" | "module";

export type GraphNodeData = {
  label: string;
  kind: NodeKind | string;
  path?: string;
  highlighted?: boolean;
  lineno?: number;
  end_lineno?: number;
  docstring?: string;
  bases?: string[];
  args?: string[];
  calls?: string[];
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

export type ScannedFileInfo = {
  path: string;
  size_bytes: number;
  lines_of_code: number;
  blank_lines: number;
  comment_lines: number;
  is_valid_python: boolean;
  syntax_error?: string | null;
  classes_count: number;
  functions_count: number;
  imports_count: number;
};

export type ProjectValidationSummary = {
  is_valid: boolean;
  repo_name: string;
  total_files_scanned: number;
  total_directories_scanned: number;
  ignored_directories_count: number;
  python_files_count: number;
  valid_python_files_count: number;
  syntax_error_files_count: number;
  total_loc: number;
  python_files?: ScannedFileInfo[];
  errors: string[];
  warnings: string[];
};

export type GitInfo = {
  url: string;
  branch?: string;
  commit?: string;
};

export type FileResponsibility = {
  file_path: string;
  role: string;
  summary: string;
  key_classes: string[];
  key_functions: string[];
  imports_internal: string[];
  imports_external: string[];
  dependents: string[];
};

export type DataFlowStep = {
  step_number: number;
  stage: string;
  source: string;
  destination: string;
  description: string;
  files_involved: string[];
};

export type ArchitectureLayer = {
  name: string;
  description: string;
  files: Array<{ path: string; role: string; summary: string }>;
};

export type ArchitectureReport = {
  project_name: string;
  system_overview: string;
  architectural_pattern: string;
  primary_layers: ArchitectureLayer[];
  file_responsibilities: FileResponsibility[];
  data_flow: DataFlowStep[];
  key_technologies: string[];
  model_used?: string | null;
  fallback_used?: boolean;
};

export type OnboardingDocResponse = {
  title: string;
  markdown: string;
  project_name: string;
  generated_at: string;
};

export type CodebaseQnAResponse = {
  question: string;
  answer: string;
  relevant_files: string[];
  relevant_symbols: string[];
  model_used?: string | null;
  fallback_used?: boolean;
};

export type GraphPayload = {
  workspace_id?: string;
  repo_root?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  files?: string[];
  file_map?: Record<string, string>;
  validation_summary?: ProjectValidationSummary;
  git_info?: GitInfo;
};

export type Severity = "Low" | "Medium" | "High";

export type RemediationStep = {
  step_number: number;
  phase: string;
  file_name: string;
  action: string;
  details: string;
};

export type RepairActionType =
  | "CONTRACT_VERIFICATION"
  | "CORE_REMEDIATION"
  | "CALLER_MIGRATION"
  | "TEST_VALIDATION";

export type RepairStep = {
  order: number;
  file_path: string;
  phase_name: string;
  action_type: RepairActionType;
  action_title: string;
  description: string;
  proposed_code: string;
  diff_summary: string;
  reasoning: string;
  potential_risks: string;
  status: "pending" | "applied" | "verified";
};

export type DownstreamImpact = {
  file_path: string;
  depth: number;
  relationship: string;
  symbols_used: string[];
  risk_level: "High" | "Medium" | "Low";
};

export type GuidedRepairPlan = {
  finding_id: string;
  target_file: string;
  severity: string;
  issue_title: string;
  root_cause: string;
  knowledge_graph_path: string[];
  blast_radius: string;
  downstream_impacts: DownstreamImpact[];
  ordered_steps: RepairStep[];
  architectural_reasoning: string;
  potential_risks: string[];
  test_validation_command: string;
};

export type TestValidationRequest = {
  files_to_validate: string[];
  workspace_root?: string | null;
  code_overrides?: Record<string, string>;
  run_pytest?: boolean;
};

export type TestValidationResult = {
  passed: boolean;
  syntax_passed: boolean;
  tests_passed: boolean;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  output_log: string;
  details: { file: string; check: string; status: string; error?: string }[];
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
  guided_plan?: GuidedRepairPlan | null;
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
  root_cause?: string;
  code_evidence?: string;
  potential_impact?: string;
  affected_files?: string[];
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
export type LedgerStatus = "active" | "rolled_back" | "failed";
export type LedgerSeverity = "low" | "medium" | "high";

export type LedgerEntry = {
  id: number;
  timestamp: string;
  file_path: string;
  previous_code: string;
  new_code: string;
  severity: LedgerSeverity | string;
  changed_by: LedgerChangedBy | string;
  details?: string;
  issue_id?: string | null;
  validation_result?: string | null;
  status: LedgerStatus | string;
  rollback_ref?: number | null;
  before_hash?: string | null;
  after_hash?: string | null;
};

export type LedgerLogRequest = {
  file_path: string;
  previous_code: string;
  new_code: string;
  severity: string;
  changed_by: LedgerChangedBy | string;
  details?: string;
  issue_id?: string;
  validation_result?: string;
  workspace_root?: string;
};

// =====================================================================
// Module 6: Automatic Repair Engine Types
// =====================================================================

export type RepairApplyRequest = {
  issue_id: string;
  file_path: string;
  severity: string;
  proposed_code: string;
  workspace_root?: string | null;
  workspace_id?: string | null;
  approval: boolean;
  original_code_hash?: string | null;
  expected_original_code?: string | null;
};

export type RepairApplyResult = {
  success: boolean;
  issue_id: string;
  file_path: string;
  severity: string;
  validation_status: "PASSED" | "FAILED" | "REJECTED" | "BLOCKED" | "CONFLICT" | string;
  output_logs: string;
  rollback_status: "NOT_NEEDED" | "RESTORED" | "NOT_APPLICABLE" | string;
  explanation: string;
  change_id?: number | null;
  details?: { file: string; check: string; status: string; error?: string }[];
};

// =====================================================================
// Module 4: Multi-Model AI Router Types
// =====================================================================

export type TaskType =
  | "architecture_analysis"
  | "code_remediation"
  | "security_audit"
  | "quick_fix"
  | "explanation"
  | "general";

export type OptimizationStrategy =
  | "balanced"
  | "cost_optimized"
  | "speed_optimized"
  | "quality_optimized";

export type ModelHealthStatus =
  | "Available"
  | "Cooling Down"
  | "Degraded"
  | "Unavailable";

export type ModelProfile = {
  id: string;
  name: string;
  provider: string;
  cost_input_per_m: number;
  cost_output_per_m: number;
  avg_latency_ms: number;
  quality_rating: number;
  context_window: number;
  specializations: TaskType[];
  is_configured: boolean;
  health_status: ModelHealthStatus;
  success_rate: number;
  consecutive_failures: number;
  last_latency_ms: number;
  last_error?: string | null;
};

export type RouterResponse = {
  content: string;
  model: string;
  provider: string;
  task_type: TaskType;
  strategy: OptimizationStrategy;
  fallback_used: boolean;
  fallback_reason?: string | null;
  fallback_chain: string[];
  latency_ms: number;
  estimated_cost: number;
  tokens_used: Record<string, number>;
};

export type ModelEvaluationScore = {
  model: string;
  provider: string;
  content: string;
  quality_score: number;
  relevance_score: number;
  overall_score: number;
  latency_ms: number;
  estimated_cost: number;
  syntax_valid: boolean;
  is_winner?: boolean;
  strengths: string[];
};

export type ComparisonReport = {
  prompt: string;
  task_type: TaskType;
  strategy: OptimizationStrategy;
  evaluations: ModelEvaluationScore[];
  winning_model: string;
  recommendation_reason: string;
};
