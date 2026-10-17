import axios from "axios";
import type {
  DebtReport,
  GraphPayload,
  LedgerEntry,
  LedgerLogRequest,
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
