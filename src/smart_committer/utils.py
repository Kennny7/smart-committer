from pathlib import Path
from .git_service import GitService
from .models import ChangeType, FileChange


def build_content_preview(git: GitService, change: FileChange, max_chars: int) -> str:
    """Build a concise diff or content preview to feed into the local LLM."""
    if change.change_type is ChangeType.DELETED:
        return "(file deleted)"

    if change.change_type is ChangeType.RENAMED and change.original_path:
        return f"(renamed from {change.original_path})"

    if change.change_type is ChangeType.ADDED:
        full = git.repo_root / change.path
        if full.is_dir():
            files = [str(f.relative_to(full)).replace("\\", "/") for f in full.rglob("*") if f.is_file()]
            return f"(directory containing {len(files)} file(s): {', '.join(files[:8])})"
        try:
            data = full.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            return "(binary or unreadable file)"
        return data[:max_chars]

    diff = git.get_diff(change.path) or git.get_staged_diff(change.path)
    if not diff:
        return "(no diff available)"
    return diff[:max_chars]


def build_batch_preview(git: GitService, changes: list[FileChange], max_chars: int = 4000) -> str:
    """Build a multi-file structural summary for batch or grouped commits."""
    lines: list[str] = []
    lines.append(f"Changed files count: {len(changes)}")
    for c in changes[:25]:
        lines.append(f"- [{c.change_type.value}] {c.path}")
    if len(changes) > 25:
        lines.append(f"... and {len(changes) - 25} more files")

    lines.append("\nSample diffs:")
    budget_per_file = max(150, max_chars // max(1, min(len(changes), 6)))
    for c in changes[:6]:
        preview = build_content_preview(git, c, budget_per_file)
        lines.append(f"--- {c.path} ({c.change_type.value}) ---")
        lines.append(preview[:budget_per_file])

    summary = "\n".join(lines)
    return summary[:max_chars]
