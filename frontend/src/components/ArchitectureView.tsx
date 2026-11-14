import React, { useState } from "react";
import {
  Layers,
  ArrowRight,
  FileCode,
  Box,
  Workflow,
  Search,
  Cpu,
  Database,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { ArchitectureReport, FileResponsibility } from "../lib/types";

type Props = {
  report: ArchitectureReport | null;
  loading: boolean;
  onSelectFile?: (filePath: string) => void;
  selectedFile?: string | null;
};

export default function ArchitectureView({
  report,
  loading,
  onSelectFile,
  selectedFile,
}: Props) {
  const [searchTerm, setSearchTerm] = useState("");
  const [activeTab, setActiveTab] = useState<"overview" | "dataflow" | "files">("overview");

  if (loading) {
    return (
      <div className="arch-loading-state">
        <Cpu size={28} className="animate-spin text-cyan" />
        <p className="arch-loading-title">Analyzing System Architecture…</p>
        <p className="arch-loading-subtitle">Mapping AST patterns, layers, and data pipelines</p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="arch-empty-state">
        <Layers size={32} className="text-muted" />
        <p className="arch-empty-title">No Architecture Report</p>
        <p className="arch-empty-subtitle">Upload or clone a repository to generate architecture intelligence.</p>
      </div>
    );
  }

  const filteredFiles = report.file_responsibilities.filter(
    (f) =>
      f.file_path.toLowerCase().includes(searchTerm.toLowerCase()) ||
      f.role.toLowerCase().includes(searchTerm.toLowerCase()) ||
      f.summary.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="arch-view-container">
      {/* Sub-navigation tabs */}
      <div className="arch-subtabs">
        <button
          type="button"
          className={`arch-subtab-btn ${activeTab === "overview" ? "active" : ""}`}
          onClick={() => setActiveTab("overview")}
        >
          <Layers size={13} />
          <span>Overview</span>
        </button>
        <button
          type="button"
          className={`arch-subtab-btn ${activeTab === "dataflow" ? "active" : ""}`}
          onClick={() => setActiveTab("dataflow")}
        >
          <Workflow size={13} />
          <span>Data Flow ({report.data_flow.length})</span>
        </button>
        <button
          type="button"
          className={`arch-subtab-btn ${activeTab === "files" ? "active" : ""}`}
          onClick={() => setActiveTab("files")}
        >
          <FileCode size={13} />
          <span>Files ({report.file_responsibilities.length})</span>
        </button>
      </div>

      <div className="arch-tab-content">
        {/* TAB 1: OVERVIEW & LAYERS */}
        {activeTab === "overview" && (
          <div className="arch-overview-pane">
            <div className="arch-pattern-badge">
              <span className="pattern-label">Architectural Pattern</span>
              <span className="pattern-name">{report.architectural_pattern}</span>
            </div>

            <div className="arch-card">
              <div className="arch-card-header">
                <span className="arch-card-title">System Overview</span>
                {report.model_used && (
                  <span className="arch-ai-tag">
                    <Sparkles size={11} /> {report.model_used}
                  </span>
                )}
              </div>
              <p className="arch-overview-text">{report.system_overview}</p>

              {report.key_technologies.length > 0 && (
                <div className="tech-tags-list">
                  {report.key_technologies.map((tech) => (
                    <span key={tech} className="tech-tag">
                      {tech}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="arch-layers-section">
              <h4 className="section-subheading">Architectural Layers</h4>
              <div className="layers-grid">
                {report.primary_layers.map((layer) => (
                  <div key={layer.name} className="layer-card">
                    <div className="layer-header">
                      <span className="layer-name">{layer.name}</span>
                      <span className="layer-count">{layer.files.length} modules</span>
                    </div>
                    <p className="layer-desc">{layer.description}</p>
                    <div className="layer-files-list">
                      {layer.files.map((file) => (
                        <div
                          key={file.path}
                          className={`layer-file-item ${selectedFile === file.path ? "selected" : ""}`}
                          onClick={() => onSelectFile?.(file.path)}
                          title="Click to locate on canvas"
                        >
                          <span className="layer-file-path">{file.path}</span>
                          <span className="layer-file-role">{file.role}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: DATA FLOW */}
        {activeTab === "dataflow" && (
          <div className="arch-dataflow-pane">
            <p className="dataflow-intro">
              Traced lifecycle of requests, input transformations, and persistence through AST dependencies:
            </p>
            <div className="dataflow-timeline">
              {report.data_flow.map((step) => (
                <div key={step.step_number} className="dataflow-step-card">
                  <div className="step-badge">Step {step.step_number}</div>
                  <div className="step-body">
                    <h5 className="step-stage">{step.stage}</h5>
                    <div className="step-route">
                      <span className="route-from">{step.source}</span>
                      <ArrowRight size={13} className="route-arrow" />
                      <span className="route-to">{step.destination}</span>
                    </div>
                    <p className="step-desc">{step.description}</p>
                    {step.files_involved.length > 0 && (
                      <div className="step-files">
                        <span className="step-files-label">Modules:</span>
                        {step.files_involved.map((file) => (
                          <span
                            key={file}
                            className="step-file-pill"
                            onClick={() => onSelectFile?.(file)}
                            title="Click to highlight on canvas"
                          >
                            {file}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 3: FILE RESPONSIBILITIES */}
        {activeTab === "files" && (
          <div className="arch-files-pane">
            <div className="files-search-bar">
              <Search size={14} className="search-icon" />
              <input
                type="text"
                placeholder="Search file path or role..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="files-search-input"
              />
              {searchTerm && (
                <button
                  type="button"
                  className="clear-search-btn"
                  onClick={() => setSearchTerm("")}
                >
                  Clear
                </button>
              )}
            </div>

            <div className="files-list-container">
              {filteredFiles.map((file) => (
                <div
                  key={file.file_path}
                  className={`responsibility-card ${selectedFile === file.file_path ? "selected" : ""}`}
                  onClick={() => onSelectFile?.(file.file_path)}
                >
                  <div className="resp-header">
                    <span className="resp-file-path" title={file.file_path}>
                      <FileCode size={13} className="text-cyan" />
                      <strong>{file.file_path}</strong>
                    </span>
                    <span className="resp-role-badge">{file.role}</span>
                  </div>

                  <p className="resp-summary">{file.summary}</p>

                  {(file.key_classes.length > 0 || file.key_functions.length > 0) && (
                    <div className="resp-symbols">
                      {file.key_classes.map((c) => (
                        <span key={c} className="resp-symbol class-symbol">
                          <Box size={10} /> {c}
                        </span>
                      ))}
                      {file.key_functions.map((fn) => (
                        <span key={fn} className="resp-symbol func-symbol">
                          <Workflow size={10} /> {fn}
                        </span>
                      ))}
                    </div>
                  )}

                  {file.imports_internal.length > 0 && (
                    <div className="resp-dependencies">
                      <span className="deps-label">Depends on:</span>
                      {file.imports_internal.map((dep) => (
                        <span key={dep} className="dep-pill">
                          {dep}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

