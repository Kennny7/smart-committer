from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitIgnoreSpecPattern

from .logger import get_logger

logger = get_logger(__name__)

# Always excluded unless the user explicitly force-includes them.
DEFAULT_IGNORE_PATTERNS = [
    # Git
    ".git/",
    ".git/**",
    # Python
    "__pycache__/",
    "*.py[cod]",
    "*.egg-info/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".tox/",
    ".nox/",
    "*.egg",
    # Virtual envs
    "venv/",
    ".venv/",
    "env/",
    "ENV/",
    "pip-wheel-metadata/",
    # Node / Web
    "node_modules/",
    ".next/",
    ".nuxt/",
    "dist/",
    "build/",
    "coverage/",
    ".cache/",
    "*.tsbuildinfo",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    # Angular
    ".angular/",
    # Flutter / Dart
    ".dart_tool/",
    ".flutter-plugins",
    ".flutter-plugins-dependencies",
    ".packages",
    ".pub-cache/",
    ".pub/",
    "*.g.dart",
    "*.freezed.dart",
    # Databases & storage
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.db-journal",
    "*.db-wal",
    "*.db-shm",
    # Logs
    "*.log",
    "logs/",
    # IDE & Editors
    ".vscode/",
    ".idea/",
    "*.swp",
    "*.swo",
    "*~",
    # OS files
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    # Sensitive / Secrets (Force-include required if truly wanted)
    ".env",
    ".env.*",
    "!.env.example",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "id_rsa*",
    "id_ed25519*",
    "credentials.json",
    # Binaries & Compiled
    "*.tmp",
    "*.bak",
    "*.orig",
    "target/",       # Rust
    ".terraform/",
    ".gradle/",
    "*.exe",
    "*.dll",
    "*.so",
    "*.dylib",
    "*.iso",
    "*.bin",
    "*.tar.gz",
    "*.zip",
    "*.7z",
]


class FileFilter:
    """Combines default ignores, user includes, excludes, and force-includes."""

    def __init__(
        self,
        includes: list[str] | None = None,
        excludes: list[str] | None = None,
        force_includes: list[str] | None = None,
    ):
        self._default = PathSpec.from_lines(
            GitIgnoreSpecPattern, DEFAULT_IGNORE_PATTERNS
        )
        self._includes = [
            PathSpec.from_lines(GitIgnoreSpecPattern, [p]) for p in (includes or [])
        ]
        self._excludes = [
            PathSpec.from_lines(GitIgnoreSpecPattern, [p]) for p in (excludes or [])
        ]
        self._force = [
            PathSpec.from_lines(GitIgnoreSpecPattern, [p]) for p in (force_includes or [])
        ]

    def is_allowed(self, rel_path: str) -> bool:
        norm = rel_path.replace("\\", "/")
        if norm.startswith("./"):
            norm = norm[2:]

        # 1. Explicit exclude wins.
        if any(s.match_file(norm) for s in self._excludes):
            return False

        # 2. Explicit force-include overrides defaults.
        if any(s.match_file(norm) for s in self._force):
            return True

        # 3. Default ignores.
        if self._default.match_file(norm):
            return False

        # 4. If user restricted with --include, only those pass.
        if self._includes:
            if not any(s.match_file(norm) for s in self._includes):
                return False

        return True
