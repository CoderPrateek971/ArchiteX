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
  GitBranch,
  Globe,
  RotateCcw,
  BookOpen,
  MessageSquare,
  Layers,
  X,
  Box,
} from "lucide-react";

import ArchitectureCanvas from "./components/ArchitectureCanvas";
import ArchitectureView from "./components/ArchitectureView";
import CodebaseChatDrawer from "./components/CodebaseChatDrawer";
import LedgerPanel from "./components/LedgerPanel";
import OnboardingModal from "./components/OnboardingModal";
import ResolutionView from "./components/ResolutionView";
import {
  analyzeDebt,
  cloneRepo,
  deleteWorkspace,
  errorMessage,
  explainArchitecture,
  generateOnboarding,
  logLedgerChange,
  uploadRepo,
} from "./lib/api";
import type {
  ArchitectureReport,
  DebtFinding,
  GraphNode,
  GraphPayload,
  OnboardingDocResponse,
  Severity,
} from "./lib/types";

const TABS: Severity[] = ["High", "Medium", "Low"];

export default function App() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [sourceMode, setSourceMode] = useState<"zip" | "git">("zip");
  const [gitUrl, setGitUrl] = useState("");
  const [gitBranch, setGitBranch] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [findings, setFindings] = useState<DebtFinding[]>([]);
  const [tab, setTab] = useState<Severity>("High");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [activeFinding, setActiveFinding] = useState<DebtFinding | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledgerRefresh, setLedgerRefresh] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoSolvingId, setAutoSolvingId] = useState<string | null>(null);

  // Architecture & Onboarding & Chat States
  const [sidebarMode, setSidebarMode] = useState<"debt" | "architecture">("debt");
  const [archReport, setArchReport] = useState<ArchitectureReport | null>(null);
  const [loadingArch, setLoadingArch] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [onboardingDoc, setOnboardingDoc] = useState<OnboardingDocResponse | null>(null);
  const [loadingOnboarding, setLoadingOnboarding] = useState(false);
  const [onboardingError, setOnboardingError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  const counts = useMemo(() => {
    return {
      High: findings.filter((f) => f.severity === "High").length,
      Medium: findings.filter((f) => f.severity === "Medium").length,
      Low: findings.filter((f) => f.severity === "Low").length,
    };
  }, [findings]);

  const visibleFindings = findings.filter((f) => f.severity === tab);

  async function processIngestedGraph(nextGraph: GraphPayload, label: string) {
    setGraph(nextGraph);
    setFileName(label);
    setUploading(false);
    setAnalyzing(true);
    setLoadingArch(true);
    setOnboardingDoc(null);
    setSelectedNode(null);

    // 1. Analyze Debt
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
    } finally {
      setAnalyzing(false);
    }

    // 2. Synthesize Architecture & File Responsibilities & Data Flow
    try {
      const arch = await explainArchitecture(nextGraph);
      setArchReport(arch);
    } catch (archErr) {
      console.warn("Architecture explanation error:", archErr);
    } finally {
      setLoadingArch(false);
    }

    // 3. Pre-fetch Onboarding Guide in background for instantaneous access
    generateOnboarding(nextGraph)
      .then((doc) => setOnboardingDoc(doc))
      .catch((err) => console.info("Background onboarding prefetch:", err));
  }

  async function handleFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setError("Please upload a .zip archive of a Python repository.");
      return;
    }

    setError(null);
    setUploading(true);
    setFindings([]);
    setSelectedPath(null);
    setActiveFinding(null);

    try {
      const nextGraph = await uploadRepo(file);
      await processIngestedGraph(nextGraph, file.name);
    } catch (uploadError) {
      setGraph(null);
      setError(errorMessage(uploadError));
    } finally {
      setUploading(false);
    }
  }

  async function handleGitClone(e: React.FormEvent) {
    e.preventDefault();
    const cleanUrl = gitUrl.trim();
    if (!cleanUrl) {
      setError("Please enter a valid Git repository URL.");
      return;
    }

    setError(null);
    setUploading(true);
    setFindings([]);
    setSelectedPath(null);
    setActiveFinding(null);

    try {
      const nextGraph = await cloneRepo(cleanUrl, gitBranch.trim() || undefined);
      const cleanRepoName = cleanUrl.split("/").pop()?.replace(/\.git$/, "") || "git-repo";
      const displayName = gitBranch.trim() ? `${cleanRepoName} (${gitBranch.trim()})` : cleanRepoName;
      await processIngestedGraph(nextGraph, displayName);
    } catch (cloneError) {
      setGraph(null);
      setError(errorMessage(cloneError));
    } finally {
      setUploading(false);
    }
  }

  // Handle Complete Repository Reset
  const handleReset = async () => {
    const currentWorkspaceId = graph?.workspace_id;
    setGraph(null);
    setFileName(null);
    setFindings([]);
    setSelectedPath(null);
    setActiveFinding(null);
    setSelectedNode(null);
    setError(null);
    setGitUrl("");
    setGitBranch("");
    setArchReport(null);
    setOnboardingDoc(null);
    setOnboardingError(null);
    setSidebarMode("debt");

    if (inputRef.current) {
      inputRef.current.value = "";
    }

    if (currentWorkspaceId) {
      await deleteWorkspace(currentWorkspaceId);
    }
  };

  // Open Onboarding Guide
  const handleOpenOnboarding = async () => {
    if (!graph) {
      setError("Please upload a ZIP archive or connect a Git repository first to generate an onboarding guide.");
      return;
    }
    setOnboardingOpen(true);
    setOnboardingError(null);
    if (!onboardingDoc && !loadingOnboarding) {
      setLoadingOnboarding(true);
      try {
        const doc = await generateOnboarding(graph);
        setOnboardingDoc(doc);
      } catch (err) {
        setOnboardingError(errorMessage(err));
      } finally {
        setLoadingOnboarding(false);
      }
    }
  };

  const handleRegenerateOnboarding = async () => {
    if (!graph) return;
    setLoadingOnboarding(true);
    setOnboardingError(null);
    try {
      const doc = await generateOnboarding(graph);
      setOnboardingDoc(doc);
    } catch (err) {
      setOnboardingError(errorMessage(err));
    } finally {
      setLoadingOnboarding(false);
    }
  };

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
          <div className="header-actions">
            {graph && (
              <>
                <button
                  type="button"
                  onClick={() => void handleReset()}
                  className="header-action-btn danger"
                  title="Reset repository and clear graph"
                  aria-label="Reset repository"
                >
                  <RotateCcw size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => setChatOpen(true)}
                  className="header-action-btn"
                  title="Ask Codebase Questions (Q&A)"
                  aria-label="Ask Codebase Questions"
                >
                  <MessageSquare size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => void handleOpenOnboarding()}
                  className="header-action-btn"
                  title="Developer Onboarding Documentation"
                  aria-label="Developer Onboarding Documentation"
                >
                  <BookOpen size={16} />
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => setLedgerOpen(true)}
              className="header-action-btn"
              title="Open Smart Ledger History"
              aria-label="Open history ledger"
            >
              <History size={16} />
            </button>
          </div>
        </div>

        {/* Upload Zone */}
        <div className="upload-section">
          <div className="section-label">
            <span>Repository Ingestion</span>
            {(graph || fileName) && (
              <button
                type="button"
                className="section-reset-btn"
                onClick={() => void handleReset()}
                title="Reset repository and clear graph"
              >
                <RotateCcw size={11} />
                <span>Reset</span>
              </button>
            )}
          </div>

          <div className="source-toggle">
            <button
              type="button"
              className={`source-toggle-btn ${sourceMode === "zip" ? "active" : ""}`}
              onClick={() => {
                setSourceMode("zip");
                setError(null);
              }}
            >
              <Upload size={12} />
              <span>ZIP Archive</span>
            </button>
            <button
              type="button"
              className={`source-toggle-btn ${sourceMode === "git" ? "active" : ""}`}
              onClick={() => {
                setSourceMode("git");
                setError(null);
              }}
            >
              <GitBranch size={12} />
              <span>Git Repository</span>
            </button>
          </div>

          {sourceMode === "zip" ? (
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

              {fileName && (
                <div className="active-file-pill-group" onClick={(e) => e.stopPropagation()}>
                  <div className="active-file-pill" title={fileName}>
                    <FileCode size={12} />
                    <span>{fileName}</span>
                  </div>
                  <button
                    type="button"
                    className="pill-reset-btn"
                    onClick={() => void handleReset()}
                    title="Remove repository"
                  >
                    <RotateCcw size={11} />
                  </button>
                </div>
              )}
            </div>
          ) : (
            <form onSubmit={handleGitClone} className="git-form">
              <div className="git-input-container">
                <Globe size={14} className="git-field-icon" />
                <input
                  type="text"
                  className="git-input"
                  placeholder="https://github.com/org/repo.git"
                  value={gitUrl}
                  onChange={(e) => setGitUrl(e.target.value)}
                  disabled={uploading}
                />
              </div>
              <div className="git-row">
                <div className="git-input-container" style={{ flex: 1 }}>
                  <GitBranch size={13} className="git-field-icon" />
                  <input
                    type="text"
                    className="git-input"
                    placeholder="branch (optional, e.g. main)"
                    value={gitBranch}
                    onChange={(e) => setGitBranch(e.target.value)}
                    disabled={uploading}
                  />
                </div>
                <button
                  type="submit"
                  className="git-submit-btn"
                  disabled={uploading || !gitUrl.trim()}
                >
                  {uploading ? (
                    <>
                      <Loader2 size={13} className="animate-spin" />
                      <span>Cloning…</span>
                    </>
                  ) : (
                    <span>Clone & Scan</span>
                  )}
                </button>
              </div>

              {fileName && (
                <div className="active-file-pill-group">
                  <div className="active-file-pill" title={fileName}>
                    <GitBranch size={12} />
                    <span>{fileName}</span>
                  </div>
                  <button
                    type="button"
                    className="pill-reset-btn"
                    onClick={() => void handleReset()}
                    title="Remove repository"
                  >
                    <RotateCcw size={11} />
                  </button>
                </div>
              )}
            </form>
          )}

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

          {/* Validation & Ingestion Summary Badge */}
          {graph?.validation_summary && (
            <div className="validation-summary-card">
              <div className="validation-badge-row">
                <span className="validation-stat" title={`${graph.validation_summary.valid_python_files_count} valid Python files discovered`}>
                  <FileCode size={12} className="stat-icon text-cyan" />
                  <strong>{graph.validation_summary.valid_python_files_count}</strong> py files
                </span>
                <span className="validation-stat" title={`${graph.validation_summary.total_loc.toLocaleString()} total lines of code`}>
                  <Workflow size={12} className="stat-icon text-cyan" />
                  <strong>{graph.validation_summary.total_loc.toLocaleString()}</strong> LOC
                </span>
                {graph.validation_summary.ignored_directories_count > 0 && (
                  <span className="validation-stat muted" title={`${graph.validation_summary.ignored_directories_count} irrelevant directories filtered`}>
                    <strong>{graph.validation_summary.ignored_directories_count}</strong> dirs filtered
                  </span>
                )}
              </div>
              {graph.validation_summary.syntax_error_files_count > 0 && (
                <div
                  className="validation-alert-pill"
                  title={graph.validation_summary.warnings.join("\n")}
                >
                  <AlertTriangle size={12} />
                  <span>{graph.validation_summary.syntax_error_files_count} syntax warning(s)</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Sidebar Mode Navigation: Debt Triage vs Architecture Intelligence */}
        {graph && (
          <div className="sidebar-mode-tabs">
            <button
              type="button"
              className={`sidebar-mode-tab ${sidebarMode === "debt" ? "active" : ""}`}
              onClick={() => setSidebarMode("debt")}
            >
              <ShieldAlert size={13} />
              <span>Debt Triage ({findings.length})</span>
            </button>
            <button
              type="button"
              className={`sidebar-mode-tab ${sidebarMode === "architecture" ? "active" : ""}`}
              onClick={() => setSidebarMode("architecture")}
            >
              <Layers size={13} />
              <span>Architecture & Flow</span>
            </button>
          </div>
        )}

        {/* VIEW 1: ARCHITECTURE INTELLIGENCE */}
        {graph && sidebarMode === "architecture" && (
          <div className="architecture-panel-wrapper">
            <ArchitectureView
              report={archReport}
              loading={loadingArch}
              onSelectFile={(f) => setSelectedPath(f)}
              selectedFile={selectedPath}
            />
          </div>
        )}

        {/* VIEW 2: DEBT TRIAGE */}
        {(!graph || sidebarMode === "debt") && (
          <div className="triage-section">
            <div className="section-label">
              <span>Technical Debt Triage</span>
              {analyzing && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "var(--cyan-400)", fontSize: 10 }}>
                  <Sparkles size={11} /> Analyzing
                </span>
              )}
            </div>

            {/* Severity Tabs */}
            <div className="tabs-container">
              {TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`tab-btn ${tab === t ? "active" : ""}`}
                  onClick={() => setTab(t)}
                >
                  <span className={`tab-dot tab-dot-${t.toLowerCase()}`} />
                  <span>{t}</span>
                  <span className="tab-count">{counts[t]}</span>
                </button>
              ))}
            </div>

            {/* Error Notification */}
            {error && (
              <div className="error-card animate-fade-in">
                <AlertTriangle size={15} style={{ flexShrink: 0 }} />
                <span>{error}</span>
              </div>
            )}

            {/* Findings List */}
            <div className="findings-scroll">
              {visibleFindings.length === 0 && !uploading && !analyzing && (
                <div className="empty-state">
                  <ShieldAlert size={28} className="empty-icon" />
                  <p className="empty-title">No {tab.toLowerCase()} severity issues</p>
                  <p className="empty-subtitle">
                    {findings.length > 0 ? "Switch tabs to view other detected debt." : "Repository healthy or no repo ingested."}
                  </p>
                </div>
              )}

              {visibleFindings.map((finding, idx) => {
                const isSelected = selectedPath === finding.file_name;
                const isAutoSolving = autoSolvingId === `${finding.file_name}-${finding.line_number ?? 0}`;
                const isLow = finding.severity === "Low";

                return (
                  <div
                    key={`${finding.file_name}-${idx}`}
                    className={`finding-card finding-${finding.severity.toLowerCase()} ${
                      isSelected ? "selected" : ""
                    }`}
                    onClick={() => {
                      setSelectedPath(finding.file_name);
                      if (!isLow) setActiveFinding(finding);
                    }}
                  >
                    <div className="finding-header">
                      <p className="finding-file" title={finding.file_name}>
                        <FileCode size={13} style={{ flexShrink: 0 }} />
                        <span>{finding.file_name}</span>
                        {finding.line_number && (
                          <span className="finding-line">:{finding.line_number}</span>
                        )}
                      </p>
                      <span className={`severity-badge badge-${finding.severity.toLowerCase()}`}>
                        {finding.severity}
                      </span>
                    </div>

                    <p className="finding-desc">{finding.description}</p>

                    <div className="finding-fix-box">
                      <p className="fix-label">RECOMMENDED FIX</p>
                      <p className="fix-text">{finding.suggested_fix}</p>
                    </div>

                    {/* Action Area */}
                    <div className="finding-footer">
                      {isLow ? (
                        <button
                          type="button"
                          disabled={isAutoSolving}
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleAutoSolve(finding);
                          }}
                          className="btn-autosolve"
                        >
                          {isAutoSolving ? (
                            <>
                              <Loader2 size={13} className="animate-spin" />
                              <span>Auto-Solving…</span>
                            </>
                          ) : (
                            <>
                              <Sparkles size={13} />
                              <span>AI Auto-Solve</span>
                            </>
                          )}
                        </button>
                      ) : (
                        <div style={{ display: "flex", width: "100%", justifyContent: "flex-end" }}>
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
        )}
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

        {/* Canvas Top Actions Bar (Reset, Ask Codebase, Onboarding) */}
        {graph && (
          <div className="canvas-top-actions">
            <button
              type="button"
              className="canvas-action-pill"
              onClick={() => setChatOpen(true)}
              title="Ask questions about architecture, functions, files, data flow"
            >
              <MessageSquare size={13} />
              <span>Ask Codebase</span>
            </button>
            <button
              type="button"
              className="canvas-action-pill"
              onClick={() => void handleOpenOnboarding()}
              title="Generate comprehensive developer onboarding documentation"
            >
              <BookOpen size={13} />
              <span>Onboarding Guide</span>
            </button>
            <button
              type="button"
              className="canvas-action-pill danger"
              onClick={() => void handleReset()}
              title="Unload repository and clear knowledge graph"
            >
              <RotateCcw size={13} />
              <span>Reset Graph</span>
            </button>
          </div>
        )}

        {graph ? (
          <ArchitectureCanvas
            graphNodes={graph.nodes}
            graphEdges={graph.edges}
            selectedPath={selectedPath}
            onSelectNode={(node) => setSelectedNode(node)}
          />
        ) : (
          <div className="canvas-empty">
            <span className="canvas-empty-icon">
              <AlertTriangle size={26} />
            </span>
            <h3 className="canvas-empty-title">No Knowledge Graph Loaded</h3>
            <p className="canvas-empty-desc">
              Upload a Python project archive (.zip) or connect a Git repository on the left panel to map file hierarchies, classes, functions, imports, and call dependencies.
            </p>
          </div>
        )}

        {/* Selected Node Details Card / Inspector */}
        {selectedNode && (
          <div className="canvas-node-inspector animate-fade-in">
            <div className="inspector-header">
              <div className="inspector-title-group">
                <span className="inspector-kind-badge">
                  {String(selectedNode.data?.kind || selectedNode.type || "node").toUpperCase()}
                </span>
                <h4 className="inspector-title" title={selectedNode.data?.label}>
                  {selectedNode.data?.label}
                </h4>
              </div>
              <button
                type="button"
                className="inspector-close-btn"
                onClick={() => setSelectedNode(null)}
                aria-label="Close inspector"
              >
                <X size={15} />
              </button>
            </div>

            <div className="inspector-body">
              {selectedNode.data?.path && (
                <div className="inspector-row">
                  <span className="inspector-label">Path:</span>
                  <span className="inspector-val code-font">{selectedNode.data.path}</span>
                </div>
              )}

              {selectedNode.data?.lineno && (
                <div className="inspector-row">
                  <span className="inspector-label">Lines:</span>
                  <span className="inspector-val code-font">
                    {selectedNode.data.lineno} - {selectedNode.data.end_lineno || selectedNode.data.lineno}
                  </span>
                </div>
              )}

              {Array.isArray(selectedNode.data?.bases) && selectedNode.data.bases.length > 0 && (
                <div className="inspector-row">
                  <span className="inspector-label">Inherits:</span>
                  <span className="inspector-val code-font">{selectedNode.data.bases.join(", ")}</span>
                </div>
              )}

              {Array.isArray(selectedNode.data?.args) && selectedNode.data.args.length > 0 && (
                <div className="inspector-row">
                  <span className="inspector-label">Params:</span>
                  <span className="inspector-val code-font">({selectedNode.data.args.join(", ")})</span>
                </div>
              )}

              {selectedNode.data?.docstring && (
                <div className="inspector-doc-section">
                  <span className="inspector-label">Docstring:</span>
                  <pre className="inspector-doc-pre">{selectedNode.data.docstring}</pre>
                </div>
              )}

              {Array.isArray(selectedNode.data?.calls) && selectedNode.data.calls.length > 0 && (
                <div className="inspector-calls-section">
                  <span className="inspector-label">Outgoing Calls:</span>
                  <div className="inspector-chips-row">
                    {selectedNode.data.calls.map((c: string) => (
                      <span key={c} className="inspector-chip">
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
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

        {/* Onboarding Guide Modal */}
        <OnboardingModal
          open={onboardingOpen}
          onClose={() => setOnboardingOpen(false)}
          doc={onboardingDoc}
          loading={loadingOnboarding}
          error={onboardingError}
          onRegenerate={() => void handleRegenerateOnboarding()}
        />

        {/* Codebase Q&A Intelligence Drawer */}
        <CodebaseChatDrawer
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          graph={graph}
          onSelectFile={(f) => setSelectedPath(f)}
        />
      </main>
    </div>
  );
}
