import { useEffect, useState } from "react";
import {
  History,
  Loader2,
  RotateCcw,
  X,
  Bot,
  User,
  CheckCircle2,
  AlertTriangle,
  FileCode,
  Tag,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";
import { errorMessage, fetchLedger, rollbackLedgerChange } from "../lib/api";
import type { DebtFinding, LedgerEntry } from "../lib/types";

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

type Props = {
  open: boolean;
  onClose: () => void;
  refreshKey: number;
  findings?: DebtFinding[];
  onRollback?: (entry: LedgerEntry) => Promise<string>;
};

export default function LedgerPanel({ open, onClose, refreshKey, findings = [], onRollback }: Props) {
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [rollingBack, setRollingBack] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rollbackNotice, setRollbackNotice] = useState<string | null>(null);
  const [conflictWarning, setConflictWarning] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setRollbackNotice(null);
    setConflictWarning(null);

    fetchLedger()
      .then((data) => {
        if (!cancelled) setEntries(data);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, refreshKey]);

  async function handleRollback(entry: LedgerEntry, issue?: DebtFinding) {
    const issueLabel = issue?.title || entry.issue_id || "Unlabeled change";
    const issueDescription = issue?.description || entry.details;
    const isRollbackAction = entry.rollback_ref != null;
    const actionLabel = isRollbackAction ? "Undo this rollback action" : "Rollback this change";
    const confirmed = window.confirm(
      `${actionLabel} #${entry.id} for “${issueLabel}”${issueDescription ? `?\n\n${issueDescription}` : "?"}${isRollbackAction ? `\n\nThis entry reverses ledger change #${entry.rollback_ref}.` : ""}\n\nFile: ${entry.file_path}\n\nArchiteX will check for newer edits before restoring this file.`
    );
    if (!confirmed) return;

    setRollingBack(entry.id);
    setError(null);
    setConflictWarning(null);
    setRollbackNotice(null);
    try {
      // Ledger paths point to the workspace where each change was made. Do not
      // pass the currently selected repository root, which may be a different upload.
      await rollbackLedgerChange(entry.id);
      setRollbackNotice(
        (await onRollback?.(entry)) || `Change #${entry.id} rolled back in the ArchiteX workspace.`
      );
      try {
        setEntries(await fetchLedger());
      } catch (refreshError) {
        setError(`Rollback completed, but the ledger could not refresh: ${errorMessage(refreshError)}`);
      }
    } catch (err: any) {
      const msg = errorMessage(err);
      if (err?.response?.status === 409 || msg.toLowerCase().includes("conflict")) {
        setConflictWarning(
          `Rollback Blocked (Conflict Detected): ${msg}. The file has newer modifications that would be lost. ArchiteX prevented overwriting your changes.`
        );
      } else {
        setError(msg);
      }
    } finally {
      setRollingBack(null);
    }
  }

  if (!open) return null;

  return (
    <div className="ledger-backdrop" onClick={onClose}>
      <aside className="ledger-sidebar" onClick={(e) => e.stopPropagation()}>
        <header className="ledger-header">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                width: 32,
                height: 32,
                borderRadius: "var(--radius-md)",
                background: "var(--cyan-bg)",
                color: "var(--cyan-400)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <History size={16} />
            </span>
            <div>
              <h2 className="ledger-header-title">Audit Ledger & Rollback Engine</h2>
              <p className="ledger-header-subtitle">
                Issue attribution, selective rollback & conflict protection
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="header-action-btn"
            aria-label="Close ledger"
          >
            <X size={16} />
          </button>
        </header>

        <div className="ledger-body">
          {loading && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 13,
                color: "var(--text-muted)",
                padding: 12,
              }}
            >
              <Loader2 size={16} className="animate-spin" color="var(--cyan-400)" />
              <span>Fetching Smart Ledger history…</span>
            </div>
          )}

          {/* Prominent Conflict Warning Banner */}
          {conflictWarning && (
            <div
              style={{
                padding: "10px 14px",
                marginBottom: 12,
                borderRadius: "var(--radius-sm)",
                background: "rgba(239, 68, 68, 0.15)",
                border: "1px solid var(--red-400)",
                color: "var(--red-400)",
                fontSize: 12,
                display: "flex",
                gap: 10,
                alignItems: "flex-start",
                lineHeight: 1.4,
              }}
            >
              <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 1 }} />
              <div>
                <strong style={{ display: "block", marginBottom: 2 }}>
                  Rollback Conflict Detected
                </strong>
                <span>{conflictWarning}</span>
              </div>
            </div>
          )}

          {error && <div className="error-banner">{error}</div>}
          {rollbackNotice && <div className="ledger-rollback-notice" role="status">{rollbackNotice}</div>}

          {!loading && entries.length === 0 && !error && (
            <div className="empty-state">
              No modifications recorded yet. Any automatic repair, developer edit, or accepted
              remediation plan will automatically be saved here.
            </div>
          )}

          <div className="timeline">
            {entries.map((entry) => {
              const isRolledBack = entry.status === "rolled_back";
              const isFailed = entry.status === "failed";
              const isAI = entry.changed_by === "AI";
              const cleanPath = entry.file_path.replace(/^file:/, "");
              const fileChanges = entry.file_changes || [];
              const displayPath = fileChanges.length > 1
                ? `${fileChanges.length} files changed`
                : cleanPath.split("/").slice(-2).join("/");
              const pathTitle = fileChanges.length
                ? fileChanges.map((change) => change.file_path).join("\n")
                : cleanPath;
              const issue = findings.find((finding) => finding.id?.toLowerCase() === entry.issue_id?.toLowerCase());
              const completedIssueTitle = entry.details?.match(/^Completed Guided Repair Plan for:\s*(.+)$/)?.[1];
              const validation = entry.validation_result?.trim().toUpperCase() || "";
              const validationNotRun = validation === "NOT_RUN" || validation === "PENDING_REVIEW";
              const validationPassed = validation.includes("PASSED");
              const validationLabel = validation === "PENDING_REVIEW" ? "Pending review" : validation === "NOT_RUN" ? "Not run" : validationPassed ? "Passed" : "Failed";

              return (
                <div key={entry.id} className="timeline-item">
                  <span
                    className="timeline-dot"
                    style={{
                      borderColor: isRolledBack
                        ? "var(--text-muted)"
                        : isFailed
                        ? "var(--red-400)"
                        : "var(--cyan-400)",
                    }}
                  />

                  <div className="ledger-entry-card">
                    {/* Header: Change ID, File Path, Source & Timestamp */}
                    <div className="ledger-entry-header">
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
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
                            #{entry.id}
                          </span>
                          {isAI ? (
                            <Bot size={14} color="var(--emerald-400)" />
                          ) : (
                            <User size={14} color="var(--cyan-400)" />
                          )}
                          <span className="ledger-file-name" title={pathTitle}>
                            {displayPath}
                          </span>
                        </div>
                        <p className="ledger-time">{formatTime(entry.timestamp)}</p>
                      </div>

                      {/* Badges: Severity and Changed-By */}
                      <div className="ledger-entry-badges">
                        <span
                          className={`severity-pill ${
                            entry.severity
                              ? entry.severity.charAt(0).toUpperCase() +
                                entry.severity.slice(1).toLowerCase()
                              : "Low"
                          }`}
                        >
                          {entry.severity}
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
                          {entry.changed_by}
                        </span>
                      </div>
                    </div>

                    {/* Issue ID and Validation Badges */}
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        margin: "6px 0 8px 0",
                        flexWrap: "wrap",
                      }}
                    >
                      {entry.issue_id && (
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
                          Issue: {entry.issue_id}
                        </span>
                      )}

                      {entry.validation_result && (
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            fontSize: 10,
                            fontFamily: "var(--font-mono)",
                            color: validationPassed
                              ? "var(--emerald-400)"
                              : validationNotRun
                                ? "var(--text-muted)"
                                : "var(--red-400)",
                            background: validationPassed
                              ? "var(--emerald-bg)"
                              : validationNotRun
                                ? "rgba(148, 163, 184, 0.1)"
                                : "rgba(239, 68, 68, 0.15)",
                            padding: "2px 6px",
                            borderRadius: "var(--radius-sm)",
                          }}
                          title={entry.validation_result}
                        >
                          {validationPassed ? (
                            <ShieldCheck size={10} />
                          ) : (
                            <ShieldAlert size={10} />
                          )}
                          Validation: {validationLabel}
                        </span>
                      )}
                    </div>

                    {(issue || entry.issue_id || entry.details || fileChanges.length > 0) && (
                      <div className="ledger-issue-context">
                        <strong>{issue?.title || completedIssueTitle || (entry.issue_id ? `Issue ${entry.issue_id}` : "Change details")}</strong>
                        <span className="ledger-issue-description">{issue?.description || (completedIssueTitle ? "Resolution recorded in history." : fileChanges.length ? "One combined change includes a saved before and after version for each file." : entry.details) || "No issue description was saved for this older change."}</span>
                        {(entry.details || fileChanges.length > 0) && (
                          <details className="ledger-change-details">
                            <summary>{fileChanges.length ? `Change details · ${fileChanges.length} file${fileChanges.length === 1 ? "" : "s"}` : "Change details"}</summary>
                            {entry.details && <span>{entry.details}</span>}
                            {fileChanges.map((change) => (
                              <div className="ledger-file-snapshot" key={change.file_path}>
                                <strong>{change.file_path.split("/").slice(-2).join("/")}</strong>
                                <div className="ledger-snapshot-columns">
                                  <div>
                                    <span>Previous</span>
                                    <pre>{change.previous_code}</pre>
                                  </div>
                                  <div>
                                    <span>Saved</span>
                                    <pre>{change.new_code}</pre>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </details>
                        )}
                      </div>
                    )}

                    {/* Footer: Status Badge and Selective Rollback Action */}
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        marginTop: 10,
                        paddingTop: 8,
                        borderTop: "1px solid var(--border-subtle)",
                      }}
                    >
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

                      <button
                        type="button"
                        disabled={isRolledBack || isFailed || rollingBack === entry.id}
                        onClick={() => void handleRollback(entry, issue)}
                        className="btn-rollback"
                        title={
                          isRolledBack
                            ? "This change has already been rolled back"
                            : isFailed
                            ? "Cannot roll back a failed repair attempt"
                            : entry.rollback_ref != null
                            ? `Undo this rollback action (ledger change #${entry.rollback_ref})`
                            : fileChanges.length > 1
                              ? `Roll back all ${fileChanges.length} files in this combined repair`
                              : "Selectively rollback this modification with conflict detection"
                        }
                      >
                        {rollingBack === entry.id ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <RotateCcw size={12} />
                        )}
                        <span>
                          {isRolledBack ? "Rolled Back" : isFailed ? "Failed" : entry.rollback_ref != null ? "Undo Rollback" : fileChanges.length > 1 ? "Rollback Change" : "Rollback File"}
                        </span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </aside>
    </div>
  );
}
