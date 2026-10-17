import React, { useState } from "react";
import { Check, X, Send, FileCode, Layers, Upload, AlertCircle } from "lucide-react";
import { logLedgerChange } from "../lib/api";
import type { DebtFinding } from "../lib/types";

type Props = {
  finding: DebtFinding;
  onResolved: () => void;
  onClose: () => void;
  workspaceRoot?: string;
};

export default function ResolutionView({ finding, onResolved, onClose, workspaceRoot }: Props) {
  const [showCustomInput, setShowCustomInput] = useState(false);
  const [customNotes, setCustomNotes] = useState("");
  const [customFileContent, setCustomFileContent] = useState<string | null>(null);
  const [customFileName, setCustomFileName] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const cleanFilePath = finding.file_name.replace(/^file:/, "");
  const plan = finding.structured_plan;

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCustomFileName(file.name);
    const reader = new FileReader();
    reader.onload = (event) => {
      setCustomFileContent((event.target?.result as string) || "");
    };
    reader.readAsText(file);
  };

  const handleResolution = async (followedExact: boolean) => {
    setIsSubmitting(true);
    setFeedback(null);

    const newCode = followedExact
      ? (finding.proposed_code || plan?.proposed_code || "# AI auto-remediation applied\n")
      : (customFileContent || customNotes || "# User custom modifications applied\n");

    const details = followedExact
      ? `Applied AI suggested resolution: ${finding.title || finding.suggested_fix}`
      : (customNotes ? `User Custom Fix: ${customNotes}` : `User uploaded updated file: ${customFileName || cleanFilePath}`);

    try {
      await logLedgerChange({
        file_path: cleanFilePath,
        severity: finding.severity.toLowerCase(),
        changed_by: followedExact ? "AI" : "User",
        details: details,
        previous_code: "Original state recorded in ledger",
        new_code: newCode,
        workspace_root: workspaceRoot,
      });

      setFeedback("✨ Logged successfully to the Smart Ledger!");
      setTimeout(() => {
        onResolved();
      }, 700);
    } catch (err: any) {
      console.error(err);
      setFeedback("Failed to log change. Ensure backend is running on port 8000.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="resolution-panel animate-fade-in">
      <div className="resolution-header">
        <div className="resolution-title">
          <Layers size={18} />
          <span>Resolution Guide</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="header-action-btn"
          aria-label="Close guide"
        >
          <X size={16} />
        </button>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <FileCode size={14} color="var(--cyan-400)" />
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{cleanFilePath}</span>
        </div>
        <span className={`severity-pill ${finding.severity}`}>{finding.severity}</span>
      </div>

      {plan?.blast_radius && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 11,
            color: "var(--amber-400)",
            background: "var(--amber-bg)",
            padding: "5px 10px",
            borderRadius: "var(--radius-sm)",
            marginBottom: 14,
            border: "1px solid rgba(251, 191, 36, 0.25)",
          }}
        >
          <AlertCircle size={13} />
          <span>Blast Radius: {plan.blast_radius}</span>
        </div>
      )}

      {/* Structured Multi-step instructions */}
      <div className="resolution-box">
        <h4 className="resolution-subtitle">Step-by-Step Dependency Resolution:</h4>
        {plan?.steps && plan.steps.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
            {plan.steps.map((st) => (
              <div
                key={st.step_number}
                style={{
                  background: "rgba(255, 255, 255, 0.03)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  padding: "8px 10px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, fontWeight: 600, color: "var(--cyan-400)", marginBottom: 2 }}>
                  <span>Step {st.step_number}: {st.phase}</span>
                  <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>{st.file_name}</span>
                </div>
                <p style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.4 }}>{st.details}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="resolution-instructions">{finding.suggested_fix}</p>
        )}
      </div>

      {feedback && (
        <div
          style={{
            padding: "8px 12px",
            borderRadius: "var(--radius-sm)",
            fontSize: 12,
            marginBottom: 12,
            background: feedback.includes("✨") ? "var(--emerald-bg)" : "var(--red-bg)",
            color: feedback.includes("✨") ? "var(--emerald-400)" : "var(--red-400)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
          }}
        >
          {feedback}
        </div>
      )}

      {!showCustomInput ? (
        <div>
          <p className="prompt-text">Did you implement the changes exactly as suggested?</p>
          <div className="button-row">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleResolution(true)}
              className="btn-yes"
            >
              <Check size={16} /> YES, Exactly
            </button>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => setShowCustomInput(true)}
              className="btn-no"
            >
              <X size={16} /> NO, Custom Changes
            </button>
          </div>
        </div>
      ) : (
        <div className="animate-fade-in">
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>
            Describe what you changed differently or upload your updated Python file:
          </p>

          <textarea
            className="custom-input-area"
            value={customNotes}
            onChange={(e) => setCustomNotes(e.target.value)}
            placeholder="e.g. Renamed user_token instead of token_id and added guard clause..."
          />

          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <label
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontSize: 11,
                fontWeight: 600,
                color: "var(--text-primary)",
                background: "rgba(255, 255, 255, 0.06)",
                border: "1px solid var(--border-medium)",
                padding: "6px 12px",
                borderRadius: "var(--radius-sm)",
                cursor: "pointer",
              }}
            >
              <Upload size={14} color="var(--cyan-400)" />
              <span>{customFileName ? customFileName : "Upload Updated .py"}</span>
              <input
                type="file"
                accept=".py"
                onChange={handleFileUpload}
                style={{ display: "none" }}
              />
            </label>
            {customFileName && (
              <span style={{ fontSize: 10, color: "var(--emerald-400)", fontFamily: "var(--font-mono)" }}>
                ✓ File loaded
              </span>
            )}
          </div>

          <div className="button-row">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleResolution(false)}
              className="btn-yes"
              style={{ background: "var(--cyan-400)", color: "#07090e" }}
            >
              <Send size={15} /> Log Custom Fix to Ledger
            </button>
            <button
              type="button"
              onClick={() => setShowCustomInput(false)}
              className="header-action-btn"
              style={{ fontSize: 12 }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
