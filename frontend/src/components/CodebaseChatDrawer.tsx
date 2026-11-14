import React, { useEffect, useState } from "react";
import {
  MessageSquare,
  Send,
  Loader2,
  X,
  FileCode,
  Sparkles,
  HelpCircle,
  Key,
  Check,
} from "lucide-react";
import { askCodebase, errorMessage, getLLMStatus, setGeminiApiKey, type LLMStatus } from "../lib/api";
import type { CodebaseQnAResponse, GraphPayload } from "../lib/types";
import { MarkdownRenderer } from "./MarkdownRenderer";

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

  // Gemini API Key state
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [showKeyInput, setShowKeyInput] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (open) {
      void fetchStatus();
    }
  }, [open]);

  const fetchStatus = async () => {
    try {
      const status = await getLLMStatus();
      setLlmStatus(status);
    } catch {
      // Backend might be offline or initializing
    }
  };

  const handleSaveKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!keyInput.trim()) return;

    setSavingKey(true);
    setError(null);
    try {
      const updated = await setGeminiApiKey(keyInput.trim());
      setLlmStatus(updated);
      setSaveSuccess(true);
      setKeyInput("");
      setTimeout(() => {
        setSaveSuccess(false);
        setShowKeyInput(false);
      }, 1500);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingKey(false);
    }
  };

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
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <h3 className="drawer-title">Codebase Intelligence Q&A</h3>
                {llmStatus?.has_gemini_key ? (
                  <span
                    className="llm-pill connected"
                    title={`Connected via ${llmStatus.primary_model}`}
                  >
                    <Sparkles size={10} /> Gemini Active
                  </span>
                ) : (
                  <button
                    type="button"
                    className="llm-pill warning"
                    onClick={() => setShowKeyInput(!showKeyInput)}
                    title="Click to connect Gemini API Key"
                  >
                    <Key size={10} /> Connect Gemini
                  </button>
                )}
              </div>
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

        {/* Gemini Key Config Accordion */}
        {showKeyInput && (
          <form className="gemini-key-box" onSubmit={handleSaveKey}>
            <div className="gemini-key-header">
              <span className="gemini-key-title">
                <Key size={13} className="text-cyan" /> Configure Gemini API Key
              </span>
              <button
                type="button"
                className="gemini-key-close"
                onClick={() => setShowKeyInput(false)}
              >
                ✕
              </button>
            </div>
            <div className="gemini-key-input-row">
              <input
                type="password"
                className="gemini-key-input"
                placeholder="Paste your Gemini API key (starts with AIza...)"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                autoFocus
              />
              <button
                type="submit"
                className="gemini-key-btn"
                disabled={savingKey || !keyInput.trim()}
              >
                {savingKey ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : saveSuccess ? (
                  <>
                    <Check size={13} /> Connected!
                  </>
                ) : (
                  "Connect"
                )}
              </button>
            </div>
            <p className="gemini-key-hint">
              Saved securely to <code>backend/.env</code> as <code>GEMINI_API_KEY</code> and activates Gemini 1.5 Flash for your chatbot.
            </p>
          </form>
        )}

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
                ArchiteX uses Gemini and the AST dependency graph to explain how components interact, locate responsibilities, and trace execution pipelines.
              </p>
            </div>
          )}

          {loading && (
            <div className="chat-loading-item">
              <Loader2 size={20} className="animate-spin text-cyan" />
              <span>Analyzing AST knowledge graph & querying Gemini…</span>
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
                  <MarkdownRenderer content={item.answer} compact />
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
