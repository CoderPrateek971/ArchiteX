import { useEffect, useState } from "react";
import { RotateCcw, User, Bot } from "lucide-react";
import { fetchLedger, rollbackLedgerChange, errorMessage } from "../lib/api";
import type { LedgerEntry } from "../lib/types";

export default function LedgerHistory() {
  const [logs, setLogs] = useState<LedgerEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

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
      "Are you sure you want to rollback this change? This will revert the file to its previous state."
    );
    if (!confirm) return;

    try {
      await rollbackLedgerChange(id);
      alert("Rollback successful! File reverted.");
      void loadLogs();
    } catch (err) {
      alert("Rollback failed: " + errorMessage(err));
    }
  };

  return (
    <div style={{ padding: 24, height: "100%", overflowY: "auto", color: "var(--text-primary)" }}>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: "var(--violet-400)", marginBottom: 16 }}>
        Smart Ledger & Rollback
      </h2>

      {error && <div className="error-banner">{error}</div>}

      {logs.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontStyle: "italic" }}>
          No changes have been logged yet.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {logs.map((log) => (
            <div
              key={log.id}
              style={{
                background: "var(--bg-card)",
                padding: 16,
                borderRadius: "var(--radius-md)",
                borderLeft: "4px solid var(--violet-400)",
                borderTop: "1px solid var(--border-subtle)",
                borderRight: "1px solid var(--border-subtle)",
                borderBottom: "1px solid var(--border-subtle)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {log.changed_by === "AI" ? (
                    <Bot size={18} color="var(--emerald-400)" />
                  ) : (
                    <User size={18} color="var(--cyan-400)" />
                  )}
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{log.file_path}</span>
                </div>
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  {new Date(log.timestamp).toLocaleString()}
                </span>
              </div>

              <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 12 }}>
                {log.details || "No details provided"}
              </p>

              {log.status !== "rolled_back" ? (
                <button
                  type="button"
                  onClick={() => void handleRollback(log.id)}
                  className="btn-rollback"
                >
                  <RotateCcw size={13} />
                  <span>Rollback Change</span>
                </button>
              ) : (
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    color: "var(--red-400)",
                    border: "1px solid var(--red-400)",
                    padding: "2px 6px",
                    borderRadius: "var(--radius-sm)",
                  }}
                >
                  Rolled Back
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
