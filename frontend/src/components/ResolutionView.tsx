import React, { useState } from "react";
import {
  Check,
  X,
  Send,
  FileCode,
  Layers,
  Upload,
  AlertCircle,
  ArrowRight,
  GitCommit,
  CheckCircle2,
  Play,
  ShieldAlert,
  ChevronRight,
} from "lucide-react";
import { errorMessage, logLedgerChange } from "../lib/api";
import type {
  DebtFinding,
  GuidedRepairPlan,
  RepairStep,
} from "../lib/types";

type Props = {
  finding: DebtFinding;
  onResolved: (resolvedFinding: DebtFinding, updatedFiles?: Record<string, string>) => void;
  onClose: () => void;
  workspaceRoot?: string;
  sourceFiles?: Record<string, string>;
};

export default function ResolutionView({ finding, onResolved, onClose, workspaceRoot, sourceFiles }: Props) {
  const cleanFilePath = finding.file_name.replace(/^file:/, "");
  const plan = finding.structured_plan;
  const guidedPlan: GuidedRepairPlan | null = plan?.guided_plan || null;

  // Ordered steps from guidedPlan, or fallback generated steps
  const plannedSteps: RepairStep[] = guidedPlan?.ordered_steps || [
    {
      order: 1,
      file_path: cleanFilePath,
      phase_name: "Order 1: Interface Contract Preparation",
      action_type: "CONTRACT_VERIFICATION",
      action_title: `Inspect interfaces in ${cleanFilePath}`,
      description: `Verify that changes to resolve '${finding.title || "issue"}' preserve public interfaces and symbol contracts.`,
      proposed_code: `# Contract audit in ${cleanFilePath}\n`,
      diff_summary: `Contract audit in ${cleanFilePath}`,
      reasoning: "Executing contract audit first prevents downstream interface breakages.",
      potential_risks: "Signature divergence breaks callers.",
      status: "pending",
    },
    {
      order: 2,
      file_path: cleanFilePath,
      phase_name: "Order 2: Target File Core Remediation",
      action_type: "CORE_REMEDIATION",
      action_title: `Apply fix in ${cleanFilePath}`,
      description: finding.suggested_fix,
      proposed_code: finding.proposed_code || plan?.proposed_code || `# Fix for ${finding.title}\n`,
      diff_summary: `Fixes ${finding.title}`,
      reasoning: "Remediates the root cause directly in the target component.",
      potential_risks: "Unchecked syntax errors halt module execution.",
      status: "pending",
    },
    {
      order: 3,
      file_path: cleanFilePath,
      phase_name: "Order 3: Automated Test Validation",
      action_type: "TEST_VALIDATION",
      action_title: "Validate syntax, contracts, and regression tests",
      description: "Run AST syntax compilation and regression suite across all affected files.",
      proposed_code: "pytest -v tests/",
      diff_summary: "Automated regression verification",
      reasoning: "Ensures zero regressions before declaring issue resolved.",
      potential_risks: "Silent regressions if tests are not run.",
      status: "pending",
    },
  ];
  const repairSteps = plannedSteps
    .filter((step) => step.action_type !== "TEST_VALIDATION")
    .map((step, index) => ({
      ...step,
      order: index + 1,
      phase_name: step.phase_name.replace(/^(Order|Step)\s+\d+:\s*/i, ""),
    }));
  const steps: RepairStep[] = repairSteps.length > 0 ? repairSteps : [{
    order: 1,
    file_path: cleanFilePath,
    phase_name: "Review resolution",
    action_type: "CONTRACT_VERIFICATION",
    action_title: "Review the proposed resolution",
    description: finding.suggested_fix || finding.description,
    proposed_code: "",
    diff_summary: "Review the proposed resolution",
    reasoning: "Confirm that the resolution addresses the reported issue.",
    potential_risks: "",
    status: "pending",
  }];

  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [appliedSteps, setAppliedSteps] = useState<Record<number, boolean>>({});
  const [stepCodes, setStepCodes] = useState<Record<number, string>>(() => {
    const initial: Record<number, string> = {};
    steps.forEach((s) => {
      initial[s.order] = s.proposed_code || finding.proposed_code || "";
    });
    return initial;
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  // Custom code input toggle
  const [showCustomInput, setShowCustomInput] = useState(false);
  const [customNotes, setCustomNotes] = useState("");
  const [customFileContent, setCustomFileContent] = useState<string | null>(null);
  const [customFileName, setCustomFileName] = useState<string | null>(null);

  const currentStep = steps[activeStepIndex] || steps[0];

  const handleApplyStep = (step: RepairStep) => {
    // Contract checks and downstream impact reviews are human review steps.
    // Their generated notes are not file contents and must never be written.
    if (step.action_type !== "CORE_REMEDIATION") {
      setAppliedSteps((prev) => ({ ...prev, [step.order]: true }));
      setFeedback(`Review complete for ${step.file_path}; no file was changed.`);
      return;
    }

    setAppliedSteps((prev) => ({ ...prev, [step.order]: true }));
    setFeedback(`Step ${step.order} staged. It will be saved with one rollback entry when you resolve this issue.`);
    if (activeStepIndex + 1 < steps.length) {
      setTimeout(() => setActiveStepIndex((prev) => Math.min(prev + 1, steps.length - 1)), 350);
    }
  };

  const handleFinalResolution = async (followedExact: boolean) => {
    setIsSubmitting(true);
    setFeedback(null);

    const fileChangeMap = new Map<string, string>();
    if (followedExact) {
      steps
        .filter((step) => step.action_type === "CORE_REMEDIATION")
        .forEach((step) => fileChangeMap.set(step.file_path, stepCodes[step.order] || step.proposed_code));
    } else if (customFileContent) {
      fileChangeMap.set(cleanFilePath, customFileContent);
    }
    const fileChanges = Array.from(fileChangeMap, ([file_path, new_code]) => ({
      file_path,
      new_code,
      expected_code: sourceFiles?.[file_path],
    }));

    const details = followedExact
      ? `Completed Guided Repair Plan for: ${finding.title || finding.suggested_fix}`
      : (customNotes ? `User Custom Fix: ${customNotes}` : `User uploaded updated file: ${customFileName || cleanFilePath}`);

    try {
      await logLedgerChange({
        file_path: cleanFilePath,
        severity: finding.severity.toLowerCase(),
        changed_by: followedExact ? "AI" : "User",
        issue_id: finding.id || `${finding.file_name}:${finding.line_number ?? 0}`,
        details: details,
        previous_code: "",
        new_code: fileChanges[0]?.new_code || "",
        workspace_root: workspaceRoot,
        file_changes: fileChanges.length ? fileChanges : undefined,
        record_only: fileChanges.length === 0,
      });

      setFeedback(`Repair saved as one combined history entry${fileChanges.length ? ` (${fileChanges.length} file${fileChanges.length === 1 ? "" : "s"})` : ""}.`);
      setTimeout(() => {
        onResolved(finding, Object.fromEntries(fileChangeMap));
      }, 700);
    } catch (err: any) {
      console.error(err);
      setFeedback(errorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="resolution-panel animate-fade-in">
      {/* Header */}
      <div className="resolution-header">
        <div className="resolution-title">
          <Layers size={18} color="var(--cyan-400)" />
          <span>Repair plan</span>
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

      {/* Target & Severity Info */}
      <div className="repair-file-row">
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <FileCode size={14} color="var(--cyan-400)" />
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{cleanFilePath}</span>
          {finding.line_number && <span className="card-line">Line {finding.line_number}</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {finding.category && (
            <span className={`category-pill ${finding.category.toLowerCase().replace(/\s+/g, "-")}`}>
              {finding.category}
            </span>
          )}
          <span className={`severity-pill ${finding.severity}`}>{finding.severity}</span>
        </div>
      </div>

      <div className="repair-issue-summary">
        <h3>
          {finding.title || finding.description}
        </h3>
        <p>
          {finding.description}
        </p>
      </div>

      {/* Blast Radius */}
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
            marginBottom: 12,
            border: "1px solid rgba(251, 191, 36, 0.25)",
          }}
        >
          <AlertCircle size={13} />
          <span>Impact: {plan.blast_radius}</span>
        </div>
      )}

      {/* SECTION 1: KNOWLEDGE GRAPH ROOT CAUSE & DOWNSTREAM IMPACT */}
      <div className="resolution-section-box">
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
          <ShieldAlert size={14} color="var(--cyan-400)" />
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--cyan-400)", letterSpacing: "0.04em" }}>
            Why this issue matters
          </span>
        </div>

        {(finding.root_cause || (guidedPlan?.knowledge_graph_path?.length ?? 0) > 1 || (guidedPlan?.downstream_impacts?.length ?? 0) > 0) && (
          <details className="repair-context-details">
            <summary>Technical details</summary>
            {finding.root_cause && (
              <p className="repair-root-cause"><strong>Root cause:</strong> {finding.root_cause}</p>
            )}
            {guidedPlan?.knowledge_graph_path && guidedPlan.knowledge_graph_path.length > 1 && (
              <div className="repair-context-block">
                <span className="repair-context-label">Dependency path</span>
                <div className="graph-path-pills">
                  {guidedPlan.knowledge_graph_path.map((node, i) => (
                    <React.Fragment key={node}>
                      <span className={`graph-node-pill ${i === 0 ? "target" : ""}`}>
                        {node.split("/").pop()}
                      </span>
                      {i < guidedPlan.knowledge_graph_path.length - 1 && (
                        <ArrowRight size={12} color="var(--text-muted)" />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            )}
            {guidedPlan?.downstream_impacts && guidedPlan.downstream_impacts.length > 0 && (
              <div className="repair-context-block">
                <span className="repair-context-label">Affected components</span>
                <div className="impact-table-wrap">
                  <table className="impact-table">
                    <thead>
                      <tr>
                        <th>Component file</th>
                        <th>Relationship</th>
                        <th>Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {guidedPlan.downstream_impacts.map((imp) => (
                        <tr key={imp.file_path}>
                          <td style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>{imp.file_path}</td>
                          <td>{imp.relationship}</td>
                          <td>
                            <span className={`risk-pill ${imp.risk_level.toLowerCase()}`}>
                              {imp.risk_level}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </details>
        )}
      </div>

      {/* SECTION 2: STRUCTURED ORDERED REPAIR PLAN STEPPER */}
      <div className="resolution-section-box">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <GitCommit size={14} color="var(--emerald-400)" />
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--emerald-400)", letterSpacing: "0.04em" }}>
              Repair steps
            </span>
          </div>
          <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
            Step {activeStepIndex + 1} of {steps.length}
          </span>
        </div>

        {/* Stepper Tabs */}
        <div className="plan-stepper-tabs">
          {steps.map((st, idx) => {
            const isApplied = appliedSteps[st.order];
            const isActive = activeStepIndex === idx;
            return (
              <button
                key={st.order}
                type="button"
                className={`stepper-tab-btn ${isActive ? "active" : ""} ${isApplied ? "applied" : ""}`}
                aria-label={`Step ${st.order}: ${st.phase_name}`}
                onClick={() => setActiveStepIndex(idx)}
              >
                <span className="step-num" aria-hidden="true">{isApplied ? "✓" : st.order}</span>
              </button>
            );
          })}
        </div>

        {/* Active Step Details */}
        <div className="active-step-card animate-fade-in">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
            <div>
              <span className="active-step-eyebrow">Step {currentStep.order}</span>
              <h4 className="active-step-title">{currentStep.action_title}</h4>
            </div>
            <span className="affected-pill">{currentStep.file_path}</span>
          </div>

          <p style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.45, marginBottom: 8 }}>
            {currentStep.description}
          </p>

          {/* Reasoning & Risks */}
          <details className="step-rationale-details">
            <summary>Reasoning and risk</summary>
            <div className="step-meta-box">
              <p><strong>Reason:</strong> {currentStep.reasoning}</p>
              <p><strong>Risk:</strong> {currentStep.potential_risks}</p>
            </div>
          </details>

          {/* Code / Action Editor */}
          {currentStep.action_type === "CORE_REMEDIATION" && currentStep.proposed_code && (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)" }}>
                  PROPOSED CODE / CHANGES:
                </span>
                <span style={{ fontSize: 9.5, color: "var(--text-muted)" }}>Editable</span>
              </div>
              <textarea
                value={stepCodes[currentStep.order] ?? currentStep.proposed_code}
                onChange={(e) =>
                  setStepCodes((prev) => ({ ...prev, [currentStep.order]: e.target.value }))
                }
                className="step-code-textarea"
                rows={5}
              />
            </div>
          )}

          {/* Action button for this step */}
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleApplyStep(currentStep)}
              className="btn-apply-step"
            >
              {appliedSteps[currentStep.order] ? (
                <>
                  <CheckCircle2 size={13} color="var(--emerald-400)" />
                  <span>Staged (update)</span>
                </>
              ) : (
                <>
                  <Play size={13} />
                  <span>
                    {currentStep.action_type === "CORE_REMEDIATION"
                      ? `Stage Step ${currentStep.order}`
                      : "Mark Review Complete"}
                  </span>
                </>
              )}
            </button>
            {activeStepIndex + 1 < steps.length && (
              <button
                type="button"
                onClick={() => setActiveStepIndex((prev) => prev + 1)}
                className="btn-secondary"
                style={{ fontSize: 11, padding: "5px 10px" }}
              >
                <span>Next Step</span>
                <ChevronRight size={13} />
              </button>
            )}
          </div>
        </div>
      </div>

      {feedback && (
        <div
          style={{
            padding: "8px 12px",
            borderRadius: "var(--radius-sm)",
            fontSize: 12,
            marginBottom: 12,
            background: feedback.includes("✨") || feedback.includes("🎉") || feedback.includes("staged") || feedback.includes("Review complete") || feedback.includes("Repair saved") ? "var(--emerald-bg)" : "var(--red-bg)",
            color: feedback.includes("✨") || feedback.includes("🎉") || feedback.includes("staged") || feedback.includes("Review complete") || feedback.includes("Repair saved") ? "var(--emerald-400)" : "var(--red-400)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
          }}
        >
          {feedback}
        </div>
      )}

      {/* FINAL RESOLUTION ACTIONS */}
      {!showCustomInput ? (
        <div style={{ marginTop: 14 }}>
          <p className="prompt-text">Finish this repair</p>
          <div className="button-row">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleFinalResolution(true)}
              className="btn-yes"
            >
              <Check size={16} /> Resolve issue
            </button>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => setShowCustomInput(true)}
              className="btn-no"
            >
              <Upload size={14} /> Record another fix
            </button>
          </div>
        </div>
      ) : (
        <div className="animate-fade-in" style={{ marginTop: 14 }}>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>
            Describe what you changed differently or upload your updated Python file:
          </p>

          <textarea
            className="custom-input-area"
            value={customNotes}
            onChange={(e) => setCustomNotes(e.target.value)}
            placeholder="e.g. Renamed user_token instead of token_id and added guard clause..."
          />

          <label style={{ display: "block", margin: "8px 0", fontSize: 11, color: "var(--text-secondary)" }}>
            Or upload the updated Python file
            <input
              type="file"
              accept=".py,text/x-python,text/plain"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                if (!file) return;
                setCustomFileName(file.name);
                const reader = new FileReader();
                reader.onload = () => setCustomFileContent(String(reader.result ?? ""));
                reader.onerror = () => setFeedback("Could not read the selected file.");
                reader.readAsText(file);
              }}
            />
            {customFileName && <span style={{ marginLeft: 8 }}>{customFileName}</span>}
          </label>

          <div className="button-row">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleFinalResolution(false)}
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
