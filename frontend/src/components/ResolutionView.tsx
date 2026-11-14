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
  RotateCcw,
  Sparkles,
  Terminal,
  ShieldAlert,
  Loader2,
  FileCheck,
  AlertTriangle,
  ChevronRight,
} from "lucide-react";
import { logLedgerChange, validateRepairTests } from "../lib/api";
import type {
  DebtFinding,
  GuidedRepairPlan,
  RepairStep,
  TestValidationResult,
} from "../lib/types";

type Props = {
  finding: DebtFinding;
  onResolved: () => void;
  onClose: () => void;
  workspaceRoot?: string;
};

export default function ResolutionView({ finding, onResolved, onClose, workspaceRoot }: Props) {
  const cleanFilePath = finding.file_name.replace(/^file:/, "");
  const plan = finding.structured_plan;
  const guidedPlan: GuidedRepairPlan | null = plan?.guided_plan || null;

  // Ordered steps from guidedPlan, or fallback generated steps
  const steps: RepairStep[] = guidedPlan?.ordered_steps || [
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

  // Test validation state
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<TestValidationResult | null>(null);
  const [showConsole, setShowConsole] = useState(false);

  // Custom code input toggle
  const [showCustomInput, setShowCustomInput] = useState(false);
  const [customNotes, setCustomNotes] = useState("");
  const [customFileContent, setCustomFileContent] = useState<string | null>(null);
  const [customFileName, setCustomFileName] = useState<string | null>(null);

  const currentStep = steps[activeStepIndex] || steps[0];

  const handleApplyStep = async (step: RepairStep) => {
    if (step.action_type === "TEST_VALIDATION") {
      await handleRunValidation();
      return;
    }

    // Contract checks and downstream impact reviews are human review steps.
    // Their generated notes are not file contents and must never be written.
    if (step.action_type !== "CORE_REMEDIATION") {
      setAppliedSteps((prev) => ({ ...prev, [step.order]: true }));
      setFeedback(`Review complete for ${step.file_path}; no file was changed.`);
      return;
    }

    setIsSubmitting(true);
    setFeedback(null);
    const codeToApply = stepCodes[step.order] || step.proposed_code;

    try {
      await logLedgerChange({
        file_path: step.file_path,
        severity: finding.severity.toLowerCase(),
        changed_by: "AI",
        details: `Guided Repair Step ${step.order} applied: ${step.action_title}`,
        previous_code: "Original code recorded in ledger",
        new_code: codeToApply,
        workspace_root: workspaceRoot,
      });

      setAppliedSteps((prev) => ({ ...prev, [step.order]: true }));
      setFeedback(`✨ Step ${step.order} applied to ${step.file_path} and logged to Smart Ledger!`);

      // Advance to next step if available
      if (activeStepIndex + 1 < steps.length) {
        setTimeout(() => {
          setActiveStepIndex((prev) => prev + 1);
        }, 600);
      }
    } catch (err: any) {
      console.error(err);
      setFeedback("Failed to write change to disk. Ensure backend is running.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRunValidation = async () => {
    setIsValidating(true);
    setShowConsole(true);
    setValidationResult(null);

    const affectedFiles = Array.from(new Set(steps.map((s) => s.file_path)));
    const overrides: Record<string, string> = {};
    steps.forEach((s) => {
      if (s.action_type === "CORE_REMEDIATION" && stepCodes[s.order]) {
        overrides[s.file_path] = stepCodes[s.order];
      }
    });

    try {
      const res = await validateRepairTests({
        files_to_validate: affectedFiles,
        workspace_root: workspaceRoot,
        code_overrides: overrides,
        run_pytest: true,
      });
      setValidationResult(res);
      if (res.passed) {
        setFeedback("🎉 Automated Test Suite PASSED! Zero regressions detected.");
      } else {
        setFeedback("⚠️ Some tests or syntax checks failed. Check terminal output below.");
      }
    } catch (err) {
      console.error(err);
      setFeedback("Failed to run automated test validation.");
    } finally {
      setIsValidating(false);
    }
  };

  const handleFinalResolution = async (followedExact: boolean) => {
    setIsSubmitting(true);
    setFeedback(null);

    const newCode = followedExact
      ? (stepCodes[2] || finding.proposed_code || plan?.proposed_code || "# AI Guided Repair applied\n")
      : (customFileContent || customNotes || "# User Custom Guided Repair\n");

    const details = followedExact
      ? `Completed Guided Repair Plan for: ${finding.title || finding.suggested_fix}`
      : (customNotes ? `User Custom Fix: ${customNotes}` : `User uploaded updated file: ${customFileName || cleanFilePath}`);

    try {
      await logLedgerChange({
        file_path: cleanFilePath,
        severity: finding.severity.toLowerCase(),
        changed_by: followedExact ? "AI" : "User",
        details: details,
        previous_code: "Original code recorded in ledger",
        new_code: newCode,
        workspace_root: workspaceRoot,
      });

      setFeedback("✨ Repair plan fully completed and logged to Smart Ledger!");
      setTimeout(() => {
        onResolved();
      }, 700);
    } catch (err: any) {
      console.error(err);
      setFeedback("Failed to record final resolution.");
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
          <span>Guided Repair Planner (Module 5)</span>
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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
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

      <div style={{ marginBottom: 12 }}>
        <h3 style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", lineHeight: 1.35 }}>
          {finding.title || finding.description}
        </h3>
        <p style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 3, lineHeight: 1.45 }}>
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
          <span>Blast Radius: {plan.blast_radius}</span>
        </div>
      )}

      {/* SECTION 1: KNOWLEDGE GRAPH ROOT CAUSE & DOWNSTREAM IMPACT */}
      <div className="resolution-section-box">
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
          <ShieldAlert size={14} color="var(--cyan-400)" />
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--cyan-400)", letterSpacing: "0.04em" }}>
            KNOWLEDGE GRAPH ROOT CAUSE & DOWNSTREAM IMPACT
          </span>
        </div>

        {finding.root_cause && (
          <div style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.45, marginBottom: 8 }}>
            <strong style={{ color: "var(--text-primary)" }}>Root Cause:</strong> {finding.root_cause}
          </div>
        )}

        {/* Knowledge Graph Path Visualization */}
        {guidedPlan?.knowledge_graph_path && guidedPlan.knowledge_graph_path.length > 1 && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)", marginBottom: 4 }}>
              DEPENDENCY PROPAGATION PATH:
            </div>
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

        {/* Downstream Impact Table */}
        {guidedPlan?.downstream_impacts && guidedPlan.downstream_impacts.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)", marginBottom: 5 }}>
              DOWNSTREAM IMPACTED COMPONENTS ({guidedPlan.downstream_impacts.length}):
            </div>
            <div className="impact-table-wrap">
              <table className="impact-table">
                <thead>
                  <tr>
                    <th>Component File</th>
                    <th>Depth</th>
                    <th>Impact Level</th>
                  </tr>
                </thead>
                <tbody>
                  {guidedPlan.downstream_impacts.map((imp) => (
                    <tr key={imp.file_path}>
                      <td style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>{imp.file_path}</td>
                      <td>{imp.relationship}</td>
                      <td>
                        <span className={`risk-pill ${imp.risk_level.toLowerCase()}`}>
                          {imp.risk_level} Risk
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* SECTION 2: STRUCTURED ORDERED REPAIR PLAN STEPPER */}
      <div className="resolution-section-box">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <GitCommit size={14} color="var(--emerald-400)" />
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--emerald-400)", letterSpacing: "0.04em" }}>
              STEP-BY-STEP REPAIR PLAN (ORDERED EXECUTION)
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
                onClick={() => setActiveStepIndex(idx)}
              >
                <span className="step-num">{isApplied ? "✓" : `#${st.order}`}</span>
                <span className="step-label">{st.phase_name.split(":")[0]}</span>
              </button>
            );
          })}
        </div>

        {/* Active Step Details */}
        <div className="active-step-card animate-fade-in">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
            <div>
              <h4 style={{ fontSize: 12, fontWeight: 700, color: "var(--cyan-400)" }}>
                {currentStep.phase_name}
              </h4>
              <p style={{ fontSize: 11, fontWeight: 600, color: "var(--text-primary)", marginTop: 2 }}>
                {currentStep.action_title}
              </p>
            </div>
            <span className="affected-pill">{currentStep.file_path}</span>
          </div>

          <p style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.45, marginBottom: 8 }}>
            {currentStep.description}
          </p>

          {/* Reasoning & Risks */}
          <div className="step-meta-box">
            <div style={{ marginBottom: 4 }}>
              <strong style={{ color: "var(--cyan-400)", fontSize: 10.5 }}>ARCHITECTURAL REASONING:</strong>{" "}
              <span style={{ fontSize: 10.5, color: "var(--text-secondary)" }}>{currentStep.reasoning}</span>
            </div>
            <div>
              <strong style={{ color: "var(--amber-400)", fontSize: 10.5 }}>POTENTIAL RISKS:</strong>{" "}
              <span style={{ fontSize: 10.5, color: "var(--text-secondary)" }}>{currentStep.potential_risks}</span>
            </div>
          </div>

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
              disabled={isSubmitting || (currentStep.action_type === "TEST_VALIDATION" && isValidating)}
              onClick={() => handleApplyStep(currentStep)}
              className="btn-apply-step"
            >
              {appliedSteps[currentStep.order] ? (
                <>
                  <CheckCircle2 size={13} color="var(--emerald-400)" />
                  <span>Applied (Re-Apply)</span>
                </>
              ) : (
                <>
                  <Play size={13} />
                  <span>
                    {currentStep.action_type === "CORE_REMEDIATION"
                      ? `Apply Step ${currentStep.order} to Disk & Ledger`
                      : currentStep.action_type === "TEST_VALIDATION"
                        ? "Run Validation Tests"
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

      {/* SECTION 3: TEST VALIDATION & VERIFICATION */}
      <div className="resolution-section-box">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Terminal size={14} color="var(--cyan-400)" />
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--cyan-400)", letterSpacing: "0.04em" }}>
              AUTOMATED TEST VALIDATION & REGRESSION SUITE
            </span>
          </div>
          <button
            type="button"
            disabled={isValidating}
            onClick={() => void handleRunValidation()}
            className="btn-run-tests"
          >
            {isValidating ? (
              <>
                <Loader2 size={13} className="animate-spin" />
                <span>Running Tests…</span>
              </>
            ) : (
              <>
                <Play size={13} />
                <span>Run Validation Tests</span>
              </>
            )}
          </button>
        </div>

        {/* Validation Console Output */}
        {showConsole && (
          <div className="test-console-container animate-fade-in">
            <div className="console-bar">
              <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                TERMINAL VALIDATION OUTPUT
              </span>
              {validationResult && (
                <span className={`status-pill ${validationResult.passed ? "available" : "degraded"}`}>
                  {validationResult.passed ? "PASSED (Zero Regressions)" : "FAILED"}
                </span>
              )}
            </div>
            <pre className="test-console-pre">
              {isValidating
                ? "Compiling AST and executing regression verification tests..."
                : validationResult?.output_log || "Validation initialized."}
            </pre>
          </div>
        )}
      </div>

      {feedback && (
        <div
          style={{
            padding: "8px 12px",
            borderRadius: "var(--radius-sm)",
            fontSize: 12,
            marginBottom: 12,
            background: feedback.includes("✨") || feedback.includes("🎉") ? "var(--emerald-bg)" : "var(--red-bg)",
            color: feedback.includes("✨") || feedback.includes("🎉") ? "var(--emerald-400)" : "var(--red-400)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
          }}
        >
          {feedback}
        </div>
      )}

      {/* FINAL RESOLUTION ACTIONS */}
      {!showCustomInput ? (
        <div style={{ marginTop: 14 }}>
          <p className="prompt-text">Confirm full Guided Repair resolution:</p>
          <div className="button-row">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleFinalResolution(true)}
              className="btn-yes"
            >
              <Check size={16} /> Mark Resolved & Log to Ledger
            </button>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => setShowCustomInput(true)}
              className="btn-no"
            >
              <Upload size={14} /> Custom Changes
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
