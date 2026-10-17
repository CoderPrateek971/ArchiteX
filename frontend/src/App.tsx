import { useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  History,
  Loader2,
  ShieldAlert,
  Sparkles,
  Upload,
  Workflow,
  FileCode,
} from "lucide-react";

import ArchitectureCanvas from "./components/ArchitectureCanvas";
import LedgerPanel from "./components/LedgerPanel";
import ResolutionView from "./components/ResolutionView";
import { analyzeDebt, errorMessage, logLedgerChange, uploadRepo } from "./lib/api";
import type { DebtFinding, GraphPayload, Severity } from "./lib/types";

const TABS: Severity[] = ["High", "Medium", "Low"];

export default function App() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [findings, setFindings] = useState<DebtFinding[]>([]);
  const [tab, setTab] = useState<Severity>("High");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [activeFinding, setActiveFinding] = useState<DebtFinding | null>(null);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledgerRefresh, setLedgerRefresh] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoSolvingId, setAutoSolvingId] = useState<string | null>(null);

  const counts = useMemo(() => {
    return {
      High: findings.filter((f) => f.severity === "High").length,
      Medium: findings.filter((f) => f.severity === "Medium").length,
      Low: findings.filter((f) => f.severity === "Low").length,
    };
  }, [findings]);

  const visibleFindings = findings.filter((f) => f.severity === tab);

  async function handleFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setError("Please upload a .zip archive of a Python repository.");
      return;
    }

    setError(null);
    setFileName(file.name);
    setUploading(true);
    setFindings([]);
    setSelectedPath(null);
    setActiveFinding(null);

    try {
      const nextGraph = await uploadRepo(file);
      setGraph(nextGraph);
      setUploading(false);
      setAnalyzing(true);

      try {
        const report = await analyzeDebt(nextGraph);
        const incoming = report.findings || [];
        setFindings(incoming);

        // Auto-switch to tab with findings if current tab is empty
        if (incoming.length > 0) {
          const highCount = incoming.filter((f) => f.severity === "High").length;
          const medCount = incoming.filter((f) => f.severity === "Medium").length;
          if (highCount > 0) setTab("High");
          else if (medCount > 0) setTab("Medium");
          else setTab("Low");
        }
      } catch (debtError) {
        setError(errorMessage(debtError));
      }
    } catch (uploadError) {
      setGraph(null);
      setError(errorMessage(uploadError));
    } finally {
      setUploading(false);
      setAnalyzing(false);
    }
  }

  // Handle AI Auto-Solving for Low Severity Issues
  const handleAutoSolve = async (finding: DebtFinding) => {
    const cleanFileName = finding.file_name.replace(/^file:/, "");
    const findingKey = `${finding.file_name}-${finding.line_number ?? 0}`;
    setAutoSolvingId(findingKey);

    const proposedCode =
      finding.proposed_code ||
      (finding.structured_plan ? finding.structured_plan.proposed_code : "") ||
      `# [ArchiteX Auto-Solve] Resolved ${finding.title || "Low severity debt"}\n`;

    try {
      await logLedgerChange({
        file_path: cleanFileName,
        severity: finding.severity.toLowerCase(),
        changed_by: "AI",
        details: `AI Auto-Solved: ${finding.title || finding.suggested_fix}`,
        previous_code: "Original code prior to auto-solve",
        new_code: proposedCode,
        workspace_root: graph?.repo_root,
      });

      // Remove the solved issue from the list
      setFindings((prev) =>
        prev.filter((f) => !(f.file_name === finding.file_name && f.line_number === finding.line_number))
      );
      setLedgerRefresh((prev) => prev + 1);
    } catch (err) {
      console.error(err);
      alert("Failed to record fix in ledger. Please check backend status.");
    } finally {
      setAutoSolvingId(null);
    }
  };

  return (
    <div className="app-container">
      {/* Left Sidebar */}
      <aside className="sidebar">
        {/* Header */}
        <div className="sidebar-header">
          <div className="brand-wrapper">
            <span className="brand-icon">
              <Workflow size={20} />
            </span>
            <div>
              <h1 className="brand-title">ArchiteX</h1>
              <p className="brand-subtitle">AI Architecture Intelligence</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setLedgerOpen(true)}
            className="header-action-btn"
            title="Open Smart Ledger History"
            aria-label="Open history ledger"
          >
            <History size={18} />
          </button>
        </div>

        {/* Upload Zone */}
        <div className="upload-section">
          <div className="section-label">
            <span>Repository Ingestion</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>PYTHON</span>
          </div>

          <div
            className={`dropzone ${dragOver ? "drag-active" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const file = e.dataTransfer.files[0];
              if (file) void handleFile(file);
            }}
          >
            {uploading ? (
              <Loader2 size={26} className="dropzone-icon animate-spin" />
            ) : (
              <Upload size={26} className="dropzone-icon" />
            )}
            <p className="dropzone-title">
              {uploading ? "Ingesting & Mapping AST…" : "Drop a Python repo (.zip)"}
            </p>
            <p className="dropzone-subtitle">or click to browse filesystem</p>

            {fileName && <div className="active-file-pill">{fileName}</div>}
          </div>

          <input
            ref={inputRef}
            type="file"
            accept=".zip,application/zip"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
              e.target.value = "";
            }}
          />
        </div>

        {/* Debt Triage */}
        <div className="triage-section">
          <div className="section-label">
            <span>Technical Debt Triage</span>
            {analyzing && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "var(--cyan-400)", fontSize: 10 }}>
                <Sparkles size={11} /> Analyzing
              </span>
            )}
          </div>

          <div className="tabs-container">
            {TABS.map((item) => (
              <button
                key={item}
                type="button"
                data-severity={item}
                className={`tab-btn ${tab === item ? "active" : ""}`}
                onClick={() => setTab(item)}
              >
                <span>{item}</span>
                <span className="tab-badge">{counts[item]}</span>
              </button>
            ))}
          </div>

          <div className="findings-list">
            {error && <div className="error-banner">{error}</div>}

            {!graph && !uploading && (
              <p className="empty-state">
                Upload a Python repository zip to build the knowledge graph and detect architectural & syntax debt.
              </p>
            )}

            {graph && !analyzing && visibleFindings.length === 0 && (
              <p className="empty-state">No {tab.toLowerCase()} severity issues identified in this codebase.</p>
            )}

            {visibleFindings.map((finding, idx) => {
              const cleanPath = finding.file_name.replace(/^file:/, "");
              const isSelected = selectedPath === finding.file_name;
              const findingKey = `${finding.file_name}-${finding.line_number ?? idx}`;
              const isSolvingThis = autoSolvingId === findingKey;

              return (
                <div
                  key={findingKey}
                  className={`debt-card ${isSelected ? "selected" : ""}`}
                  onClick={() => {
                    setSelectedPath(finding.file_name);
                    if (finding.severity === "Medium" || finding.severity === "High") {
                      setActiveFinding(finding);
                    } else {
                      setActiveFinding(null);
                    }
                  }}
                >
                  <div className="card-header">
                    <div className="card-title-group">
                      <FileCode size={13} color="var(--cyan-400)" />
                      <span className="card-file" title={cleanPath}>{cleanPath}</span>
                      {finding.line_number && (
                        <span className="card-line">L{finding.line_number}</span>
                      )}
                    </div>
                    <span className={`severity-pill ${finding.severity}`}>
                      {finding.severity}
                    </span>
                  </div>

                  <p className="card-desc">
                    {finding.description || finding.title}
                  </p>

                  <div className="card-action-box" onClick={(e) => e.stopPropagation()}>
                    {finding.severity === "Low" ? (
                      <div>
                        <p className="fix-preview-text">
                          <strong style={{ color: "var(--emerald-400)" }}>AI Solution:</strong>{" "}
                          {finding.suggested_fix}
                        </p>
                        <button
                          type="button"
                          disabled={isSolvingThis}
                          onClick={() => void handleAutoSolve(finding)}
                          className="btn-auto-solve"
                        >
                          {isSolvingThis ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <Sparkles size={13} />
                          )}
                          <span>{isSolvingThis ? "Applying fix…" : "Auto-Solve with AI"}</span>
                        </button>
                      </div>
                    ) : (
                      <div>
                        <p className="fix-preview-text">
                          <strong style={{ color: "var(--cyan-400)" }}>Remediation:</strong>{" "}
                          {finding.suggested_fix}
                        </p>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedPath(finding.file_name);
                            setActiveFinding(finding);
                          }}
                          className="btn-guide"
                        >
                          Open Resolution Guide
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </aside>

      {/* Main Graph Area */}
      <main className="main-canvas-area">
        <div className="canvas-floating-badge">
          <ShieldAlert size={14} color="var(--cyan-400)" />
          <span>Knowledge Graph Canvas</span>
          {graph && (
            <span style={{ opacity: 0.85 }}>
              · {graph.nodes.length} nodes · {graph.edges.length} edges
            </span>
          )}
        </div>

        {graph ? (
          <ArchitectureCanvas
            graphNodes={graph.nodes}
            graphEdges={graph.edges}
            selectedPath={selectedPath}
          />
        ) : (
          <div className="canvas-empty">
            <span className="canvas-empty-icon">
              <AlertTriangle size={26} />
            </span>
            <h3 className="canvas-empty-title">No Knowledge Graph Loaded</h3>
            <p className="canvas-empty-desc">
              Upload any Python project archive (.zip) on the left panel to map file hierarchies, classes, functions, and import dependencies.
            </p>
          </div>
        )}

        {/* Floating Resolution Guide */}
        {activeFinding && (
          <ResolutionView
            finding={activeFinding}
            workspaceRoot={graph?.repo_root}
            onClose={() => setActiveFinding(null)}
            onResolved={() => {
              setActiveFinding(null);
              setLedgerRefresh((prev) => prev + 1);
            }}
          />
        )}

        {/* Smart Ledger History Panel */}
        <LedgerPanel
          open={ledgerOpen}
          onClose={() => setLedgerOpen(false)}
          refreshKey={ledgerRefresh}
          workspaceRoot={graph?.repo_root}
        />
      </main>
    </div>
  );
}
