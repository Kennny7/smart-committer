import os
import subprocess
from pathlib import Path

from .logger import get_logger
from .models import CommitGroup, FileChange

logger = get_logger(__name__)


class GitError(RuntimeError):
    pass


class GitService:
    def __init__(self, start_path: Path):
        self.start_path = start_path
        self.repo_root = self._find_root()

    # Low level runner
    def _run(self, *args: str, check: bool = True) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self.start_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as e:
            raise GitError("git executable not found on PATH") from e

        if check and result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise GitError(f"git {' '.join(args)} -> {err}")
        return result.stdout

    def _find_root(self) -> Path:
        out = self._run("rev-parse", "--show-toplevel").strip()
        return Path(out)

    # Queries
    def is_repo(self) -> bool:
        try:
            self._run("rev-parse", "--is-inside-work-tree")
            return True
        except GitError:
            return False

    def has_user_config(self) -> bool:
        try:
            name = self._run("config", "user.name", check=False).strip()
            email = self._run("config", "user.email", check=False).strip()
            return bool(name and email)
        except GitError:
            return False

    def get_current_branch(self) -> str:
        branch = self._run("rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
        return branch or "main"

    def has_remote(self) -> bool:
        try:
            return bool(self._run("remote", check=False).strip())
        except GitError:
            return False

    def get_status(self, untracked_mode: str = "all") -> list[tuple[str, str, str | None]]:
        """Return list of (status_xy, path, original_path_for_rename).
        
        Uses -uall by default so files inside untracked directories are individually enumerated.
        If git ever returns a directory with a trailing slash, it expands all files recursively.
        """
        cmd = ["status", "--porcelain=v1"]
        if untracked_mode == "all":
            cmd.append("-uall")
        elif untracked_mode == "normal":
            cmd.append("-unormal")

        out = self._run(*cmd)
        entries: list[tuple[str, str, str | None]] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            status = line[:2]
            rest = line[3:]
            orig = None
            if " -> " in rest:
                orig, rest = rest.split(" -> ", 1)
            path = rest.strip().strip('"')
            orig = orig.strip().strip('"') if orig else None

            # If git reported a directory with trailing slash, expand files recursively
            disk_path = self.repo_root / path
            if disk_path.is_dir():
                for sub in sorted(disk_path.rglob("*")):
                    if sub.is_file():
                        rel = str(sub.relative_to(self.repo_root)).replace("\\", "/")
                        entries.append((status, rel, None))
            else:
                entries.append((status, path, orig))
        return entries

    def get_diff(self, rel_path: str) -> str:
        return self._run("diff", "--", rel_path, check=False)

    def get_staged_diff(self, rel_path: str | None = None) -> str:
        if rel_path:
            return self._run("diff", "--cached", "--", rel_path, check=False)
        return self._run("diff", "--cached", check=False)

    def get_full_diff(self) -> str:
        """Combined diff of unstaged and staged changes."""
        staged = self._run("diff", "--cached", check=False)
        unstaged = self._run("diff", check=False)
        return (staged + "\n" + unstaged).strip()

    # Mutations
    def stage(self, rel_path: str, original: str | None = None) -> None:
        if original:
            self._run("add", "-A", "--", original, rel_path)
        else:
            self._run("add", "-A", "--", rel_path)

    def stage_multiple(self, paths: list[str]) -> None:
        if not paths:
            return
        chunk_size = 50
        for i in range(0, len(paths), chunk_size):
            chunk = paths[i : i + chunk_size]
            self._run("add", "-A", "--", *chunk)

    def unstage_all(self) -> None:
        self._run("reset", check=False)

    def commit(self, message: str, signoff: bool = False) -> str:
        cmd = ["commit", "-m", message]
        if signoff:
            cmd.append("-s")
        out = self._run(*cmd)
        hash_out = self._run("rev-parse", "--short", "HEAD", check=False).strip()
        return hash_out

    def push(self, set_upstream: bool = True) -> None:
        branch = self.get_current_branch()
        if set_upstream:
            try:
                self._run("push", "--set-upstream", "origin", branch)
                return
            except GitError:
                pass
        self._run("push")

    # Grouping helpers
    @staticmethod
    def group_changes(candidates: list[FileChange]) -> list[CommitGroup]:
        """Group files by logical component/directory scope."""
        groups_dict: dict[str, list[FileChange]] = {}
        for c in candidates:
            parts = Path(c.path).parts
            if len(parts) > 1:
                scope = parts[0]
                if scope in ("src", "lib", "app", "packages") and len(parts) > 2:
                    scope = f"{parts[0]}/{parts[1]}"
            else:
                scope = "root"
            c.group = scope
            groups_dict.setdefault(scope, []).append(c)

        result: list[CommitGroup] = []
        for scope, files in sorted(groups_dict.items()):
            result.append(
                CommitGroup(
                    name=scope,
                    scope=scope,
                    files=files,
                )
            )
        return result

    @staticmethod
    def apply_tree_depth(candidates: list[FileChange], tree_depth: int = 0) -> list[FileChange]:
        """Collapse files deeper than tree_depth into their parent directory.

        If tree_depth <= 0 (default), all files are preserved individually (unlimited depth).
        If tree_depth > 0, files deeper than tree_depth are collapsed to that directory level.
        """
        if tree_depth <= 0:
            return candidates

        from .models import ChangeType

        collapsed_dict: dict[str, list[FileChange]] = {}
        for c in candidates:
            parts = Path(c.path).parts
            if len(parts) > tree_depth:
                collapsed_key = "/".join(parts[:tree_depth])
            else:
                collapsed_key = c.path

            collapsed_dict.setdefault(collapsed_key, []).append(c)

        result: list[FileChange] = []
        for key, files in collapsed_dict.items():
            if len(files) == 1 and files[0].path == key:
                result.append(files[0])
            else:
                has_added = any(f.change_type == ChangeType.ADDED for f in files)
                has_deleted = any(f.change_type == ChangeType.DELETED for f in files)
                change_type = (
                    ChangeType.ADDED
                    if has_added and not any(f.change_type == ChangeType.MODIFIED for f in files)
                    else ChangeType.DELETED
                    if has_deleted and len(files) == sum(1 for f in files if f.change_type == ChangeType.DELETED)
                    else ChangeType.MODIFIED
                )
                warnings = [w for f in files for w in f.security_warnings]
                combined = FileChange(
                    path=key,
                    status="M" if change_type == ChangeType.MODIFIED else "A",
                    change_type=change_type,
                    original_path=None,
                    security_warnings=warnings,
                )
                result.append(combined)
        return result

    # Git Hook Integration
    def install_prepare_commit_msg_hook(self) -> Path:
        hooks_dir = self.repo_root / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / "prepare-commit-msg"

        # Cross-platform bash script calling smart-committer
        hook_script = """#!/usr/bin/env sh
# Installed by smart-committer
COMMIT_MSG_FILE=$1
COMMIT_SOURCE=$2
SHA1=$3

# Only generate if committing with no message specified
if [ -z "$COMMIT_SOURCE" ] || [ "$COMMIT_SOURCE" = "message" ]; then
    if [ ! -s "$COMMIT_MSG_FILE" ] || grep -q '^[[:space:]]*$' "$COMMIT_MSG_FILE"; then
        smart-committer --hook-mode "$COMMIT_MSG_FILE"
    fi
fi
"""
        hook_path.write_text(hook_script, encoding="utf-8")
        try:
            # Set executable bit on unix-like systems
            os.chmod(hook_path, 0o755)
        except OSError:
            pass
        return hook_path

    def uninstall_prepare_commit_msg_hook(self) -> bool:
        hook_path = self.repo_root / ".git" / "hooks" / "prepare-commit-msg"
        if hook_path.exists():
            content = hook_path.read_text(encoding="utf-8", errors="ignore")
            if "smart-committer" in content:
                hook_path.unlink()
                return True
        return False
