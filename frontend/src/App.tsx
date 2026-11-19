import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  AlertTriangle,
  History,
  Loader2,
  ShieldAlert,
  Sparkles,
  Upload,
  Workflow,
  FileCode,
  AlertCircle,
  Cpu,
  GitBranch,
  Globe,
  RotateCcw,
  BookOpen,
  MessageSquare,
  X,
  Box,
  ArrowRight,
  Sun,
  Moon,
  MoreHorizontal,
  Download,
  FolderOpen,
} from "lucide-react";

import ArchitectureCanvas from "./components/ArchitectureCanvas";
import ArchitectureView from "./components/ArchitectureView";
import CodebaseChatDrawer from "./components/CodebaseChatDrawer";
import LedgerPanel from "./components/LedgerPanel";
import ModelRouterModal from "./components/ModelRouterModal";
import OnboardingModal from "./components/OnboardingModal";
import ResolutionView from "./components/ResolutionView";
import {
  analyzeDebt,
  cloneRepo,
  deleteWorkspace,
  downloadUpdatedWorkspace,
  errorMessage,
  applyAutomaticRepair,
  explainArchitecture,
  generateOnboarding,
  logLedgerChange,
  uploadRepo,
} from "./lib/api";
import type {
  ArchitectureReport,
  DebtFinding,
  LedgerEntry,
  GraphNode,
  GraphPayload,
  OnboardingDocResponse,
  Severity,
} from "./lib/types";

const TABS: Severity[] = ["High", "Medium", "Low"];

type WritableFile = {
  getFile(): Promise<File>;
  createWritable(): Promise<{ write(contents: string): Promise<void>; close(): Promise<void> }>;
};

type SourceDirectory = {
  name: string;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<SourceDirectory>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<WritableFile>;
  queryPermission?(options: { mode: "readwrite" }): Promise<PermissionState>;
  requestPermission?(options: { mode: "readwrite" }): Promise<PermissionState>;
};

type DirectoryPickerWindow = Window & {
  showDirectoryPicker?: (options: { mode: "readwrite" }) => Promise<SourceDirectory>;
};

async function writeLinkedSourceFile(
  root: SourceDirectory,
  relativePath: string,
  expectedOriginal: string,
  updatedCode: string
): Promise<void> {
  const parts = relativePath.replace(/\\/g, "/").split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) {
    throw new Error("The target file path is not safe to write.");
  }

  let directory = root;
  for (const part of parts.slice(0, -1)) {
    directory = await directory.getDirectoryHandle(part);
  }
  const target = await directory.getFileHandle(parts[parts.length - 1]);
  const current = await (await target.getFile()).text();
  const normalize = (code: string) => code.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (normalize(current) !== normalize(expectedOriginal)) {
    throw new Error(`The linked folder's ${relativePath} differs from the uploaded ZIP. No local file was overwritten.`);
  }

  const writable = await target.createWritable();
  await writable.write(updatedCode);
  await writable.close();
}

function getFindingKey(finding: DebtFinding): string {
  return finding.id || [
    finding.file_name,
    finding.line_number ?? "no-line",
    finding.category ?? "uncategorized",
    finding.title ?? finding.description,
  ].join(":");
}

export default function App() {
  const inputRef = useRef<HTMLInputElement>(null);
  const resizeStartRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const savedWidth = Number(localStorage.getItem("architex-sidebar-width"));
    return Number.isFinite(savedWidth) && savedWidth >= 360 ? Math.min(savedWidth, 880) : 480;
  });
  const [sidebarResizing, setSidebarResizing] = useState(false);
  const [experience, setExperience] = useState<"debt" | "explain" | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">(() =>
    localStorage.getItem("architex-theme") === "light" ? "light" : "dark"
  );
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
  const [routerOpen, setRouterOpen] = useState(false);
  const [ledgerRefresh, setLedgerRefresh] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [exportingWorkspace, setExportingWorkspace] = useState(false);
  const [linkedSourceDirectory, setLinkedSourceDirectory] = useState<SourceDirectory | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoSolvingId, setAutoSolvingId] = useState<string | null>(null);
  const [autoSolveFeedback, setAutoSolveFeedback] = useState<{ key: string; message: string } | null>(null);
  const [repairNotice, setRepairNotice] = useState<string | null>(null);

  // Architecture & Onboarding & Chat States
  const [archReport, setArchReport] = useState<ArchitectureReport | null>(null);
  const [loadingArch, setLoadingArch] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [onboardingDoc, setOnboardingDoc] = useState<OnboardingDocResponse | null>(null);
  const [loadingOnboarding, setLoadingOnboarding] = useState(false);
  const [onboardingError, setOnboardingError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  const counts = useMemo(() => {
    return {
      High: findings.filter((f) => f.severity.trim().toLowerCase() === "high").length,
      Medium: findings.filter((f) => f.severity.trim().toLowerCase() === "medium").length,
      Low: findings.filter((f) => f.severity.trim().toLowerCase() === "low").length,
    };
  }, [findings]);

  const visibleFindings = findings.filter(
    (finding) => finding.severity.trim().toLowerCase() === tab.toLowerCase()
  );

  useEffect(() => {
    localStorage.setItem("architex-theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("architex-sidebar-width", String(sidebarWidth));
  }, [sidebarWidth]);

  const themeToggle = (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
      title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
    >
      {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
      <span>{theme === "dark" ? "Light" : "Dark"}</span>
    </button>
  );

  if (!experience) {
    return (
      <main className={`experience-home ${theme === "light" ? "theme-light" : ""}`}>
        <div className="experience-home-inner">
          <header className="experience-header">
            <div className="experience-brand">
              <span className="brand-icon"><Workflow size={22} /></span>
              <div>
              <h1>ArchiteX</h1>
                <p>Python project tools</p>
              </div>
            </div>
            {themeToggle}
          </header>
          <div className="experience-intro">
            <h2>Choose a tool</h2>
            <p>Start with the task you want to complete.</p>
          </div>
          <div className="experience-options">
            <button
              type="button"
              className="experience-card"
              onClick={() => setExperience("debt")}
            >
              <span className="experience-icon debt"><ShieldAlert size={23} /></span>
              <span className="experience-card-copy">
                <strong>Debt Detector</strong>
                <span>Find bugs, code smells, and technical debt. Review severity, evidence, and repair guidance.</span>
              </span>
              <ArrowRight className="experience-arrow" size={19} />
            </button>
            <button
              type="button"
              className="experience-card"
              onClick={() => setExperience("explain")}
            >
              <span className="experience-icon explain"><BookOpen size={23} /></span>
              <span className="experience-card-copy">
                <strong>Codebase Explanation</strong>
                <span>Explore the knowledge graph, architecture, file responsibilities, and data flow.</span>
              </span>
              <ArrowRight className="experience-arrow" size={19} />
            </button>
          </div>
        </div>
      </main>
    );
  }

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
    setLinkedSourceDirectory(null);
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

async function verifyLinkedSourceFile(
  root: SourceDirectory,
  relativePath: string,
  expectedOriginal: string
): Promise<void> {
  const parts = relativePath.replace(/\\/g, "/").split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) {
    throw new Error("The target file path is not safe to read.");
  }
  let directory = root;
  try {
    for (const part of parts.slice(0, -1)) directory = await directory.getDirectoryHandle(part);
    const target = await directory.getFileHandle(parts[parts.length - 1]);
    const current = await (await target.getFile()).text();
    const normalize = (code: string) => code.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    if (normalize(current) !== normalize(expectedOriginal)) {
      throw new Error(`${relativePath} has changed since ${fileName || "the ZIP"} was uploaded. No local changes were overwritten. Link another folder or upload the latest project ZIP.`);
    }
  } catch (err) {
    if (err instanceof Error && (err.message.includes("has changed since") || err.message.includes("folder access"))) throw err;
    if (err instanceof DOMException && err.name === "NotAllowedError") {
      throw new Error("Chrome blocked access to this folder. Reset file access for localhost:3000 in Site settings, reload, and link the folder again.");
    }
    throw new Error(`Could not find ${relativePath} in the selected folder. Choose the extracted ${fileName || "project"} folder.`);
  }
}

async function ensureDirectoryWriteAccess(directory: SourceDirectory): Promise<void> {
  const options = { mode: "readwrite" as const };
  if (await directory.queryPermission?.(options) === "granted") return;
  const permission = await directory.requestPermission?.(options);
  if (permission !== "granted") {
    throw new Error("Chrome denied write access. Reset file access for localhost:3000 in Site settings, reload the page, then link the project folder again.");
  }
}

async function linkedFileExists(root: SourceDirectory, relativePath: string): Promise<boolean> {
  const parts = relativePath.replace(/\\/g, "/").split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) return false;
  try {
    let directory = root;
    for (const part of parts.slice(0, -1)) directory = await directory.getDirectoryHandle(part);
    await directory.getFileHandle(parts[parts.length - 1]);
    return true;
  } catch {
    return false;
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
    setLinkedSourceDirectory(null);
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
    setLinkedSourceDirectory(null);

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

  const handleDownloadUpdatedWorkspace = async () => {
    if (!graph?.workspace_id) {
      setError("This project has no downloadable workspace. Re-upload the ZIP or clone the repository, then retry.");
      return;
    }
    setExportingWorkspace(true);
    setError(null);
    try {
      await downloadUpdatedWorkspace(graph.workspace_id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setExportingWorkspace(false);
    }
  };

  const handleLinkSourceDirectory = async () => {
    const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
    if (!picker) {
      setError("Direct folder updates require Chrome or Edge. You can still download the updated project ZIP.");
      return;
    }
    try {
      const directory = await picker({ mode: "readwrite" });
      await ensureDirectoryWriteAccess(directory);
      const candidates = Object.entries(graph?.file_map || {}).filter(([path]) => path.endsWith(".py"));
      const missingFiles: string[] = [];
      for (const [path] of candidates) {
        if (!(await linkedFileExists(directory, path))) missingFiles.push(path);
      }
      if (missingFiles.length > 0) {
        setError(`This folder is missing ${missingFiles.slice(0, 3).join(", ")}. Choose the extracted ${fileName || "project"} folder that directly contains the uploaded project files.`);
        return;
      }
      setLinkedSourceDirectory(directory);
      setError(null);
      setAutoSolveFeedback(null);
      setRepairNotice(null);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(errorMessage(err));
    }
  };

  async function chooseSourceDirectoryForRepair(): Promise<SourceDirectory | null> {
    if (linkedSourceDirectory) {
      try {
        await ensureDirectoryWriteAccess(linkedSourceDirectory);
        return linkedSourceDirectory;
      } catch (err) {
        setError(errorMessage(err));
        return null;
      }
    }
    const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
    if (!picker) return null;
    try {
      const directory = await picker({ mode: "readwrite" });
      await ensureDirectoryWriteAccess(directory);
      setError(null);
      return directory;
    } catch (err) {
      // The user may cancel the picker and still choose to save the workspace fix.
      if (err instanceof DOMException && err.name === "AbortError") return null;
      setError(errorMessage(err));
      return null;
    }
  }

  // Handle AI Auto-Solving for Low Severity Issues using Module 6 Repair Engine
  const handleAutoSolve = async (finding: DebtFinding) => {
    const cleanFileName = finding.file_name.replace(/^file:/, "");
    const findingKey = getFindingKey(finding);
    const originalCode = graph?.file_map?.[cleanFileName];
    const proposedCode = finding.proposed_code || finding.structured_plan?.proposed_code || "";
    const renameFrom = finding.title.match(/Function [`']?([A-Za-z_]\w*)/)?.[1];
    const renameTo = proposedCode.match(/^\s*def\s+([A-Za-z_]\w*)\s*\(/m)?.[1];
    const isFunctionRename = Boolean(
      finding.title.includes("Weak or Non-Descriptive Naming") && renameFrom && renameTo && renameFrom !== renameTo
    );
    setAutoSolveFeedback(null);
    setRepairNotice(null);
    if (!proposedCode || (originalCode !== undefined && proposedCode === originalCode)) {
      setAutoSolveFeedback({ key: findingKey, message: "No safe automatic patch is available for this finding yet." });
      return;
    }
    setAutoSolvingId(findingKey);

    try {
      // ZIP uploads are isolated from the user's disk. Ask for the extracted
      // project folder during this click so the same fix can also be written
      // back to its matching local file.
      const sourceDirectory = await chooseSourceDirectoryForRepair();
      if (!sourceDirectory) {
        setAutoSolveFeedback({
          key: findingKey,
          message: "Folder access was not granted, so the fix was not applied. Click Link another folder and choose the extracted project folder. If Chrome keeps denying access, reset file access for localhost:3000 in Site settings, reload, and try again.",
        });
        return;
      }
      if (sourceDirectory && originalCode !== undefined) {
        try {
          const filesToCheck: Array<[string, string]> = isFunctionRename
            ? Object.entries(graph?.file_map || {}).filter(([path]) => path.endsWith(".py"))
            : [[cleanFileName, originalCode] as [string, string]];
          for (const [path, contents] of filesToCheck) {
            await verifyLinkedSourceFile(sourceDirectory, path, contents);
          }
        } catch (verifyError) {
          setLinkedSourceDirectory(null);
          setAutoSolveFeedback({
            key: findingKey,
            message: verifyError instanceof Error ? verifyError.message : "The selected folder does not contain the original project file.",
          });
          return;
        }
        setLinkedSourceDirectory(sourceDirectory);
      } else {
        setAutoSolveFeedback({ key: findingKey, message: `Could not read ${cleanFileName} from the uploaded project. Re-upload the ZIP and retry.` });
        return;
      }
      const res = await applyAutomaticRepair({
        issue_id: finding.id || `ISSUE-${cleanFileName}-${finding.line_number ?? 0}`,
        issue_title: finding.title || null,
        issue_description: finding.description || null,
        file_path: cleanFileName,
        severity: finding.severity,
        proposed_code: proposedCode,
        workspace_id: graph?.workspace_id,
        ...(isFunctionRename ? { rename_symbol_from: renameFrom, rename_symbol_to: renameTo } : {}),
        approval: true,
        expected_original_code: originalCode,
      });

      if (res.success) {
        const updatedFiles = res.updated_files && Object.keys(res.updated_files).length > 0
          ? res.updated_files
          : { [cleanFileName]: proposedCode };
        let localWritebackMessage = "Download the updated project ZIP to save the changed project files.";
        if (sourceDirectory && originalCode !== undefined) {
          try {
            for (const [path, code] of Object.entries(updatedFiles)) {
              const previousCode = graph?.file_map?.[path];
              if (previousCode === undefined) throw new Error(`Could not verify ${path} against the uploaded project.`);
              await writeLinkedSourceFile(sourceDirectory, path, previousCode, code);
            }
            localWritebackMessage = `Updated ${Object.keys(updatedFiles).length} file(s) in ${sourceDirectory.name}.`;
          } catch (writeError) {
            localWritebackMessage = writeError instanceof Error
              ? `${writeError.message} The ArchiteX workspace still has the fix; download the updated project ZIP to retrieve it.`
              : "The fix is saved in the ArchiteX workspace, but local folder write-back failed. Download the updated project ZIP to retrieve it.";
          }
        }
        // Remove only this issue; multiple findings can share a file and line.
        setFindings((prev) => prev.filter((f) => getFindingKey(f) !== findingKey));
        setGraph((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            file_map: { ...prev.file_map, ...updatedFiles },
            nodes: prev.nodes.map((node) => {
              const nodePath = String(node.data.path || "").replace(/^file:/, "");
              const kind = node.data.kind || node.type;
              return kind === "file" && updatedFiles[nodePath]
                ? { ...node, data: { ...node.data, source: updatedFiles[nodePath] } }
                : node;
            }),
          };
        });
        setAutoSolveFeedback(null);
        setRepairNotice(
          `Fix saved to the ArchiteX workspace${res.change_id ? ` as change #${res.change_id}` : ""}. ${localWritebackMessage}`
        );
        setLedgerRefresh((prev) => prev + 1);
      } else {
        setAutoSolveFeedback({ key: findingKey, message: res.explanation || "The repair could not be applied." });
      }
    } catch (err) {
      console.error(err);
      setAutoSolveFeedback({ key: findingKey, message: errorMessage(err) });
    } finally {
      setAutoSolvingId(null);
    }
  };

  const handleLedgerRollback = async (entry: LedgerEntry): Promise<string> => {
    const currentGraph = graph;
    const repoRoot = currentGraph?.repo_root?.replace(/\\/g, "/").replace(/\/$/, "");
    const filePath = entry.file_path.replace(/^file:/, "").replace(/\\/g, "/");
    if (!currentGraph || !repoRoot || !filePath.startsWith(`${repoRoot}/`)) {
      return "Rollback completed in the ArchiteX workspace. This change belongs to a different upload, so the currently linked VS Code folder was left unchanged.";
    }

    const relativePath = filePath.slice(repoRoot.length + 1);
    const restoredCode = entry.previous_code;
    const updatedGraph: GraphPayload = {
      ...currentGraph,
      file_map: { ...currentGraph.file_map, [relativePath]: restoredCode },
      nodes: currentGraph.nodes.map((node) => {
        const nodePath = String(node.data.path || "").replace(/^file:/, "").replace(/\\/g, "/");
        const kind = node.data.kind || node.type;
        return kind === "file" && nodePath === relativePath
          ? { ...node, data: { ...node.data, source: restoredCode } }
          : node;
      }),
    };
    setGraph(updatedGraph);

    let sourceMessage = "";
    if (linkedSourceDirectory) {
      try {
        await writeLinkedSourceFile(linkedSourceDirectory, relativePath, entry.new_code, restoredCode);
        sourceMessage = ` VS Code folder updated: ${relativePath}.`;
      } catch (err) {
        sourceMessage = ` The ArchiteX workspace was rolled back, but the linked folder could not be updated: ${errorMessage(err)}`;
      }
    } else {
      sourceMessage = " VS Code was not updated because no source folder is linked. Click Link source folder and select the extracted project folder to enable write-back.";
    }

    try {
      const report = await analyzeDebt(updatedGraph);
      setFindings(report.findings || []);
    } catch {
      // Keep the restored graph visible even if re-analysis is temporarily unavailable.
    }
    return `Change #${entry.id} rolled back in the ArchiteX workspace.${sourceMessage}`;
  };

  return (
      <div
        className={`app-container ${theme === "light" ? "theme-light" : ""} ${sidebarResizing ? "sidebar-resizing" : ""}`}
        style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}
      >
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
              <p className="brand-subtitle">Python project tools</p>
            </div>
          </div>
          <div className="header-actions">
            {themeToggle}
            {(experience === "debt" || (experience === "explain" && graph)) && (
              <details className="workspace-menu">
                <summary className="workspace-menu-trigger"><MoreHorizontal size={17} /><span>Tools</span></summary>
                <div className="workspace-menu-list">
                  {experience === "debt" && (
                    <>
                      <button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); setRouterOpen(true); }}>
                        <Cpu size={15} /> Model router
                      </button>
                      <button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); setLedgerOpen(true); }}>
                        <History size={15} /> Change history
                      </button>
                    </>
                  )}
                  {experience === "explain" && graph && (
                    <>
                      <button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); setChatOpen(true); }}>
                        <MessageSquare size={15} /> Ask about this codebase
                      </button>
                      <button type="button" onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); void handleOpenOnboarding(); }}>
                        <BookOpen size={15} /> Onboarding guide
                      </button>
                    </>
                  )}
                </div>
              </details>
            )}
          </div>
        </div>

        <div className="sidebar-scroll-content">
        <div className="tool-switch-bar">
          <span className="active-tool-label">
            <Workflow size={14} />
            {experience === "debt" ? "Debt Detector" : "Codebase Explanation"}
          </span>
          {experience === "debt" && (
            <button
              type="button"
              className="rollback-primary-button"
              onClick={() => setLedgerOpen(true)}
              title="Open change history and selectively rollback a saved change"
            >
              <RotateCcw size={14} />
              <span>Rollback</span>
            </button>
          )}
          <button type="button" className="tool-switch-button" onClick={() => setExperience(null)}>
            <span>Change tool</span>
            <ArrowRight size={14} />
          </button>
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

        {/* VIEW 1: ARCHITECTURE INTELLIGENCE */}
        {experience === "explain" && (
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
        {experience === "debt" && (
          <div className="triage-section">
            <div className="section-label">
              <span>Technical Debt Triage</span>
              {analyzing && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "var(--cyan-400)", fontSize: 10 }}>
                  <Sparkles size={11} /> Analyzing
                </span>
              )}
            </div>

            {repairNotice && <div className="repair-notice" role="status">{repairNotice}</div>}

            {/* Severity Tabs */}
            <div className="tabs-container">
              {TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`tab-btn ${tab === t ? "active" : ""}`}
                  data-severity={t}
                  aria-pressed={tab === t}
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

<div className="findings-scroll">
  {visibleFindings.length === 0 && !uploading && !analyzing && (
    <div className="empty-state">
      <ShieldAlert size={28} className="empty-icon" />
      <p className="empty-title">
        No {tab.toLowerCase()} severity issues
      </p>
      <p className="empty-subtitle">
        {findings.length > 0
          ? "Switch tabs to view other detected debt."
          : "Repository healthy or no repo ingested."}
      </p>
    </div>
  )}

  {visibleFindings.map((finding) => {
    const cleanPath = finding.file_name.replace(/^file:/, "");
    const isSelected = selectedPath === finding.file_name;
    const findingKey = getFindingKey(finding);
    const isSolvingThis = autoSolvingId === findingKey;
    const isLow = finding.severity === "Low";
    const proposedFix = finding.proposed_code || finding.structured_plan?.proposed_code || "";
    const originalCode = graph?.file_map?.[cleanPath];
    const hasSafeAutoFix = Boolean(proposedFix && (originalCode === undefined || proposedFix !== originalCode));

    return (
      <div
        key={findingKey}
        className={`debt-card ${isSelected ? "selected" : ""}`}
        onClick={() => {
          setSelectedPath(finding.file_name);

          if (!isLow) {
            setActiveFinding(finding);
          } else {
            setActiveFinding(null);
          }
        }}
      >
        <div className="card-header">
          <div className="card-title-group">
            <FileCode size={13} color="var(--cyan-400)" />

            <span className="card-file" title={cleanPath}>
              {cleanPath}
            </span>

            {finding.line_number && (
              <span className="card-line">
                L{finding.line_number}
              </span>
            )}

            {finding.category && (
              <span
                className={`category-pill ${finding.category
                  .toLowerCase()
                  .replace(/\s+/g, "-")}`}
              >
                {finding.category}
              </span>
            )}
          </div>

          <span
            className={`severity-badge badge-${finding.severity.toLowerCase()}`}
          >
            {finding.severity}
          </span>
        </div>

                  {finding.title && <div className="card-title-text">{finding.title}</div>}

                  <p className="card-desc">
                    {finding.description || finding.title}
                  </p>

                  {finding.root_cause && (
                    <div className="card-root-cause">
                      <span className="root-cause-label">Root cause</span>
                      <span>{finding.root_cause}</span>
                    </div>
                  )}

                  {finding.code_evidence && (
                    <details className="card-code-evidence" onClick={(event) => event.stopPropagation()}>
                      <summary>View code evidence</summary>
                      <pre><code>{finding.code_evidence}</code></pre>
                    </details>
                  )}

                  {finding.potential_impact && (
                    <div className="card-impact-callout">
                      <AlertCircle size={13} style={{ flexShrink: 0, marginTop: 1 }} />
                      <span><strong>Impact:</strong> {finding.potential_impact}</span>
                    </div>
                  )}

                  {finding.affected_files && finding.affected_files.length > 0 && (
                    <div className="card-affected-files">
                      <span className="affected-label">Affected ({finding.affected_files.length}):</span>
                      {finding.affected_files.slice(0, 3).map((f) => (
                        <span key={f} className="affected-pill">{f.split("/").pop()}</span>
                      ))}
                      {finding.affected_files.length > 3 && (
                        <span className="affected-more">+{finding.affected_files.length - 3} more</span>
                      )}
                    </div>
                  )}

                  <div className="card-action-box" onClick={(e) => e.stopPropagation()}>
                    {finding.severity === "Low" ? (
                      <div>
                        <p className="fix-preview-text">
                          <strong className="fix-preview-label">Suggested fix:</strong>{" "}
                          {finding.suggested_fix}
                        </p>
                        {hasSafeAutoFix ? <button
                          type="button"
                          disabled={isSolvingThis}
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleAutoSolve(finding);
                          }}
                          className="btn-auto-solve"
                        >
                          {isSolvingThis ? (
                            <>
                              <Loader2 size={13} className="animate-spin" />
                              <span>Auto-Solving…</span>
                            </>
                          ) : (
                            <>
                              <Sparkles size={13} />
                              <span>Apply fix</span>
                            </>
                          )}
                        </button> : <p className="no-auto-fix">No safe automatic patch is available for this issue.</p>}
                        {autoSolveFeedback?.key === findingKey && (
                          <div className="auto-solve-feedback" role="status">
                            <span>{autoSolveFeedback.message}</span>
                            {(autoSolveFeedback.message.includes("has changed since") || autoSolveFeedback.message.includes("Could not find") || autoSolveFeedback.message.includes("Folder access was not granted")) && (
                              <button
                                type="button"
                                className="feedback-link-button"
                                onClick={() => {
                                  void handleLinkSourceDirectory();
                                }}
                              >
                                <FolderOpen size={13} /> Link another folder
                              </button>
                            )}
                          </div>
                        )}
                      </div>
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
        </div>
      </aside>

      <div
        className="sidebar-resizer"
        title="Drag right to widen the sidebar; drag left to widen the graph"
        role="separator"
        aria-label="Resize sidebar"
        aria-orientation="vertical"
        aria-valuemin={360}
        aria-valuemax={Math.min(880, Math.round(window.innerWidth * 0.72))}
        aria-valuenow={sidebarWidth}
        tabIndex={0}
        onPointerDown={(event) => {
          if (window.innerWidth <= 800) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          resizeStartRef.current = { startX: event.clientX, startWidth: sidebarWidth };
          setSidebarResizing(true);
        }}
        onPointerMove={(event) => {
          if (!resizeStartRef.current) return;
          const maximum = Math.min(880, Math.round(window.innerWidth * 0.72));
          const nextWidth = resizeStartRef.current.startWidth + event.clientX - resizeStartRef.current.startX;
          setSidebarWidth(Math.max(360, Math.min(maximum, nextWidth)));
        }}
        onPointerUp={() => {
          resizeStartRef.current = null;
          setSidebarResizing(false);
        }}
        onPointerCancel={() => {
          resizeStartRef.current = null;
          setSidebarResizing(false);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
            event.preventDefault();
            const maximum = Math.min(880, Math.round(window.innerWidth * 0.72));
            const adjustment = event.key === "ArrowRight" ? 32 : -32;
            setSidebarWidth((current) => Math.max(360, Math.min(maximum, current + adjustment)));
          }
        }}
      >
        <span className="sidebar-resizer-grip" />
      </div>

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
            {!graph.git_info && (
              <button
                type="button"
                className="canvas-action-pill"
                onClick={() => void handleLinkSourceDirectory()}
                title="Select the original extracted project folder to write successful fixes back to it"
              >
                <FolderOpen size={13} />
                <span>{linkedSourceDirectory ? `Linked: ${linkedSourceDirectory.name}` : "Link source folder"}</span>
              </button>
            )}
            <button
              type="button"
              className="canvas-action-pill"
              onClick={() => void handleDownloadUpdatedWorkspace()}
              disabled={exportingWorkspace}
              title="Download a ZIP containing your updated workspace files"
            >
              {exportingWorkspace ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
              <span>{exportingWorkspace ? "Preparing ZIP…" : "Download updated project"}</span>
            </button>
            {experience === "explain" && (
              <>
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
              </>
            )}
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
          findings={findings}
          onRollback={handleLedgerRollback}
        />

        {/* Multi-Model AI Router Hub */}
        <ModelRouterModal
          isOpen={routerOpen}
          onClose={() => setRouterOpen(false)}
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
