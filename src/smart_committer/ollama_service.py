import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import ollama

from .logger import get_logger
from .models import ChangeType, CommitGroup, CommitStyle, FileChange

logger = get_logger(__name__)

_PROMPT_SINGLE_CONVENTIONAL = """You are a senior engineer writing a single-line git commit message.

File: {path}
Change type: {change_type}
{context}

Strict rules:
- Output ONLY the commit message. No quotes, no markdown, no conversational text.
- Format: <type>(<scope>): <short description>
- Allowed types: feat, fix, docs, style, refactor, test, chore, build, ci, perf
- Maximum 72 characters on ONE line.

Commit message:"""

_PROMPT_SINGLE_SIMPLE = """You are a software engineer writing a clean, direct, imperative git commit message.

File: {path}
Change type: {change_type}
{context}

Strict rules:
- Output ONLY the commit message. No quotes, no markdown, no explanation.
- Start with an imperative verb (e.g. Add, Fix, Update, Remove, Refactor).
- Maximum 72 characters on ONE line.

Commit message:"""

_PROMPT_SINGLE_GITMOJI = """You are a developer writing a git commit message with text tags.

File: {path}
Change type: {change_type}
{context}

Strict rules:
- Output ONLY the commit message. No quotes, no markdown.
- Format: [<TAG>] <short description>
- Allowed tags: [FEAT], [FIX], [DOCS], [STYLE], [REFACTOR], [TEST], [CHORE], [PERF], [BUILD], [CI]
- Maximum 72 characters on ONE line.

Commit message:"""

_PROMPT_BATCH_CONVENTIONAL = """You are a lead architect writing an atomic git commit message for multiple related changes.

Summary of changes:
{context}

Strict rules:
- Output ONLY the commit message. No quotes, no markdown, no preamble.
- Line 1: <type>(<scope>): <high-level summary> (max 72 chars)
- Allowed types: feat, fix, docs, style, refactor, test, chore, build, ci, perf
- Optional body: list 2 to 4 bullet points starting with '- ' detailing key updates.

Commit message:"""

_FALLBACK_TYPES = {
    ChangeType.ADDED: "feat",
    ChangeType.MODIFIED: "chore",
    ChangeType.DELETED: "chore",
    ChangeType.RENAMED: "refactor",
}


class OllamaService:
    def __init__(self, model: str, host: str, style: CommitStyle = CommitStyle.CONVENTIONAL):
        self.model = model
        self.host = host
        self.style = style
        self.client = ollama.Client(host=host)

    @staticmethod
    def health_check(host: str) -> list[str]:
        url = host.rstrip("/") + "/api/tags"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "smart-committer"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Cannot reach Ollama at {host}: {e}") from e
        return [m.get("name") or m.get("model", "") for m in data.get("models", [])]

    def _clean_message(self, raw: str) -> str:
        text = (raw or "").strip()
        # Remove markdown code fences if model enclosed response in ```
        raw_lines = text.splitlines()
        filtered_lines = [
            line.strip()
            for line in raw_lines
            if line.strip() and not line.strip().startswith("```")
        ]
        if not filtered_lines:
            return ""

        # First line is subject
        subject = filtered_lines[0].strip('`"\'*#- ')
        if len(filtered_lines) > 1 and filtered_lines[1].startswith("-"):
            # Multi-line commit message
            body = "\n".join(filtered_lines[1:])
            return f"{subject}\n\n{body}"
        return subject[:72]

    def generate_message(self, change: FileChange) -> str:
        context = (
            f"Content preview:\n{change.content_preview}"
            if change.content_preview
            else ""
        )

        if self.style == CommitStyle.SIMPLE:
            template = _PROMPT_SINGLE_SIMPLE
        elif self.style == CommitStyle.GITMOJI:
            template = _PROMPT_SINGLE_GITMOJI
        else:
            template = _PROMPT_SINGLE_CONVENTIONAL

        prompt = template.format(
            path=change.path,
            change_type=change.change_type.value,
            context=context,
        )

        try:
            resp = self.client.generate(
                model=self.model,
                prompt=prompt,
                options={
                    "temperature": 0.2,
                    "num_predict": 75,
                    "stop": ["\n\n", "```"],
                },
            )
            raw = (
                resp["response"]
                if isinstance(resp, dict)
                else getattr(resp, "response", "")
            )
        except Exception as e:
            logger.warning("Ollama call failed for %s: %s", change.path, e)
            return self._fallback(change)

        msg = self._clean_message(raw)
        if not msg:
            return self._fallback(change)
        return msg

    def generate_batch_message(self, context_summary: str, scope_hint: str | None = None) -> str:
        prompt = _PROMPT_BATCH_CONVENTIONAL.format(context=context_summary)
        try:
            resp = self.client.generate(
                model=self.model,
                prompt=prompt,
                options={
                    "temperature": 0.2,
                    "num_predict": 120,
                    "stop": ["```"],
                },
            )
            raw = (
                resp["response"]
                if isinstance(resp, dict)
                else getattr(resp, "response", "")
            )
            msg = self._clean_message(raw)
            if msg:
                return msg
        except Exception as e:
            logger.warning("Ollama batch generation failed: %s", e)

        scope = scope_hint or "project"
        return f"chore({scope}): update project files and dependencies"

    def generate_group_message(self, group: CommitGroup, preview: str) -> str:
        prompt = (
            f"You are a developer committing changes to scope '{group.scope}'.\n"
            f"Files in this group ({len(group.files)}):\n"
            + "\n".join(f"- {f.path}" for f in group.files[:15])
            + f"\n\nContext preview:\n{preview}\n\n"
            + "Strict rules:\n"
            + f"- Format: <type>({group.scope}): <short description>\n"
            + "- Allowed types: feat, fix, docs, style, refactor, test, chore, perf\n"
            + "- Maximum 72 characters on one line.\n"
            + "- Output ONLY the commit message."
        )
        try:
            resp = self.client.generate(
                model=self.model,
                prompt=prompt,
                options={"temperature": 0.2, "num_predict": 60, "stop": ["\n"]},
            )
            raw = (
                resp["response"]
                if isinstance(resp, dict)
                else getattr(resp, "response", "")
            )
            msg = self._clean_message(raw)
            if msg:
                return msg
        except Exception as e:
            logger.warning("Ollama group generation failed for %s: %s", group.scope, e)

        return f"chore({group.scope}): update {len(group.files)} file(s)"

    def generate_parallel(
        self,
        changes: list[FileChange],
        max_workers: int = 4,
        on_progress: Callable[[int, int, FileChange, str], None] | None = None,
    ) -> list[str]:
        """Generate messages for candidates in parallel with progress reporting."""
        results: list[str] = [""] * len(changes)
        total = len(changes)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(self.generate_message, change): idx
                for idx, change in enumerate(changes)
            }

            completed_count = 0
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                change = changes[idx]
                try:
                    msg = future.result()
                except Exception as e:
                    logger.warning("Error generating for %s: %s", change.path, e)
                    msg = self._fallback(change)

                results[idx] = msg
                change.suggested_message = msg
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, total, change, msg)

        return results

    def _fallback(self, change: FileChange) -> str:
        prefix = _FALLBACK_TYPES.get(change.change_type, "chore")
        if self.style == CommitStyle.GITMOJI:
            return f"[{prefix.upper()}] update {change.path}"[:72]
        if self.style == CommitStyle.SIMPLE:
            return f"Update {change.path}"[:72]
        return f"{prefix}: update {change.path}"[:72]
