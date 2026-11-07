import os
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from . import __version__
from .config import Config
from .file_filter import FileFilter
from .git_service import GitError, GitService
from .logger import get_logger
from .models import ChangeType, CommitMode, CommitStyle, FileChange
from .ollama_service import OllamaService
from .secret_scanner import SecretScanner
from .utils import build_batch_preview, build_content_preview

logger = get_logger(__name__)

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


def create_app() -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("FastAPI and Uvicorn must be installed to run the microservice server.")

    app = FastAPI(
        title="Smart Committer Microservice",
        description="Local LLM-powered Git commit generator and microservice daemon via Ollama.",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class HealthResponse(BaseModel):
        status: str
        version: str
        ollama_host: str
        ollama_model: str
        ollama_reachable: bool
        available_models: List[str]

    class StatusRequest(BaseModel):
        repo_path: str = "."
        tree_depth: int = 0
        include: List[str] = Field(default_factory=list)
        exclude: List[str] = Field(default_factory=list)
        force_include: List[str] = Field(default_factory=list)

    class FileItem(BaseModel):
        path: str
        status: str
        change_type: str
        original_path: Optional[str] = None
        security_warnings: List[str] = Field(default_factory=list)

    class StatusResponse(BaseModel):
        repo_root: str
        branch: str
        has_remote: bool
        total_files: int
        files: List[FileItem]

    class PreviewRequest(BaseModel):
        repo_path: str = "."
        mode: str = "single"  # single, all, grouped
        style: str = "conventional"
        tree_depth: int = 0
        include: List[str] = Field(default_factory=list)
        exclude: List[str] = Field(default_factory=list)
        force_include: List[str] = Field(default_factory=list)
        limit: Optional[int] = None

    class CommitRequest(BaseModel):
        repo_path: str = "."
        mode: str = "single"  # single, all, grouped
        style: str = "conventional"
        tree_depth: int = 0
        include: List[str] = Field(default_factory=list)
        exclude: List[str] = Field(default_factory=list)
        force_include: List[str] = Field(default_factory=list)
        limit: Optional[int] = None
        push: bool = False
        signoff: bool = False
        skip_secret_scan: bool = False

    class GenerateTextRequest(BaseModel):
        diff_text: str
        style: str = "conventional"
        scope_hint: Optional[str] = None

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health_check():
        cfg = Config()
        reachable = True
        models = []
        try:
            models = OllamaService.health_check(cfg.ollama_host)
        except Exception:
            reachable = False

        return HealthResponse(
            status="ok",
            version=__version__,
            ollama_host=cfg.ollama_host,
            ollama_model=cfg.ollama_model,
            ollama_reachable=reachable,
            available_models=models,
        )

    @app.get("/api/v1/models")
    def list_models():
        cfg = Config()
        try:
            models = OllamaService.health_check(cfg.ollama_host)
            return {"models": models, "active": cfg.ollama_model}
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    def _get_git(repo_path: str) -> GitService:
        path = Path(repo_path).expanduser().resolve()
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"Path not found: {repo_path}")
        git = GitService(path)
        if not git.is_repo():
            raise HTTPException(status_code=400, detail=f"Not a git repository: {repo_path}")
        return git

    def _get_candidates(git: GitService, req) -> List[FileChange]:
        status_entries = git.get_status()
        ff = FileFilter(
            includes=req.include,
            excludes=req.exclude,
            force_includes=req.force_include,
        )
        candidates: List[FileChange] = []
        for xy, path, orig in status_entries:
            if not ff.is_allowed(path):
                continue

            change_type = (
                ChangeType.ADDED if xy == "??" or "A" in xy
                else ChangeType.RENAMED if "R" in xy
                else ChangeType.DELETED if "D" in xy
                else ChangeType.MODIFIED
            )

            # Security scan
            warnings = []
            if SecretScanner.is_sensitive_filename(path):
                warnings.append(f"Sensitive filename pattern detected: {path}")

            candidates.append(
                FileChange(
                    path=path,
                    status=xy,
                    change_type=change_type,
                    original_path=orig,
                    security_warnings=warnings,
                )
            )

        if getattr(req, "tree_depth", 0) > 0:
            candidates = git.apply_tree_depth(candidates, req.tree_depth)

        return candidates

    @app.post("/api/v1/status", response_model=StatusResponse)
    def repo_status(req: StatusRequest):
        git = _get_git(req.repo_path)
        candidates = _get_candidates(git, req)

        return StatusResponse(
            repo_root=str(git.repo_root),
            branch=git.get_current_branch(),
            has_remote=git.has_remote(),
            total_files=len(candidates),
            files=[
                FileItem(
                    path=c.path,
                    status=c.status,
                    change_type=c.change_type.value,
                    original_path=c.original_path,
                    security_warnings=c.security_warnings,
                )
                for c in candidates
            ],
        )

    @app.post("/api/v1/preview")
    def preview_commits(req: PreviewRequest):
        git = _get_git(req.repo_path)
        cfg = Config()
        candidates = _get_candidates(git, req)
        if req.limit:
            candidates = candidates[: req.limit]

        if not candidates:
            return {"mode": req.mode, "candidates": [], "message": "No eligible changes"}

        ollama = OllamaService(
            model=cfg.ollama_model,
            host=cfg.ollama_host,
            style=CommitStyle(req.style),
        )

        mode = req.mode.lower()
        if mode == CommitMode.ALL.value:
            for c in candidates:
                c.content_preview = build_content_preview(git, c, cfg.max_file_preview)
            batch_preview = build_batch_preview(git, candidates, 3000)
            msg = ollama.generate_batch_message(batch_preview)
            return {
                "mode": "all",
                "total_files": len(candidates),
                "generated_message": msg,
                "files": [c.path for c in candidates],
            }

        elif mode == CommitMode.GROUPED.value:
            groups = git.group_changes(candidates)
            group_results = []
            for g in groups:
                for c in g.files:
                    c.content_preview = build_content_preview(git, c, cfg.max_file_preview)
                preview = build_batch_preview(git, g.files, 2000)
                msg = ollama.generate_group_message(g, preview)
                group_results.append({
                    "group": g.name,
                    "scope": g.scope,
                    "count": len(g.files),
                    "files": [f.path for f in g.files],
                    "generated_message": msg,
                })
            return {"mode": "grouped", "groups": group_results}

        else:
            # Single mode
            for c in candidates:
                c.content_preview = build_content_preview(git, c, cfg.max_file_preview)
            ollama.generate_parallel(candidates, max_workers=cfg.concurrency)
            return {
                "mode": "single",
                "total_files": len(candidates),
                "files": [
                    {
                        "path": c.path,
                        "change_type": c.change_type.value,
                        "generated_message": c.suggested_message,
                        "security_warnings": c.security_warnings,
                    }
                    for c in candidates
                ],
            }

    @app.post("/api/v1/commit")
    def execute_commit(req: CommitRequest):
        git = _get_git(req.repo_path)
        cfg = Config()
        candidates = _get_candidates(git, req)
        if req.limit:
            candidates = candidates[: req.limit]

        if not candidates:
            return {"committed": 0, "failed": 0, "results": []}

        # Check secret scan
        if not req.skip_secret_scan:
            for c in candidates:
                if c.security_warnings:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Security alert on file {c.path}: {c.security_warnings[0]}",
                    )
                diff = git.get_diff(c.path)
                findings = SecretScanner.scan_text(diff)
                if findings:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Blocked commit: secret found in {c.path}: {findings[0].description}",
                    )

        ollama = OllamaService(
            model=cfg.ollama_model,
            host=cfg.ollama_host,
            style=CommitStyle(req.style),
        )

        results = []
        mode = req.mode.lower()

        if mode == CommitMode.ALL.value:
            for c in candidates:
                c.content_preview = build_content_preview(git, c, cfg.max_file_preview)
            batch_preview = build_batch_preview(git, candidates, 3000)
            msg = ollama.generate_batch_message(batch_preview)
            paths = [c.path for c in candidates]
            try:
                git.stage_multiple(paths)
                commit_hash = git.commit(msg, signoff=req.signoff)
                results.append({
                    "files": paths,
                    "message": msg,
                    "commit_hash": commit_hash,
                    "status": "success",
                })
            except GitError as e:
                raise HTTPException(status_code=500, detail=f"Git commit failed: {e}")

        elif mode == CommitMode.GROUPED.value:
            groups = git.group_changes(candidates)
            for g in groups:
                for c in g.files:
                    c.content_preview = build_content_preview(git, c, cfg.max_file_preview)
                preview = build_batch_preview(git, g.files, 2000)
                msg = ollama.generate_group_message(g, preview)
                paths = [f.path for f in g.files]
                try:
                    git.stage_multiple(paths)
                    commit_hash = git.commit(msg, signoff=req.signoff)
                    results.append({
                        "group": g.scope,
                        "files": paths,
                        "message": msg,
                        "commit_hash": commit_hash,
                        "status": "success",
                    })
                except GitError as e:
                    results.append({
                        "group": g.scope,
                        "files": paths,
                        "message": msg,
                        "error": str(e),
                        "status": "failed",
                    })

        else:
            # Single mode
            for c in candidates:
                c.content_preview = build_content_preview(git, c, cfg.max_file_preview)
            ollama.generate_parallel(candidates, max_workers=cfg.concurrency)
            for c in candidates:
                msg = c.suggested_message or f"chore: update {c.path}"
                try:
                    git.stage(c.path, c.original_path)
                    commit_hash = git.commit(msg, signoff=req.signoff)
                    results.append({
                        "file": c.path,
                        "message": msg,
                        "commit_hash": commit_hash,
                        "status": "success",
                    })
                except GitError as e:
                    results.append({
                        "file": c.path,
                        "message": msg,
                        "error": str(e),
                        "status": "failed",
                    })

        push_status = None
        if req.push and git.has_remote():
            try:
                git.push()
                push_status = "pushed"
            except GitError as e:
                push_status = f"failed: {e}"

        return {
            "mode": mode,
            "total": len(candidates),
            "results": results,
            "push_status": push_status,
        }

    @app.post("/api/v1/generate")
    def generate_message_from_diff(req: GenerateTextRequest):
        cfg = Config()
        ollama = OllamaService(
            model=cfg.ollama_model,
            host=cfg.ollama_host,
            style=CommitStyle(req.style),
        )
        msg = ollama.generate_batch_message(req.diff_text[:3500], req.scope_hint)
        return {"commit_message": msg}

    return app


def start_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    if not FASTAPI_AVAILABLE:
        print("[ERROR] FastAPI and Uvicorn are required to run the server.")
        print("Run: pip install 'smart-committer[server]' or uv pip install fastapi uvicorn")
        return

    app = create_app()
    print(f"[INFO] Starting Smart Committer Microservice on http://{host}:{port}")
    print(f"[INFO] Interactive API Documentation: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="info")
