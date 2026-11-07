from dataclasses import dataclass, field
from enum import Enum


class CommitMode(str, Enum):
    SINGLE = "single"          # One commit per file
    ALL = "all"                # One atomic commit for all staged files
    GROUPED = "grouped"        # Grouped by directory / logical module


class CommitStyle(str, Enum):
    CONVENTIONAL = "conventional"  # feat(scope): message
    SIMPLE = "simple"              # Short sentence / imperative
    GITMOJI = "gitmoji"            # Text tag format like [FEAT], [FIX]
    CUSTOM = "custom"              # User defined format


class ChangeType(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass
class FileChange:
    path: str
    status: str
    change_type: ChangeType
    original_path: str | None = None
    content_preview: str = ""
    diff: str = ""
    group: str = ""
    suggested_message: str | None = None
    security_warnings: list[str] = field(default_factory=list)


@dataclass
class CommitGroup:
    name: str
    scope: str
    files: list[FileChange]
    suggested_message: str | None = None


@dataclass
class CommitResult:
    success: bool
    message: str
    files: list[str]
    commit_hash: str | None = None
    error: str | None = None
