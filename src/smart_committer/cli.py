import sys
from pathlib import Path

import questionary
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .config import Config
from .file_filter import FileFilter
from .git_service import GitError, GitService
from .logger import setup_project_logger
from .models import ChangeType, CommitMode, CommitStyle, FileChange
from .ollama_service import OllamaService
from .secret_scanner import SecretScanner
from .utils import build_batch_preview, build_content_preview


def _parse_change_type(status: str) -> ChangeType:
    if status == "??" or "A" in status:
        return ChangeType.ADDED
    if "R" in status:
        return ChangeType.RENAMED
    if "D" in status:
        return ChangeType.DELETED
    return ChangeType.MODIFIED


def _print_banner(console: Console, repo_root: Path, cfg: Config, mode: str) -> None:
    console.print(
        Panel.fit(
            f"[bold cyan]Smart Committer[/bold cyan]\n"
            f"Project:     [yellow]{repo_root}[/yellow]\n"
            f"Model:       [magenta]{cfg.ollama_model}[/magenta]  ([dim]{cfg.ollama_host}[/dim])\n"
            f"Commit Mode: [green]{mode}[/green]\n"
            f"Style:       [blue]{cfg.commit_style}[/blue]\n"
            f"Logs:        [dim]{cfg.log_dir / repo_root.name}[/dim]",
            border_style="cyan",
            title="[bold]System Ready[/bold]",
        )
    )


def _ask_confirm(prompt: str, default: bool = False) -> bool:
    try:
        answer = questionary.confirm(prompt, default=default).ask()
    except (KeyboardInterrupt, EOFError):
        return False
    return bool(answer) if answer is not None else default


def handle_hook_execution(msg_file_path: str) -> None:
    """Invoked by git's prepare-commit-msg hook to populate commit message."""
    path = Path(msg_file_path)
    if not path.exists():
        return

    cfg = Config()
    git = GitService(Path.cwd())
    if not git.is_repo():
        return

    status = git.get_status()
    staged = [item for item in status if item[0][0] in ("M", "A", "R", "D")]
    if not staged:
        return

    diff = git.get_staged_diff()
    if not diff:
        return

    try:
        ollama = OllamaService(
            model=cfg.ollama_model,
            host=cfg.ollama_host,
            style=CommitStyle(cfg.commit_style),
        )
        msg = ollama.generate_batch_message(diff[:3000])
        if msg:
            path.write_text(f"{msg}\n", encoding="utf-8")
    except Exception:
        pass


def run(args) -> None:
    console = Console()

    # Special mode: git hook runner
    if getattr(args, "hook_mode", None):
        handle_hook_execution(args.hook_mode)
        return

    # Special subcommand: hook management
    if getattr(args, "command", None) == "hook":
        git = GitService(Path(args.path or ".").expanduser().resolve())
        if not git.is_repo():
            console.print("[red][ERROR] Not a git repository.[/red]")
            sys.exit(1)

        if args.hook_action == "install":
            hook = git.install_prepare_commit_msg_hook()
            console.print(f"[green][OK] prepare-commit-msg hook installed successfully to: {hook}[/green]")
            return
        elif args.hook_action == "uninstall":
            removed = git.uninstall_prepare_commit_msg_hook()
            if removed:
                console.print("[green][OK] Git hook uninstalled successfully.[/green]")
            else:
                console.print("[yellow][INFO] No smart-committer git hook found to uninstall.[/yellow]")
            return

    # Special subcommand: models
    if getattr(args, "command", None) == "models":
        cfg = Config().override(ollama_host=getattr(args, "ollama_host", None))
        console.print(f"[cyan][INFO] Querying Ollama models from {cfg.ollama_host}...[/cyan]")
        try:
            models = OllamaService.health_check(cfg.ollama_host)
            table = Table(title="Available Ollama Models", box=box.ROUNDED)
            table.add_column("Model Name", style="bold cyan")
            for m in models:
                table.add_row(m)
            console.print(table)
        except Exception as e:
            console.print(f"[red][ERROR] Failed to query Ollama:[/red] {e}")
        return

    # Determine mode
    selected_mode = "single"
    if getattr(args, "mode", None):
        selected_mode = args.mode
    elif getattr(args, "all", False):
        selected_mode = "all"
    elif getattr(args, "grouped", False):
        selected_mode = "grouped"

    cfg = Config().override(
        ollama_model=getattr(args, "model", None),
        ollama_host=getattr(args, "ollama_host", None),
        log_dir=Path(args.log_dir).expanduser().resolve() if getattr(args, "log_dir", None) else None,
        commit_mode=selected_mode,
        commit_style=getattr(args, "style", None),
        concurrency=getattr(args, "concurrency", None),
    )

    project_path = (
        Path(args.path).expanduser().resolve() if getattr(args, "path", None) else Path.cwd()
    )
    if not project_path.exists():
        console.print(f"[bold red][ERROR] Path does not exist:[/bold red] {project_path}")
        sys.exit(1)

    git = GitService(project_path)
    if not git.is_repo():
        console.print(f"[bold red][ERROR] Not a git repository:[/bold red] {project_path}")
        sys.exit(1)
    repo_root = git.repo_root

    logger = setup_project_logger(cfg.log_dir, repo_root.name)
    logger.info("Starting smart-committer for %s with model %s [mode=%s]", repo_root, cfg.ollama_model, selected_mode)

    _print_banner(console, repo_root, cfg, selected_mode)

    # Health check
    try:
        available = OllamaService.health_check(cfg.ollama_host)
    except RuntimeError as e:
        console.print(f"[bold red][ERROR] {e}[/bold red]")
        sys.exit(1)

    if cfg.ollama_model not in available:
        console.print(
            f"[yellow][WARN] Model '{cfg.ollama_model}' is not available in local Ollama instance.[/yellow]"
        )
        console.print(f"Available models: {', '.join(available) or '(none)'}")
        if not _ask_confirm("Continue anyway (Ollama will attempt pull or fail)?", default=False):
            sys.exit(1)

    if not git.has_user_config():
        console.print("[bold red][ERROR] git user.name / user.email is not configured.[/bold red]")
        console.print('Run: git config --global user.name "Your Name"')
        console.print('Run: git config --global user.email "you@example.com"')
        sys.exit(1)

    # Status check
    status_entries = git.get_status()
    if not status_entries:
        console.print("[green][OK] Working tree clean. Nothing to commit.[/green]")
        return

    ff = FileFilter(
        includes=getattr(args, "include", []),
        excludes=getattr(args, "exclude", []),
        force_includes=getattr(args, "force_include", []),
    )

    candidates: list[FileChange] = []
    for xy, path, orig in status_entries:
        if not ff.is_allowed(path):
            logger.debug("Filtered out %s (%s)", path, xy)
            continue
        change = FileChange(
            path=path,
            status=xy,
            change_type=_parse_change_type(xy),
            original_path=orig,
        )
        candidates.append(change)

    if not candidates:
        console.print("[yellow][INFO] No eligible files after filtering.[/yellow]")
        return

    tree_depth = getattr(args, "tree_depth", 0) or 0
    if tree_depth > 0:
        candidates = git.apply_tree_depth(candidates, tree_depth)

    if getattr(args, "limit", None):
        candidates = candidates[: args.limit]

    # Secret scanning
    skip_secrets = getattr(args, "skip_secret_scan", False)
    if not skip_secrets:
        security_flagged = 0
        for c in candidates:
            if SecretScanner.is_sensitive_filename(c.path):
                c.security_warnings.append(f"Sensitive filename matched: {c.path}")
                security_flagged += 1

            diff = git.get_diff(c.path)
            findings = SecretScanner.scan_text(diff)
            for f in findings:
                c.security_warnings.append(f.snippet)
                security_flagged += 1

        if security_flagged > 0:
            console.print(
                Panel.fit(
                    f"[bold red][ALERT] Potential secrets or credentials detected in {security_flagged} occurrence(s)![/bold red]\n"
                    + "\n".join(
                        f"[yellow]- {c.path}:[/yellow] {w}"
                        for c in candidates
                        for w in c.security_warnings
                    ),
                    title="[bold red]Security Guard Active[/bold red]",
                    border_style="red",
                )
            )
            if not _ask_confirm("Potential secrets found. Do you really wish to proceed?", default=False):
                console.print("[red][ABORT] Aborted due to security warnings.[/red]")
                return

    # Files table preview
    table = Table(
        title=f"Eligible Changes ({len(candidates)} file(s))",
        box=box.ROUNDED,
        show_lines=False,
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Type", style="cyan", width=10)
    table.add_column("Path", style="white")
    table.add_column("Security", style="magenta")

    for i, c in enumerate(candidates, 1):
        sec = "[red]WARN[/red]" if c.security_warnings else "[green]CLEAN[/green]"
        table.add_row(str(i), c.change_type.value, c.path, sec)
    console.print(table)

    if not getattr(args, "yes", False) and not getattr(args, "dry_run", False):
        prompt_text = (
            f"Commit {len(candidates)} file(s) in batch (mode: {selected_mode})?"
            if selected_mode != "single"
            else f"Commit {len(candidates)} file(s) one-by-one?"
        )
        if not _ask_confirm(prompt_text, default=True):
            console.print("[yellow][INFO] Aborted by user.[/yellow]")
            return

    # Execution according to mode
    ollama = OllamaService(
        model=cfg.ollama_model,
        host=cfg.ollama_host,
        style=CommitStyle(cfg.commit_style),
    )

    dry_run = getattr(args, "dry_run", False)
    interactive = getattr(args, "interactive", False)
    signoff = getattr(args, "signoff", False)
    committed = 0
    failed = 0

    # MODE: ALL (Batch Commit)
    if selected_mode == "all":
        with console.status("[cyan][PROGRESS] Generating holistic commit message via Ollama...[/cyan]"):
            for c in candidates:
                c.content_preview = build_content_preview(git, c, cfg.max_file_preview)
            batch_summary = build_batch_preview(git, candidates, 3500)
            msg = ollama.generate_batch_message(batch_summary)

        console.print(
            Panel.fit(
                f"[yellow]{msg}[/yellow]",
                title="[bold]Generated Batch Commit Message[/bold]",
                border_style="cyan",
            )
        )

        if dry_run:
            console.print("[green][DRY-RUN] Staged all files. Commit not created.[/green]")
            return

        if interactive:
            edited = questionary.text("Edit commit message (or press Enter to accept):", default=msg).ask()
            if edited and edited.strip():
                msg = edited.strip()

        try:
            paths = [c.path for c in candidates]
            git.stage_multiple(paths)
            commit_hash = git.commit(msg, signoff=signoff)
            committed = len(paths)
            console.print(f"[green][OK] Committed {len(paths)} files in commit {commit_hash}.[/green]")
            logger.info("Batch commit %s created for %d files", commit_hash, len(paths))
        except GitError as e:
            console.print(f"[red][FAIL] Batch commit failed: {e}[/red]")
            logger.error("Batch commit failed: %s", e)
            failed = len(candidates)

    # MODE: GROUPED (Grouped by module / directory)
    elif selected_mode == "grouped":
        groups = git.group_changes(candidates)
        console.print(f"[cyan][INFO] Partitioned into {len(groups)} logical groups.[/cyan]")

        for group_idx, g in enumerate(groups, 1):
            with console.status(f"[cyan][PROGRESS] Generating message for group '{g.scope}' ({len(g.files)} files)...[/cyan]"):
                for c in g.files:
                    c.content_preview = build_content_preview(git, c, cfg.max_file_preview)
                preview = build_batch_preview(git, g.files, 2500)
                msg = ollama.generate_group_message(g, preview)

            console.print(f"[bold cyan]Group {group_idx}/{len(groups)} [{g.scope}]:[/bold cyan] [yellow]{msg}[/yellow]")

            if dry_run:
                continue

            if interactive:
                edited = questionary.text(f"Edit message for group '{g.scope}':", default=msg).ask()
                if edited and edited.strip():
                    msg = edited.strip()

            try:
                paths = [f.path for f in g.files]
                git.stage_multiple(paths)
                h = git.commit(msg, signoff=signoff)
                committed += len(paths)
                console.print(f"[green][OK] Committed group '{g.scope}' ({h})[/green]")
            except GitError as e:
                failed += len(g.files)
                console.print(f"[red][FAIL] Commit for group '{g.scope}' failed: {e}[/red]")

    # MODE: SINGLE (One-by-one commit)
    else:
        # Step 1: Pre-generate messages concurrently with progress bar
        console.print("[cyan][PROGRESS] Generating commit messages in parallel...[/cyan]")
        for c in candidates:
            c.content_preview = build_content_preview(git, c, cfg.max_file_preview)

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        )

        with progress:
            task = progress.add_task("Querying Ollama...", total=len(candidates))

            def on_progress(completed, total, change, msg):
                progress.update(task, description=f"[cyan]Generated[/cyan] {completed}/{total} {change.path}")
                progress.advance(task)

            ollama.generate_parallel(candidates, max_workers=cfg.concurrency, on_progress=on_progress)

        # Step 2: Commit one by one
        for i, change in enumerate(candidates, 1):
            msg = change.suggested_message or f"chore: update {change.path}"

            if dry_run:
                console.print(
                    f"[dim]{i:>3}.[/dim] {change.path}  [green]->[/green] [yellow]{msg}[/yellow]"
                )
                continue

            if interactive:
                edited = questionary.text(
                    f"Message for {change.path}:", default=msg
                ).ask()
                if edited is None:
                    logger.info("Skipped by user: %s", change.path)
                    continue
                edited = edited.strip()[:72]
                if edited:
                    msg = edited

            try:
                git.stage(change.path, change.original_path)
                h = git.commit(msg, signoff=signoff)
                committed += 1
                console.print(
                    f"[green][OK]  [/green] [dim]{i:>3}.[/dim] [{h}] {change.path} -> [yellow]{msg}[/yellow]"
                )
            except GitError as e:
                failed += 1
                console.print(f"[red][FAIL][/red] [dim]{i:>3}.[/dim] {change.path} [red]{e}[/red]")
                logger.error("Commit failed for %s: %s", change.path, e)

    console.print()
    console.print(
        Panel.fit(
            f"[bold green]Committed files:[/bold green] {committed}\n"
            f"[bold red]Failed files:[/bold red]    {failed}",
            title="Execution Summary",
            border_style="green" if failed == 0 else "yellow",
        )
    )

    if dry_run or committed == 0:
        return

    # Push
    if getattr(args, "no_push", False):
        return

    if not git.has_remote():
        console.print("[yellow][INFO] No git remote configured. Skipping push.[/yellow]")
        return

    should_push = getattr(args, "push", False)
    if not should_push:
        should_push = _ask_confirm("Push commits to remote now?", default=False)

    if should_push:
        branch = git.get_current_branch()
        with console.status(f"[cyan][PROGRESS] Pushing {branch}...[/cyan]"):
            try:
                git.push()
                console.print(f"[green][OK] Pushed branch {branch} successfully.[/green]")
                logger.info("Pushed branch %s", branch)
            except GitError as e:
                console.print(f"[red][ERROR] Push failed:[/red] {e}")
                logger.error("Push failed: %s", e)
