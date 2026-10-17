import { useEffect, useState } from "react";
import { History, Loader2, RotateCcw, X, Bot, User, CheckCircle2 } from "lucide-react";
import { errorMessage, fetchLedger, rollbackLedgerChange } from "../lib/api";
import type { LedgerEntry } from "../lib/types";

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

type Props = {
  open: boolean;
  onClose: () => void;
  refreshKey: number;
  workspaceRoot?: string;
};

export default function LedgerPanel({ open, onClose, refreshKey, workspaceRoot }: Props) {
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [rollingBack, setRollingBack] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

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

  async function handleRollback(id: number) {
    const confirmed = window.confirm(
      "Are you sure you want to rollback this change? This will revert the physical file on disk to its previous state."
    );
    if (!confirmed) return;

    setRollingBack(id);
    setError(null);
    try {
      const updated = await rollbackLedgerChange(id, workspaceRoot);
      setEntries((current) => current.map((entry) => (entry.id === id ? updated : entry)));
    } catch (err) {
      setError(errorMessage(err));
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
              <h2 className="ledger-header-title">Smart Ledger & Rollback</h2>
              <p className="ledger-header-subtitle">Time-travel across all AI & User modifications</p>
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
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-muted)", padding: 12 }}>
              <Loader2 size={16} className="animate-spin" color="var(--cyan-400)" />
              <span>Fetching Smart Ledger history…</span>
            </div>
          )}

          {error && <div className="error-banner">{error}</div>}

          {!loading && entries.length === 0 && !error && (
            <div className="empty-state">
              No modifications recorded yet. Any auto-solve or accepted remediation plan will automatically be saved here.
            </div>
          )}

          <div className="timeline">
            {entries.map((entry) => {
              const isRolledBack = entry.status === "rolled_back";
              const isAI = entry.changed_by === "AI";

              return (
                <div key={entry.id} className="timeline-item">
                  <span
                    className="timeline-dot"
                    style={{ borderColor: isRolledBack ? "var(--text-muted)" : "var(--cyan-400)" }}
                  />

                  <div className="ledger-entry-card">
                    <div className="ledger-entry-header">
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          {isAI ? (
                            <Bot size={14} color="var(--emerald-400)" />
                          ) : (
                            <User size={14} color="var(--cyan-400)" />
                          )}
                          <span className="ledger-file-name">{entry.file_path}</span>
                        </div>
                        <p className="ledger-time">{formatTime(entry.timestamp)}</p>
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span className={`severity-pill ${entry.severity ? entry.severity.charAt(0).toUpperCase() + entry.severity.slice(1).toLowerCase() : "Low"}`}>
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

                    {entry.details && (
                      <p style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 8, lineHeight: 1.4 }}>
                        {entry.details}
                      </p>
                    )}

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 10, paddingTop: 8, borderTop: "1px solid var(--border-subtle)" }}>
                      <span
                        style={{
                          fontSize: 11,
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                          color: isRolledBack ? "var(--text-muted)" : "var(--emerald-400)",
                        }}
                      >
                        {isRolledBack ? "Reverted" : <><CheckCircle2 size={12} /> Active</>}
                      </span>

                      <button
                        type="button"
                        disabled={isRolledBack || rollingBack === entry.id}
                        onClick={() => void handleRollback(entry.id)}
                        className="btn-rollback"
                      >
                        {rollingBack === entry.id ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <RotateCcw size={12} />
                        )}
                        <span>{isRolledBack ? "Rolled Back" : "Rollback File"}</span>
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
