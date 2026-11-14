import React, { useEffect, useState } from "react";
import {
  X,
  Cpu,
  Zap,
  DollarSign,
  Award,
  Layers,
  ArrowRight,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  Play,
  RotateCcw,
  Sparkles,
  BarChart3,
  Loader2,
  Check,
  Copy,
} from "lucide-react";
import { fetchRouterModels, routerCompare, routerGenerate } from "../lib/api";
import type {
  ComparisonReport,
  ModelProfile,
  OptimizationStrategy,
  RouterResponse,
  TaskType,
} from "../lib/types";

type Props = {
  isOpen: boolean;
  onClose: () => void;
};

const STRATEGIES: { id: OptimizationStrategy; label: string; icon: any; desc: string }[] = [
  { id: "balanced", label: "Balanced", icon: Layers, desc: "Harmonic balance of quality, latency, and cost." },
  { id: "cost_optimized", label: "Cost-Optimized", icon: DollarSign, desc: "Favors ultra-low cost and free tier models." },
  { id: "speed_optimized", label: "Speed-Optimized", icon: Zap, desc: "Prioritizes lowest latency (<600ms) execution." },
  { id: "quality_optimized", label: "Quality-Optimized", icon: Award, desc: "Routes to highest reasoning capacity models." },
];

const PRESET_PROMPTS = [
  {
    title: "Circular Import Fix",
    prompt: "How do I resolve a circular import cycle between models.py and auth.py in a Python FastAPI codebase?",
    task: "architecture_analysis",
  },
  {
    title: "Safe Division & Guard",
    prompt: "Write a production Python function that calculates percentage ratios guarding against ZeroDivisionError and NaN values.",
    task: "code_remediation",
  },
  {
    title: "SQL Injection Defense",
    prompt: "Show how to rewrite an insecure execute(f'SELECT * FROM users WHERE email = {email}') using SQLite parameterized queries.",
    task: "security_audit",
  },
];

export default function ModelRouterModal({ isOpen, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<"catalog" | "arena" | "console">("catalog");
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [selectedStrategy, setSelectedStrategy] = useState<OptimizationStrategy>("balanced");

  // Arena state
  const [arenaPrompt, setArenaPrompt] = useState(PRESET_PROMPTS[0].prompt);
  const [selectedModelsForArena, setSelectedModelsForArena] = useState<string[]>([
    "architex-local-engine",
    "gpt-4o",
    "gemini/gemini-1.5-flash",
  ]);
  const [arenaLoading, setArenaLoading] = useState(false);
  const [comparisonReport, setComparisonReport] = useState<ComparisonReport | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Console state
  const [consolePrompt, setConsolePrompt] = useState("def process_orders(items=[]):\n    # Fix mutable default and add docstring");
  const [consoleLoading, setConsoleLoading] = useState(false);
  const [consoleResponse, setConsoleResponse] = useState<RouterResponse | null>(null);

  useEffect(() => {
    if (isOpen) {
      void loadModels();
    }
  }, [isOpen]);

  async function loadModels() {
    setLoadingModels(true);
    try {
      const data = await fetchRouterModels();
      setModels(data);
    } catch (err) {
      console.error("Failed to load router models:", err);
    } finally {
      setLoadingModels(false);
    }
  }

  async function handleRunArena() {
    if (!arenaPrompt.trim()) return;
    setArenaLoading(true);
    setComparisonReport(null);
    try {
      const report = await routerCompare({
        prompt: arenaPrompt,
        candidate_models: selectedModelsForArena,
        strategy: selectedStrategy,
      });
      setComparisonReport(report);
    } catch (err) {
      console.error(err);
      alert("Failed to run model comparison. Please check backend connection.");
    } finally {
      setArenaLoading(false);
    }
  }

  async function handleRunConsole() {
    if (!consolePrompt.trim()) return;
    setConsoleLoading(true);
    try {
      const resp = await routerGenerate({
        prompt: consolePrompt,
        strategy: selectedStrategy,
      });
      setConsoleResponse(resp);
    } catch (err) {
      console.error(err);
      alert("Routing failed. Please ensure backend is running.");
    } finally {
      setConsoleLoading(false);
    }
  }

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  if (!isOpen) return null;

  return (
    <div className="router-modal-overlay animate-fade-in" onClick={onClose}>
      <div className="router-modal-container" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="router-modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="router-icon-pill">
              <Cpu size={18} color="var(--cyan-400)" />
            </span>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                  Multi-Model AI Router Hub
                </h2>
                <span className="module-badge">MODULE 4</span>
              </div>
              <p style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Task-Aware Dynamic Selection • Response Quality Comparison • Automatic Fallback Pipeline
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="header-action-btn" aria-label="Close router hub">
            <X size={18} />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="router-nav-tabs">
          <button
            type="button"
            className={`router-tab ${activeTab === "catalog" ? "active" : ""}`}
            onClick={() => setActiveTab("catalog")}
          >
            <BarChart3 size={14} />
            <span>Model Catalog & Routing Policy</span>
          </button>
          <button
            type="button"
            className={`router-tab ${activeTab === "arena" ? "active" : ""}`}
            onClick={() => setActiveTab("arena")}
          >
            <Sparkles size={14} />
            <span>Multi-Model Arena & Comparator</span>
          </button>
          <button
            type="button"
            className={`router-tab ${activeTab === "console" ? "active" : ""}`}
            onClick={() => setActiveTab("console")}
          >
            <Play size={14} />
            <span>Live Routing Console</span>
          </button>
        </div>

        {/* Modal Body */}
        <div className="router-modal-body">
          {/* TAB 1: MODEL CATALOG & ROUTING POLICY */}
          {activeTab === "catalog" && (
            <div>
              {/* Strategy Selector */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)" }}>
                    ACTIVE ROUTING STRATEGY
                  </label>
                  <span style={{ fontSize: 11, color: "var(--cyan-400)", fontFamily: "var(--font-mono)" }}>
                    {STRATEGIES.find((s) => s.id === selectedStrategy)?.desc}
                  </span>
                </div>
                <div className="strategy-grid">
                  {STRATEGIES.map((s) => {
                    const Icon = s.icon;
                    const isActive = selectedStrategy === s.id;
                    return (
                      <div
                        key={s.id}
                        className={`strategy-card ${isActive ? "active" : ""}`}
                        onClick={() => setSelectedStrategy(s.id)}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                          <Icon size={16} color={isActive ? "var(--cyan-400)" : "var(--text-muted)"} />
                          <span style={{ fontSize: 13, fontWeight: 600 }}>{s.label}</span>
                        </div>
                        <p style={{ fontSize: 10.5, color: "var(--text-muted)", lineHeight: 1.3 }}>
                          {s.desc}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Task Mapping Overview */}
              <div style={{ marginBottom: 20 }}>
                <h4 style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 8 }}>
                  TASK-AWARE DYNAMIC ROUTING MAPPING
                </h4>
                <div className="task-mapping-grid">
                  <div className="task-mapping-card">
                    <span className="task-label">ARCHITECTURE & DESIGN</span>
                    <span className="task-model">GPT-4o / Claude 3.5 Sonnet</span>
                    <span className="task-reason">High reasoning depth & multi-file context</span>
                  </div>
                  <div className="task-mapping-card">
                    <span className="task-label">CODE REMEDIATION</span>
                    <span className="task-model">Claude 3.5 / Local AST Engine</span>
                    <span className="task-reason">Accurate diff generation & syntax guarantee</span>
                  </div>
                  <div className="task-mapping-card">
                    <span className="task-label">SECURITY AUDITS</span>
                    <span className="task-model">Gemini 1.5 Pro / GPT-4o</span>
                    <span className="task-reason">Taint-tracking & vulnerability detection</span>
                  </div>
                  <div className="task-mapping-card">
                    <span className="task-label">QUICK FIXES & HYGIENE</span>
                    <span className="task-model">Gemini 1.5 Flash / GPT-4o Mini</span>
                    <span className="task-reason">Lowest latency (under 500ms) & zero cost overhead</span>
                  </div>
                </div>
              </div>

              {/* Live Model Catalog */}
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <h4 style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)" }}>
                    LIVE MODEL REGISTRY & HEALTH TRACKER ({models.length})
                  </h4>
                  <button type="button" onClick={() => void loadModels()} className="btn-secondary" style={{ padding: "4px 8px", fontSize: 11 }}>
                    <RotateCcw size={12} /> Refresh Status
                  </button>
                </div>

                {loadingModels ? (
                  <div style={{ textAlign: "center", padding: "40px 0" }}>
                    <Loader2 size={24} className="animate-spin" style={{ color: "var(--cyan-400)", margin: "0 auto 8px" }} />
                    <p style={{ fontSize: 12, color: "var(--text-muted)" }}>Probing model providers & latency…</p>
                  </div>
                ) : (
                  <div className="model-table-container">
                    <table className="model-table">
                      <thead>
                        <tr>
                          <th>Model</th>
                          <th>Provider</th>
                          <th>Status</th>
                          <th>Input / Output Cost</th>
                          <th>Latency</th>
                          <th>Quality Score</th>
                          <th>Success Rate</th>
                        </tr>
                      </thead>
                      <tbody>
                        {models.map((m) => (
                          <tr key={m.id}>
                            <td>
                              <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{m.name}</div>
                              <span style={{ fontSize: 9.5, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{m.id}</span>
                            </td>
                            <td>
                              <span className="provider-pill">{m.provider}</span>
                            </td>
                            <td>
                              <span className={`status-pill ${m.health_status.toLowerCase().replace(/\s+/g, "-")}`}>
                                {m.health_status}
                              </span>
                            </td>
                            <td style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                              ${m.cost_input_per_m} / ${m.cost_output_per_m} <span style={{ color: "var(--text-muted)", fontSize: 9 }}>/1M</span>
                            </td>
                            <td style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                              {m.avg_latency_ms} ms
                            </td>
                            <td>
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <span style={{ fontWeight: 600, fontSize: 11 }}>{m.quality_rating}</span>
                                <div className="mini-progress-bar">
                                  <div className="mini-progress-fill" style={{ width: `${m.quality_rating}%` }} />
                                </div>
                              </div>
                            </td>
                            <td style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--emerald-400)" }}>
                              {m.success_rate}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 2: MULTI-MODEL COMPARISON ARENA */}
          {activeTab === "arena" && (
            <div>
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 6, display: "block" }}>
                  ARENA PROMPT / CODE TASK:
                </label>
                <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                  {PRESET_PROMPTS.map((p) => (
                    <button
                      key={p.title}
                      type="button"
                      className="preset-btn"
                      onClick={() => setArenaPrompt(p.prompt)}
                    >
                      {p.title}
                    </button>
                  ))}
                </div>
                <textarea
                  value={arenaPrompt}
                  onChange={(e) => setArenaPrompt(e.target.value)}
                  className="router-textarea"
                  rows={3}
                  placeholder="Enter code instruction, bug repair, or architectural query to compare..."
                />
              </div>

              {/* Models to compare */}
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 6, display: "block" }}>
                  SELECT MODELS FOR HEAD-TO-HEAD COMPARISON:
                </label>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {models.map((m) => {
                    const isSelected = selectedModelsForArena.includes(m.id);
                    return (
                      <button
                        key={m.id}
                        type="button"
                        className={`model-select-chip ${isSelected ? "selected" : ""}`}
                        onClick={() => {
                          if (isSelected) {
                            if (selectedModelsForArena.length > 1) {
                              setSelectedModelsForArena(selectedModelsForArena.filter((id) => id !== m.id));
                            }
                          } else {
                            setSelectedModelsForArena([...selectedModelsForArena, m.id]);
                          }
                        }}
                      >
                        {isSelected && <Check size={12} />}
                        <span>{m.name}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <button
                type="button"
                disabled={arenaLoading}
                onClick={() => void handleRunArena()}
                className="btn-primary"
                style={{ width: "100%", marginBottom: 20 }}
              >
                {arenaLoading ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    <span>Executing Multi-Model Comparison Arena…</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={16} />
                    <span>Run Head-to-Head Model Comparison ({selectedModelsForArena.length} Models)</span>
                  </>
                )}
              </button>

              {/* Comparison Results */}
              {comparisonReport && (
                <div className="animate-fade-in">
                  <div className="recommendation-banner">
                    <Award size={18} color="var(--amber-400)" />
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 12, color: "var(--amber-400)" }}>
                        WINNING MODEL IDENTIFIED: {comparisonReport.winning_model}
                      </div>
                      <p style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
                        {comparisonReport.recommendation_reason}
                      </p>
                    </div>
                  </div>

                  <div className="arena-cards-grid">
                    {comparisonReport.evaluations.map((ev) => (
                      <div key={ev.model} className={`arena-card ${ev.is_winner ? "winner" : ""}`}>
                        {ev.is_winner && (
                          <div className="winner-badge">
                            <Award size={12} />
                            <span>WINNER</span>
                          </div>
                        )}
                        <div className="arena-card-header">
                          <div>
                            <h4 style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{ev.model}</h4>
                            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{ev.provider}</span>
                          </div>
                          <div style={{ textAlign: "right" }}>
                            <div style={{ fontSize: 16, fontWeight: 700, color: ev.is_winner ? "var(--cyan-400)" : "var(--text-primary)" }}>
                              {ev.overall_score}
                              <span style={{ fontSize: 10, color: "var(--text-muted)" }}>/100</span>
                            </div>
                            <span style={{ fontSize: 9, color: "var(--text-muted)" }}>Overall Score</span>
                          </div>
                        </div>

                        {/* Metrics Bar */}
                        <div className="arena-metrics-box">
                          <div className="metric-row">
                            <span>Quality Score</span>
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <span style={{ fontWeight: 600 }}>{ev.quality_score}</span>
                              <div className="mini-progress-bar" style={{ width: 60 }}>
                                <div className="mini-progress-fill" style={{ width: `${ev.quality_score}%` }} />
                              </div>
                            </div>
                          </div>
                          <div className="metric-row">
                            <span>Relevance Score</span>
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <span style={{ fontWeight: 600 }}>{ev.relevance_score}</span>
                              <div className="mini-progress-bar" style={{ width: 60 }}>
                                <div className="mini-progress-fill" style={{ width: `${ev.relevance_score}%`, background: "var(--emerald-400)" }} />
                              </div>
                            </div>
                          </div>
                          <div className="metric-row">
                            <span>Latency</span>
                            <span style={{ fontFamily: "var(--font-mono)" }}>{ev.latency_ms} ms</span>
                          </div>
                          <div className="metric-row">
                            <span>Estimated Cost</span>
                            <span style={{ fontFamily: "var(--font-mono)" }}>${ev.estimated_cost.toFixed(5)}</span>
                          </div>
                          <div className="metric-row">
                            <span>Compilable Syntax</span>
                            <span style={{ color: ev.syntax_valid ? "var(--emerald-400)" : "var(--red-400)", display: "flex", alignItems: "center", gap: 4 }}>
                              {ev.syntax_valid ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                              {ev.syntax_valid ? "Valid AST" : "Syntax Errors"}
                            </span>
                          </div>
                        </div>

                        {/* Strengths tags */}
                        {ev.strengths && ev.strengths.length > 0 && (
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 10 }}>
                            {ev.strengths.map((str) => (
                              <span key={str} className="strength-tag">{str}</span>
                            ))}
                          </div>
                        )}

                        {/* Output preview */}
                        <div className="arena-output-box">
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>RESPONSE CONTENT</span>
                            <button
                              type="button"
                              onClick={() => handleCopy(ev.model, ev.content)}
                              className="copy-btn"
                            >
                              {copiedId === ev.model ? <Check size={11} /> : <Copy size={11} />}
                              <span>{copiedId === ev.model ? "Copied" : "Copy"}</span>
                            </button>
                          </div>
                          <pre style={{ margin: 0, fontSize: 10.5, fontFamily: "var(--font-mono)", color: "#e2e8f0", whiteSpace: "pre-wrap", maxHeight: 180, overflowY: "auto" }}>
                            {ev.content}
                          </pre>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: LIVE ROUTING CONSOLE */}
          {activeTab === "console" && (
            <div>
              <div style={{ marginBottom: 14 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 6, display: "block" }}>
                  TEST PROMPT FOR TASK-AWARE ROUTER:
                </label>
                <textarea
                  value={consolePrompt}
                  onChange={(e) => setConsolePrompt(e.target.value)}
                  className="router-textarea"
                  rows={4}
                  placeholder="Enter any Python question, refactoring goal, or security inquiry..."
                />
              </div>

              <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
                <button
                  type="button"
                  disabled={consoleLoading}
                  onClick={() => void handleRunConsole()}
                  className="btn-primary"
                  style={{ flex: 1 }}
                >
                  {consoleLoading ? (
                    <>
                      <Loader2 size={15} className="animate-spin" />
                      <span>Classifying & Routing Request…</span>
                    </>
                  ) : (
                    <>
                      <Play size={15} />
                      <span>Execute Dynamic Route & Generation</span>
                    </>
                  )}
                </button>
              </div>

              {consoleResponse && (
                <div className="console-result-card animate-fade-in">
                  <div className="console-result-header">
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="category-pill" style={{ fontSize: 10 }}>
                        {consoleResponse.task_type.toUpperCase().replace(/_/g, " ")}
                      </span>
                      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>
                        Model: {consoleResponse.model}
                      </span>
                      <span className="provider-pill">{consoleResponse.provider}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11, fontFamily: "var(--font-mono)" }}>
                      <span style={{ color: "var(--cyan-400)" }}>{consoleResponse.latency_ms} ms</span>
                      <span style={{ color: "var(--emerald-400)" }}>${consoleResponse.estimated_cost.toFixed(5)}</span>
                    </div>
                  </div>

                  {consoleResponse.fallback_used && (
                    <div className="fallback-banner">
                      <AlertTriangle size={14} />
                      <span>{consoleResponse.fallback_reason || "Automatic fallback engaged."}</span>
                    </div>
                  )}

                  <div style={{ marginTop: 10 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                      <span style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)" }}>
                        CASCADING ROUTE CHAIN:
                      </span>
                      <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                        {consoleResponse.fallback_chain.join(" ➔ ")}
                      </span>
                    </div>
                    <div className="card-code-evidence" style={{ maxHeight: 250, overflowY: "auto" }}>
                      <pre style={{ whiteSpace: "pre-wrap" }}>
                        <code>{consoleResponse.content}</code>
                      </pre>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
