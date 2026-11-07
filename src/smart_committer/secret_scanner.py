import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SecretFinding:
    rule_id: str
    description: str
    line_number: int
    snippet: str


_PATTERNS = [
    (
        "private-key",
        "Private Cryptographic Key",
        re.compile(r"-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP|ENCRYPTED)?\s*PRIVATE KEY-----", re.IGNORECASE),
    ),
    (
        "aws-access-key",
        "AWS Access Key ID",
        re.compile(r"(?<![A-Z0-9])[A-Z0-9]{20}(?![A-Z0-9])", re.IGNORECASE),
    ),
    (
        "aws-secret-key",
        "AWS Secret Access Key",
        re.compile(r"(?:aws_secret_access_key|aws_sec_key|secret_key)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?", re.IGNORECASE),
    ),
    (
        "github-pat",
        "GitHub Personal Access Token",
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,255}"),
    ),
    (
        "slack-token",
        "Slack Bot/User Token",
        re.compile(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}"),
    ),
    (
        "generic-api-key",
        "Generic API Key / Secret Token",
        re.compile(
            r"(?:api_key|apikey|secret_key|auth_token|access_token|private_token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,80}['\"]",
            re.IGNORECASE,
        ),
    ),
    (
        "db-connection-string",
        "Database Connection String with Credentials",
        re.compile(r"(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis)://[^:\s]+:[^@\s]+@", re.IGNORECASE),
    ),
    (
        "jwt-token",
        "JSON Web Token (JWT)",
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]{10,}\.[A-Za-z0-9._-]{10,}"),
    ),
]


class SecretScanner:
    """Detect potential credentials and sensitive keys in file content or diffs."""

    @staticmethod
    def is_sensitive_filename(file_path: str) -> bool:
        path = Path(file_path)
        name = path.name.lower()
        sensitive_names = {
            ".env",
            ".env.local",
            ".env.production",
            ".env.staging",
            "id_rsa",
            "id_ed25519",
            "id_ecdsa",
            "id_dsa",
            "credentials.json",
            "service-account.json",
            "client_secrets.json",
            "token.json",
        }
        if name in sensitive_names:
            return True
        if name.startswith(".env.") and not name.endswith(".example"):
            return True
        sensitive_suffixes = {".pem", ".key", ".pkcs12", ".p12", ".pfx", ".kdbx"}
        if path.suffix.lower() in sensitive_suffixes:
            return True
        return False

    @classmethod
    def scan_text(cls, text: str, max_findings: int = 5) -> list[SecretFinding]:
        findings: list[SecretFinding] = []
        if not text:
            return findings

        lines = text.splitlines()
        for line_idx, line in enumerate(lines, start=1):
            if len(line) > 1000:
                continue  # skip minified / binary rows
            for rule_id, desc, pattern in _PATTERNS:
                match = pattern.search(line)
                if match:
                    raw = match.group(0)
                    # Redact middle characters for safe terminal reporting
                    if len(raw) > 8:
                        redacted = f"{raw[:4]}...{raw[-4:]}"
                    else:
                        redacted = "****"
                    snippet = f"Line {line_idx}: {desc} ({redacted})"
                    findings.append(
                        SecretFinding(
                            rule_id=rule_id,
                            description=desc,
                            line_number=line_idx,
                            snippet=snippet,
                        )
                    )
                    if len(findings) >= max_findings:
                        return findings
        return findings
