import os
import sqlite3
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Keep your AI services imports
from services.ast_parser import ingest_zip
from services.debt_detector import DebtReport, GraphPayload, analyze_debt
from services.llm_router import generate_completion

app = FastAPI(title="ArchiteX API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. Database Initialization ---
def init_db():
    conn = sqlite3.connect('ledger.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            file_path TEXT,
            severity TEXT,
            changed_by TEXT,
            details TEXT,
            previous_code TEXT,
            new_code TEXT,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- 2. Pydantic Models ---
class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1)

class PromptResponse(BaseModel):
    content: str
    model: str
    fallback_used: bool

class LedgerLogRequest(BaseModel):
    file_path: str
    severity: str
    changed_by: str
    details: str
    previous_code: str
    new_code: str
    workspace_root: Optional[str] = None

class RollbackRequest(BaseModel):
    id: int
    workspace_root: Optional[str] = None

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

@app.post("/api/upload-repo")
async def upload_repo(file: UploadFile = File(...)) -> dict:
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip file.")

    zip_bytes = await file.read()
    if not zip_bytes:
        raise HTTPException(status_code=400, detail="Uploaded zip is empty.")

    try:
        return ingest_zip(zip_bytes)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse repository: {exc}") from exc

@app.post("/api/analyze-debt", response_model=DebtReport)
def analyze_repo_debt(graph: GraphPayload) -> DebtReport:
    try:
        return analyze_debt(graph)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Debt analysis failed: {exc}") from exc

# --- 4. Ledger & Physical File Modification Endpoints ---
@app.get("/api/ledger")
def get_ledger() -> List[dict]:
    conn = sqlite3.connect('ledger.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ledger ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/api/ledger/log")
def log_ledger_change(request: LedgerLogRequest):
    timestamp = datetime.now().isoformat()
    
    # Handle workspace_root if frontend provides it
    file_path = request.file_path
    if request.workspace_root:
        file_path = os.path.join(request.workspace_root, request.file_path)

    actual_previous_code = request.previous_code

    # ⚡ PHYSICAL FILE OVERWRITE LOGIC ⚡
    if os.path.exists(file_path):
        try:
            # 1. Read and save the EXACT original code to ensure rollback works perfectly
            with open(file_path, 'r', encoding='utf-8') as f:
                actual_previous_code = f.read()
            
            # 2. Overwrite the file with the new code
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(request.new_code)
                
            print(f"✅ Physically updated file: {file_path}")
        except Exception as e:
            print(f"⚠️ Failed to write to {file_path}: {e}")
    else:
        # If running from a temporary .zip extraction, it skips safely
        print(f"⚠️ File not found on disk (skipping physical write): {file_path}")

    # SAVE TO DB
    conn = sqlite3.connect('ledger.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO ledger (timestamp, file_path, severity, changed_by, details, previous_code, new_code, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
    ''', (timestamp, request.file_path, request.severity, request.changed_by, request.details, actual_previous_code, request.new_code))
    
    conn.commit()
    cursor.execute("SELECT * FROM ledger WHERE id = last_insert_rowid()")
    new_row = dict(cursor.fetchone())
    conn.close()
    
    return new_row

@app.post("/api/ledger/rollback")
def rollback_ledger_change(request: RollbackRequest):
    conn = sqlite3.connect('ledger.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT previous_code, file_path FROM ledger WHERE id = ?", (request.id,))
    record = cursor.fetchone()
    
    if not record:
        conn.close()
        raise HTTPException(status_code=404, detail="Log not found")
        
    previous_code = record["previous_code"]
    file_path = record["file_path"]

    if request.workspace_root:
        file_path = os.path.join(request.workspace_root, file_path)
    
    # ⚡ PHYSICAL FILE ROLLBACK LOGIC ⚡
    if os.path.exists(file_path) and previous_code:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(previous_code)
            print(f"⏪ Physically rolled back file: {file_path}")
        except Exception as e:
            print(f"⚠️ Failed to rollback {file_path}: {e}")

    # Update DB status
    cursor.execute("UPDATE ledger SET status = 'rolled_back' WHERE id = ?", (request.id,))
    conn.commit()
    
    cursor.execute("SELECT * FROM ledger WHERE id = ?", (request.id,))
    updated_row = dict(cursor.fetchone())
    conn.close()
    
    return updated_row