"""Conservative local secret scan used beside the CI Gitleaks scan."""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".tmp", "node_modules", ".venv"}
PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai_like_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "high_entropy_assignment",
        re.compile(r"(?i)\b(?:api[_-]?key|secret|password|token|credential)\s*[:=]\s*['\"][A-Za-z0-9+/=_-]{24,}['\"]"),
    ),
)


def _files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:
            continue
        yield path, data.decode("utf-8", errors="replace")


def scan(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for path, text in _files(root):
        for line_number, line in enumerate(text.splitlines(), 1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(f"{path.relative_to(root).as_posix()}:{line_number}:{label}")
    return sorted(set(findings))


def main() -> int:
    findings = scan(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT)
    for finding in findings:
        print(finding)
    print(f"secret_findings={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
