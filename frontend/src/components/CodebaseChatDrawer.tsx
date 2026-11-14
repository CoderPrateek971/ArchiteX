import React, { useState } from "react";
import {
  MessageSquare,
  Send,
  Loader2,
  X,
  FileCode,
  Box,
  Sparkles,
  HelpCircle,
} from "lucide-react";
import { askCodebase, errorMessage } from "../lib/api";
import type { CodebaseQnAResponse, GraphPayload } from "../lib/types";

type Props = {
  open: boolean;
  onClose: () => void;
  graph: GraphPayload | null;
  onSelectFile?: (file: string) => void;
};

type QAItem = CodebaseQnAResponse;

const QUICK_PROMPTS = [
  "How does data flow through this codebase?",
  "Which files handle API routes and ingestion?",
  "Where is state or data stored?",
  "What are the main classes and functions?",
];

export default function CodebaseChatDrawer({
  open,
  onClose,
  graph,
  onSelectFile,
}: Props) {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<QAItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleAsk = async (qText: string) => {
    const cleanQ = qText.trim();
    if (!cleanQ || !graph) return;

    setError(null);
    setLoading(true);
    setQuestion("");

    try {
      const response = await askCodebase(cleanQ, graph);
      setHistory((prev) => [response, ...prev]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-drawer-backdrop" onClick={onClose}>
      <div className="chat-drawer" onClick={(e) => e.stopPropagation()}>
        {/* Drawer Header */}
        <div className="chat-drawer-header">
          <div className="drawer-title-group">
            <span className="brand-icon">
              <MessageSquare size={18} />
            </span>
            <div>
              <h3 className="drawer-title">Codebase Intelligence Q&A</h3>
              <p className="drawer-subtitle">Ask questions about architecture, files, symbols, and data flow</p>
            </div>
          </div>
          <button
            type="button"
            className="drawer-close-btn"
            onClick={onClose}
            aria-label="Close Q&A Drawer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Quick Suggestion Chips */}
        <div className="quick-prompts-bar">
          <span className="quick-label">
            <HelpCircle size={11} /> Suggested:
          </span>
          <div className="quick-chips-list">
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                className="quick-chip"
                onClick={() => void handleAsk(prompt)}
                disabled={loading}
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>

        {/* Chat History Container */}
        <div className="chat-history-container">
          {error && <div className="chat-error-banner">{error}</div>}

          {history.length === 0 && !loading && (
            <div className="chat-empty-state">
              <MessageSquare size={32} className="text-muted" />
              <p className="empty-title">Ask anything about this project</p>
              <p className="empty-subtitle">
                ArchiteX uses the AST dependency graph to explain how components interact, locate responsibilities, and trace execution pipelines.
              </p>
            </div>
          )}

          {loading && (
            <div className="chat-loading-item">
              <Loader2 size={20} className="animate-spin text-cyan" />
              <span>Analyzing AST knowledge graph & source definitions…</span>
            </div>
          )}

          {history.map((item, idx) => (
            <div key={idx} className="qa-item-card">
              <div className="qa-question-box">
                <span className="qa-label">Q:</span>
                <span className="qa-question-text">{item.question}</span>
              </div>

              <div className="qa-answer-box">
                <div className="qa-answer-header">
                  <span className="qa-label text-cyan">A:</span>
                  {item.model_used && (
                    <span className="arch-ai-tag">
                      <Sparkles size={11} /> {item.model_used}
                    </span>
                  )}
                </div>
                <div className="qa-answer-body">
                  <pre className="qa-answer-text">{item.answer}</pre>
                </div>

                {item.relevant_files.length > 0 && (
                  <div className="qa-citations">
                    <span className="citations-label">Relevant Modules:</span>
                    <div className="citation-pills">
                      {item.relevant_files.map((file) => (
                        <button
                          key={file}
                          type="button"
                          className="citation-pill"
                          onClick={() => {
                            onSelectFile?.(file);
                            onClose();
                          }}
                          title="Click to view on Knowledge Canvas"
                        >
                          <FileCode size={11} />
                          <span>{file}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Input Bar */}
        <form
          className="chat-input-bar"
          onSubmit={(e) => {
            e.preventDefault();
            void handleAsk(question);
          }}
        >
          <input
            type="text"
            className="chat-input"
            placeholder="Ask about architecture, data flow, functions, or files..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={loading}
          />
          <button
            type="submit"
            className="chat-send-btn"
            disabled={loading || !question.trim()}
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
          </button>
        </form>
      </div>
    </div>
  );
}

