import axios from "axios";
import type {
  ComparisonReport,
  ArchitectureReport,
  CodebaseQnAResponse,
  DebtReport,
  GraphPayload,
  GuidedRepairPlan,
  LedgerEntry,
  LedgerLogRequest,
  ModelProfile,
  OptimizationStrategy,
  RouterResponse,
  TaskType,
  TestValidationRequest,
  TestValidationResult,
  OnboardingDocResponse,
  RepairApplyRequest,
  RepairApplyResult,
} from "./types";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE,
});

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (error.code === "ERR_NETWORK") {
      return "Cannot reach the API. Please ensure the backend is running on port 8000.";
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

export async function uploadRepo(file: File): Promise<GraphPayload> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<GraphPayload>("/api/upload-repo", form);
  return data;
}

export async function cloneRepo(url: string, branch?: string): Promise<GraphPayload> {
  const { data } = await api.post<GraphPayload>("/api/clone-repo", {
    url: url.trim(),
    branch: branch?.trim() || undefined,
  });
  return data;
}

export async function downloadUpdatedWorkspace(workspaceId: string): Promise<void> {
  const { data } = await api.get<Blob>(`/api/workspace/${encodeURIComponent(workspaceId)}/download`, {
    responseType: "blob",
  });
  const url = URL.createObjectURL(data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "architex-updated-project.zip";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function analyzeDebt(graph: GraphPayload): Promise<DebtReport> {
  const { data } = await api.post<DebtReport>("/api/analyze-debt", graph);
  return data;
}

export async function fetchLedger(): Promise<LedgerEntry[]> {
  const { data } = await api.get<LedgerEntry[]>("/api/ledger");
  return data;
}

export async function logLedgerChange(payload: LedgerLogRequest): Promise<LedgerEntry> {
  const { data } = await api.post<LedgerEntry>("/api/ledger/log", payload);
  return data;
}

export async function rollbackLedgerChange(id: number, workspaceRoot?: string): Promise<LedgerEntry> {
  const { data } = await api.post<LedgerEntry>("/api/ledger/rollback", {
    id,
    workspace_root: workspaceRoot,
  });
  return data;
}

// =====================================================================
// Module 6: Automatic Repair Engine API
// =====================================================================

export async function applyAutomaticRepair(payload: RepairApplyRequest): Promise<RepairApplyResult> {
  const { data } = await api.post<RepairApplyResult>("/api/repair/apply", payload);
  return data;
}

// =====================================================================
// Module 4: Multi-Model AI Router API
// =====================================================================

export async function fetchRouterModels(): Promise<ModelProfile[]> {
  const { data } = await api.get<ModelProfile[]>("/api/router/models");
  return data;
}

export async function routerGenerate(payload: {
  prompt: string;
  system?: string;
  task_type?: TaskType;
  strategy?: OptimizationStrategy;
  override_model?: string;
}): Promise<RouterResponse> {
  const { data } = await api.post<RouterResponse>("/api/router/generate", payload);
  return data;
}

export async function routerCompare(payload: {
  prompt: string;
  candidate_models?: string[];
  system?: string;
  strategy?: OptimizationStrategy;
}): Promise<ComparisonReport> {
  const { data } = await api.post<ComparisonReport>("/api/router/compare", payload);
  return data;
}

// =====================================================================
// Module 5: Guided Repair Planner & Test Validator API
// =====================================================================

export async function validateRepairTests(
  payload: TestValidationRequest
): Promise<TestValidationResult> {
  const { data } = await api.post<TestValidationResult>("/api/repair/validate-tests", payload);
  return data;
}
export async function deleteWorkspace(workspaceId: string): Promise<void> {
  try {
    await api.delete(`/api/workspace/${workspaceId}`);
  } catch (err) {
    console.warn("Failed to delete workspace:", err);
  }
}

export async function explainArchitecture(graph: GraphPayload): Promise<ArchitectureReport> {
  const { data } = await api.post<ArchitectureReport>("/api/explain-architecture", graph);
  return data;
}

export async function generateOnboarding(graph: GraphPayload): Promise<OnboardingDocResponse> {
  const { data } = await api.post<OnboardingDocResponse>("/api/generate-onboarding", graph);
  return data;
}

export async function askCodebase(question: string, graph: GraphPayload): Promise<CodebaseQnAResponse> {
  const { data } = await api.post<CodebaseQnAResponse>("/api/ask-codebase", {
    question,
    graph,
  });
  return data;
}

export type LLMStatus = {
  connected: boolean;
  primary_model: string;
  fallback_model: string;
  has_gemini_key: boolean;
  has_openai_key: boolean;
  active_provider: "gemini" | "openai" | "none";
};

export async function getLLMStatus(): Promise<LLMStatus> {
  const { data } = await api.get<LLMStatus>("/api/llm/status");
  return data;
}

export async function setGeminiApiKey(apiKey: string): Promise<LLMStatus> {
  const { data } = await api.post<LLMStatus>("/api/llm/gemini-key", { api_key: apiKey.trim() });
  return data;
}
