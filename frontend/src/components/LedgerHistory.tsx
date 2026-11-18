import { useEffect, useState } from "react";
import {
  RotateCcw,
  User,
  Bot,
  AlertTriangle,
  Tag,
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { fetchLedger, rollbackLedgerChange, errorMessage } from "../lib/api";
import type { LedgerEntry } from "../lib/types";

export default function LedgerHistory() {
  const [logs, setLogs] = useState<LedgerEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [conflictWarning, setConflictWarning] = useState<string | null>(null);
  const [rollingBackId, setRollingBackId] = useState<number | null>(null);

  const loadLogs = async () => {
    try {
      const data = await fetchLedger();
      setLogs(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  useEffect(() => {
    void loadLogs();
  }, []);

  const handleRollback = async (id: number) => {
    const confirm = window.confirm(
      `Are you sure you want to rollback change #${id}? ArchiteX will verify that the file has not been modified since this change was recorded before reverting.`
    );
    if (!confirm) return;

    setRollingBackId(id);
    setError(null);
    setConflictWarning(null);

    try {
      await rollbackLedgerChange(id);
      void loadLogs();
    } catch (err: any) {
      const msg = errorMessage(err);
      if (err?.response?.status === 409 || msg.toLowerCase().includes("conflict")) {
        setConflictWarning(
          `Rollback Blocked (Conflict): ${msg}. File has newer modifications. Overwriting was prevented.`
        );
      } else {
        setError("Rollback failed: " + msg);
      }
    } finally {
      setRollingBackId(null);
    }
  };

  return (
    <div style={{ padding: 24, height: "100%", overflowY: "auto", color: "var(--text-primary)" }}>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: "var(--violet-400)", marginBottom: 6 }}>
        Change History & Rollback Ledger
      </h2>
      <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
        Complete audit history with issue attribution, selective rollback, and conflict detection.
      </p>

      {conflictWarning && (
        <div
          style={{
            padding: "10px 14px",
            marginBottom: 14,
            borderRadius: "var(--radius-sm)",
            background: "rgba(239, 68, 68, 0.15)",
            border: "1px solid var(--red-400)",
            color: "var(--red-400)",
            fontSize: 12,
            display: "flex",
            gap: 10,
            alignItems: "flex-start",
          }}
        >
          <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 1 }} />
          <div>
            <strong>Rollback Blocked by Conflict</strong>
            <p style={{ margin: "2px 0 0 0" }}>{conflictWarning}</p>
          </div>
        </div>
      )}

      {error && <div className="error-banner" style={{ marginBottom: 14 }}>{error}</div>}

      {logs.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontStyle: "italic" }}>
          No changes have been logged yet.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {logs.map((log) => {
            const isRolledBack = log.status === "rolled_back";
            const isFailed = log.status === "failed";
            const isAI = log.changed_by === "AI";
            const cleanPath = log.file_path.replace(/^file:/, "");

            return (
              <div
                key={log.id}
                style={{
                  background: "var(--bg-card)",
                  padding: 16,
                  borderRadius: "var(--radius-md)",
                  borderLeft: isRolledBack
                    ? "4px solid var(--text-muted)"
                    : isFailed
                    ? "4px solid var(--red-400)"
                    : "4px solid var(--cyan-400)",
                  borderTop: "1px solid var(--border-subtle)",
                  borderRight: "1px solid var(--border-subtle)",
                  borderBottom: "1px solid var(--border-subtle)",
                }}
              >
                {/* Header row: ID, User/AI, Path, Timestamp */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span
                      style={{
                        fontSize: 11,
                        fontFamily: "var(--font-mono)",
                        background: "rgba(255, 255, 255, 0.08)",
                        padding: "1px 6px",
                        borderRadius: "var(--radius-sm)",
                        color: "var(--cyan-400)",
                        fontWeight: 600,
                      }}
                    >
                      #{log.id}
                    </span>
                    {isAI ? (
                      <Bot size={18} color="var(--emerald-400)" />
                    ) : (
                      <User size={18} color="var(--cyan-400)" />
                    )}
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{cleanPath}</span>

                    <span
                      className={`severity-pill ${
                        log.severity
                          ? log.severity.charAt(0).toUpperCase() + log.severity.slice(1).toLowerCase()
                          : "Low"
                      }`}
                    >
                      {log.severity}
                    </span>

                    <span
                      style={{
                        fontSize: 10,
                        fontFamily: "var(--font-mono)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-sm)",
                        background: isAI ? "var(--emerald-bg)" : "var(--cyan-bg)",
                        color: isAI ? "var(--emerald-400)" : "var(--cyan-400)",
                      }}
                    >
                      {log.changed_by}
                    </span>
                  </div>

                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                    {new Date(log.timestamp).toLocaleString()}
                  </span>
                </div>

                {/* Sub-row: Issue ID & Validation status */}
                <div style={{ display: "flex", gap: 8, margin: "6px 0 10px 0", flexWrap: "wrap" }}>
                  {log.issue_id && (
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                        fontSize: 10,
                        fontFamily: "var(--font-mono)",
                        color: "var(--violet-400)",
                        background: "rgba(167, 139, 250, 0.12)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-sm)",
                      }}
                    >
                      <Tag size={10} />
                      Issue: {log.issue_id}
                    </span>
                  )}

                  {log.validation_result && (
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                        fontSize: 10,
                        fontFamily: "var(--font-mono)",
                        color: log.validation_result.toUpperCase().includes("PASSED")
                          ? "var(--emerald-400)"
                          : "var(--red-400)",
                        background: log.validation_result.toUpperCase().includes("PASSED")
                          ? "var(--emerald-bg)"
                          : "rgba(239, 68, 68, 0.15)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-sm)",
                      }}
                    >
                      {log.validation_result.toUpperCase().includes("PASSED") ? (
                        <ShieldCheck size={10} />
                      ) : (
                        <ShieldAlert size={10} />
                      )}
                      Validation: {log.validation_result.toUpperCase().includes("PASSED") ? "PASSED" : "FAILED"}
                    </span>
                  )}
                </div>

                <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 12 }}>
                  {log.details || "No details provided"}
                </p>

                {/* Footer action */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 8, borderTop: "1px solid var(--border-subtle)" }}>
                  <span
                    style={{
                      fontSize: 11,
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      color: isRolledBack
                        ? "var(--text-muted)"
                        : isFailed
                        ? "var(--red-400)"
                        : "var(--emerald-400)",
                    }}
                  >
                    {isRolledBack ? (
                      "Rolled Back"
                    ) : isFailed ? (
                      <>
                        <ShieldAlert size={12} /> Failed Repair
                      </>
                    ) : (
                      <>
                        <CheckCircle2 size={12} /> Active
                      </>
                    )}
                  </span>

                  {!isRolledBack && !isFailed ? (
                    <button
                      type="button"
                      disabled={rollingBackId === log.id}
                      onClick={() => void handleRollback(log.id)}
                      className="btn-rollback"
                    >
                      {rollingBackId === log.id ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : (
                        <RotateCcw size={13} />
                      )}
                      <span>Rollback Change</span>
                    </button>
                  ) : (
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        color: isRolledBack ? "var(--text-muted)" : "var(--red-400)",
                        border: isRolledBack ? "1px solid var(--border-subtle)" : "1px solid var(--red-400)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-sm)",
                      }}
                    >
                      {isRolledBack ? "Rolled Back" : "Failed Repair"}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
