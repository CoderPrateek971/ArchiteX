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
