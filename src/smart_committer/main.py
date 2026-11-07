import argparse
import sys

from . import __version__
from .cli import run
from .server import start_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-committer",
        description=(
            "Commit git files with AI-generated commit messages via local Ollama LLMs. "
            "Supports single-file, batch, and grouped commits, with built-in secret scanning "
            "and REST microservice API."
        ),
    )

    # Subparsers for dedicated subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: serve
    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the smart-committer REST API microservice daemon.",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1).",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number to listen on (default: 8000).",
    )

    # Subcommand: hook
    hook_parser = subparsers.add_parser(
        "hook",
        help="Manage git prepare-commit-msg hook integration.",
    )
    hook_parser.add_argument(
        "hook_action",
        choices=["install", "uninstall"],
        help="Install or uninstall prepare-commit-msg hook.",
    )
    hook_parser.add_argument(
        "-p", "--path", help="Target git repository path (default: current directory)."
    )

    # Subcommand: models
    models_parser = subparsers.add_parser(
        "models",
        help="List available models in the target Ollama instance.",
    )
    models_parser.add_argument(
        "--ollama-host", help="Ollama HTTP host (default: http://localhost:11434)."
    )

    # Main CLI arguments (also applied if no subcommand given)
    parser.add_argument(
        "-p", "--path", help="Project repository path (default: current working directory)."
    )
    parser.add_argument(
        "-m",
        "--model",
        help="Ollama model name (default from OLLAMA_MODEL, e.g. qwen2.5:7b).",
    )
    parser.add_argument(
        "--ollama-host", help="Ollama HTTP host (default http://localhost:11434)."
    )
    parser.add_argument(
        "--mode",
        choices=["single", "all", "grouped"],
        default="single",
        help="Commit mode: single (one commit per file), all (atomic commit), grouped (by directory/module).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Shortcut for --mode all (atomic single commit for all eligible files).",
    )
    parser.add_argument(
        "--grouped",
        action="store_true",
        help="Shortcut for --mode grouped (commit by directory/module scope).",
    )
    parser.add_argument(
        "--style",
        choices=["conventional", "simple", "gitmoji"],
        default="conventional",
        help="Commit message style: conventional (<type>(<scope>): desc), simple (Imperative), gitmoji ([TAG] desc).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Number of concurrent worker threads for querying Ollama (default: 4).",
    )
    parser.add_argument(
        "--tree-depth",
        "--max-depth",
        type=int,
        default=0,
        dest="tree_depth",
        help="Depth limit for directory traversal: 0 / unlimited (default) commits every file individually; N > 0 collapses nested changes to depth N.",
    )
    parser.add_argument(
        "-i",
        "--include",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Only include files matching PATTERN (gitignore-style). Repeatable.",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Exclude files matching PATTERN. Repeatable.",
    )
    parser.add_argument(
        "--force-include",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Force include files even if present in default ignore list. Repeatable.",
    )
    parser.add_argument(
        "--skip-secret-scan",
        action="store_true",
        help="Bypass built-in security check for API keys and private tokens.",
    )
    parser.add_argument(
        "-s",
        "--signoff",
        action="store_true",
        help="Add Signed-off-by trailer by the committer at the end of the commit log message.",
    )
    parser.add_argument(
        "--limit", type=int, help="Stop after committing N files or groups."
    )
    parser.add_argument(
        "--log-dir", help="Override log directory (default: ~/.smart-committer/logs)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview generated messages and actions without modifying git repository.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the initial batch confirmation prompt.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt to review/edit each generated message before committing.",
    )
    parser.add_argument(
        "--push", action="store_true", help="Push to remote after committing."
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Never push, even if a remote exists.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Launch the REST API microservice server directly.",
    )
    parser.add_argument(
        "--hook-mode",
        help=argparse.SUPPRESS,  # Internal flag used by prepare-commit-msg
    )
    parser.add_argument(
        "--version", action="version", version=f"smart-committer {__version__}"
    )
    return parser


def app() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if getattr(args, "command", None) == "serve" or getattr(args, "serve", False):
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8000)
        start_server(host=host, port=port)
        return

    try:
        run(args)
    except KeyboardInterrupt:
        print("\n[ABORT] Interrupted by user.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    app()
