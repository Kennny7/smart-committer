import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


@dataclass
class Config:
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    log_dir: Path = field(
        default_factory=lambda: _expand(os.getenv("LOG_DIR", "~/.smart-committer/logs"))
    )
    max_file_preview: int = int(os.getenv("MAX_FILE_PREVIEW", "2500"))
    max_diff_preview: int = int(os.getenv("MAX_DIFF_PREVIEW", "3500"))
    commit_mode: str = os.getenv("SMART_COMMITTER_MODE", "single")
    commit_style: str = os.getenv("SMART_COMMITTER_STYLE", "conventional")
    concurrency: int = int(os.getenv("SMART_COMMITTER_CONCURRENCY", "4"))
    secret_scan: bool = os.getenv("SMART_COMMITTER_SECRET_SCAN", "true").lower() in ("1", "true", "yes")
    server_host: str = os.getenv("SMART_COMMITTER_HOST", "127.0.0.1")
    server_port: int = int(os.getenv("SMART_COMMITTER_PORT", "8000"))

    def override(self, **kwargs) -> "Config":
        for k, v in kwargs.items():
            if v is not None and hasattr(self, k):
                setattr(self, k, v)
        return self
