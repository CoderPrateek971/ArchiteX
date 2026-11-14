import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  Copy,
  Download,
  Loader2,
  RotateCcw,
  X,
} from "lucide-react";
import type { OnboardingDocResponse } from "../lib/types";

type Props = {
  open: boolean;
  onClose: () => void;
  doc: OnboardingDocResponse | null;
  loading: boolean;
  error?: string | null;
  onRegenerate?: () => void;
};

export default function OnboardingModal({
  open,
  onClose,
  doc,
  loading,
  error,
  onRegenerate,
}: Props) {
  const [copied, setCopied] = useState(false);

  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const handleCopy = () => {
    if (!doc?.markdown) return;
    void navigator.clipboard.writeText(doc.markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!doc?.markdown) return;
    const blob = new Blob([doc.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    const safeName = (doc.project_name || "codebase").toLowerCase().replace(/[^a-z0-9_-]/g, "_");
    link.download = `${safeName}-ONBOARDING.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-content onboarding-modal animate-fade-in"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
      >
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-wrapper">
            <span className="brand-icon">
              <BookOpen size={18} />
            </span>
            <div>
              <h2 id="onboarding-title" className="modal-title">
                Developer Onboarding Guide
              </h2>
              <p className="modal-subtitle">
                {doc
                  ? `${doc.project_name} · Generated at ${doc.generated_at}`
                  : loading
                  ? "Analyzing codebase architecture…"
                  : "Onboarding manual"}
              </p>
            </div>
          </div>

          <div className="modal-header-actions">
            {doc && !loading && (
              <>
                {onRegenerate && (
                  <button
                    type="button"
                    className="modal-action-btn"
                    onClick={onRegenerate}
                    title="Regenerate guide from current graph"
                  >
                    <RotateCcw size={13} />
                    <span>Regenerate</span>
                  </button>
                )}
                <button
                  type="button"
                  className="modal-action-btn"
                  onClick={handleCopy}
                  title="Copy Markdown to Clipboard"
                >
                  {copied ? <Check size={13} className="text-cyan" /> : <Copy size={13} />}
                  <span>{copied ? "Copied!" : "Copy MD"}</span>
                </button>
                <button
                  type="button"
                  className="modal-action-btn primary"
                  onClick={handleDownload}
                  title="Download as ONBOARDING.md"
                >
                  <Download size={13} />
                  <span>Download .md</span>
                </button>
              </>
            )}
            <button
              type="button"
              className="modal-close-btn"
              onClick={onClose}
              aria-label="Close onboarding modal"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="modal-body onboarding-body">
          {error && (
            <div className="onboarding-error-box">
              <AlertTriangle size={16} />
              <span>{error}</span>
              {onRegenerate && (
                <button
                  type="button"
                  className="retry-btn"
                  onClick={onRegenerate}
                >
                  Retry
                </button>
              )}
            </div>
          )}

          {loading ? (
            <div className="onboarding-loading">
              <Loader2 size={32} className="animate-spin text-cyan" />
              <p className="loading-headline">Synthesizing Architecture & Onboarding Manual…</p>
              <p className="loading-subline">
                Parsing AST dependencies, classifying module responsibilities, and documenting execution lifecycles.
              </p>
            </div>
          ) : doc ? (
            <div className="markdown-preview">
              <pre className="markdown-pre">{doc.markdown}</pre>
            </div>
          ) : (
            <div className="onboarding-empty">
              <BookOpen size={28} className="text-muted" />
              <p className="empty-notice">No onboarding documentation generated yet.</p>
              {onRegenerate && (
                <button
                  type="button"
                  className="modal-action-btn primary"
                  style={{ marginTop: 12 }}
                  onClick={onRegenerate}
                >
                  Generate Onboarding Guide
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
