import os
import sqlite3
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Keep your AI services imports
from services.architecture_explainer import (
    ArchitectureReport,
    AskCodebaseRequest,
    CodebaseQnAResponse,
    OnboardingDocResponse,
    analyze_codebase_architecture,
    answer_codebase_question,
    generate_onboarding_documentation,
)
from services.ast_parser import ingest_zip
from services.debt_detector import DebtReport, GraphPayload, analyze_debt
from services.repair_planner import (
    GuidedRepairPlan,
    TestValidationRequest,
    TestValidationResult,
    generate_guided_repair_plan,
    validate_repair_with_tests,
)
from services.llm_router import (
    ComparisonReport,
    ModelProfile,
    OptimizationStrategy,
    RouterResponse,
    TaskType,
    compare_model_responses,
    generate_completion,
    get_model_profiles,
    route_and_generate,
)
from services.workspace_manager import (
    create_workspace_from_zip,
    create_workspace_from_git,
    read_workspace_file,
    cleanup_workspace,
)
from database import ledger
from database.ledger import ConflictError
from services.repair_engine import (
    RepairApplyRequest,
    RepairApplyResult,
    apply_repair_request,
)

app = FastAPI(title="ArchiteX API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. Database Initialization ---
ledger.init_db()

# --- 2. Pydantic Models ---
class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1)

class PromptResponse(BaseModel):
    content: str
    model: str
    fallback_used: bool

class RouterGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    system: Optional[str] = None
    task_type: Optional[TaskType] = None
    strategy: OptimizationStrategy = OptimizationStrategy.BALANCED
    override_model: Optional[str] = None

class RouterCompareRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    candidate_models: Optional[List[str]] = None
    system: Optional[str] = None
    strategy: OptimizationStrategy = OptimizationStrategy.BALANCED

class LedgerLogRequest(BaseModel):
    file_path: str
    severity: str
    changed_by: str = "AI"
    details: Optional[str] = ""
    previous_code: Optional[str] = ""
    new_code: Optional[str] = ""
    workspace_root: Optional[str] = None
    issue_id: Optional[str] = None
    validation_result: Optional[str] = None

class RollbackRequest(BaseModel):
    id: int
    workspace_root: Optional[str] = None

class GitCloneRequest(BaseModel):
    url: str = Field(..., min_length=1, description="URL of the Git repository to clone")
    branch: Optional[str] = Field(None, description="Optional branch or tag name")

# --- 3. Core AI Endpoints ---
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

@app.post("/generate", response_model=PromptResponse)
def generate(request: PromptRequest) -> PromptResponse:
    try:
        result = generate_completion(request.prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return PromptResponse(**result)

@app.get("/api/router/models", response_model=List[ModelProfile])
def list_router_models() -> List[ModelProfile]:
    return get_model_profiles()

@app.post("/api/router/generate", response_model=RouterResponse)
def router_generate(req: RouterGenerateRequest) -> RouterResponse:
    try:
        return route_and_generate(
            prompt=req.prompt,
            system=req.system,
            task_type=req.task_type,
            strategy=req.strategy,
            override_model=req.override_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Routing failed: {exc}") from exc

@app.post("/api/router/compare", response_model=ComparisonReport)
def router_compare(req: RouterCompareRequest) -> ComparisonReport:
    try:
        return compare_model_responses(
            prompt=req.prompt,
            candidate_models=req.candidate_models,
            system=req.system,
            strategy=req.strategy,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model comparison failed: {exc}") from exc

@app.post("/api/upload-repo")
async def upload_repo(file: UploadFile = File(...)) -> dict:
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip file.")

    zip_bytes = await file.read()
    if not zip_bytes:
        raise HTTPException(status_code=400, detail="Uploaded zip file is empty.")

    try:
        return create_workspace_from_zip(zip_bytes, filename=file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to ingest ZIP repository: {exc}") from exc

@app.post("/api/clone-repo")
def clone_repo(request: GitCloneRequest) -> dict:
    try:
        return create_workspace_from_git(git_url=request.url, branch=request.branch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to clone and ingest Git repository: {exc}") from exc

@app.get("/api/workspace/{workspace_id}/file")
def get_workspace_file_content(workspace_id: str, path: str) -> dict:
    try:
        content = read_workspace_file(workspace_id, path)
        return {"path": path, "content": content}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.delete("/api/workspace/{workspace_id}")
def delete_workspace(workspace_id: str) -> dict:
    try:
        cleanup_workspace(workspace_id)
        return {"status": "ok", "message": f"Workspace {workspace_id} removed"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/api/analyze-debt", response_model=DebtReport)
def analyze_repo_debt(graph: GraphPayload) -> DebtReport:
    try:
        return analyze_debt(graph)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Debt analysis failed: {exc}") from exc

@app.post("/api/repair/validate-tests", response_model=TestValidationResult)
def validate_repair_tests(request: TestValidationRequest) -> TestValidationResult:
    try:
        return validate_repair_with_tests(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Validation failed: {exc}") from exc
@app.post("/api/explain-architecture", response_model=ArchitectureReport)
def explain_architecture_endpoint(graph: GraphPayload) -> ArchitectureReport:
    try:
        return analyze_codebase_architecture(graph)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Architecture explanation failed: {exc}") from exc

@app.post("/api/generate-onboarding", response_model=OnboardingDocResponse)
def generate_onboarding_endpoint(graph: GraphPayload) -> OnboardingDocResponse:
    try:
        return generate_onboarding_documentation(graph)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Onboarding generation failed: {exc}") from exc

@app.post("/api/ask-codebase", response_model=CodebaseQnAResponse)
def ask_codebase_endpoint(request: AskCodebaseRequest) -> CodebaseQnAResponse:
    try:
        return answer_codebase_question(request.graph, request.question)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Codebase Q&A failed: {exc}") from exc

# --- 4. Ledger & Automatic Repair Endpoints ---
@app.get("/api/ledger")
def get_ledger() -> List[dict]:
    entries = ledger.list_logs()
    return [e.model_dump() for e in entries]

@app.post("/api/ledger/log")
def log_ledger_change(request: LedgerLogRequest):
    try:
        entry = ledger.insert_log(
            file_path=request.file_path,
            previous_code=request.previous_code or "",
            new_code=request.new_code or "",
            severity=request.severity,
            changed_by=request.changed_by,
            details=request.details,
            issue_id=request.issue_id,
            validation_result=request.validation_result,
            workspace_root=request.workspace_root,
            write_to_disk=True,
        )
        return entry.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/api/ledger/rollback")
def rollback_ledger_change(request: RollbackRequest):
    try:
        updated = ledger.rollback_change(request.id, workspace_root=request.workspace_root)
        return updated.model_dump()
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/api/repair/apply", response_model=RepairApplyResult)
def apply_repair_endpoint(request: RepairApplyRequest) -> RepairApplyResult:
    try:
        return apply_repair_request(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Automatic repair engine error: {exc}") from exc