from __future__ import annotations

import re
import subprocess
from pathlib import Path


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"OPENAI_API_KEY\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret", re.compile(r"AWS_SECRET_ACCESS_KEY\s*=\s*['\"]?[A-Za-z0-9/+]{40}")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{24,}")),
    ("nrg_api_key", re.compile(r"nrgk_[a-f0-9]{32}_[A-Za-z0-9_\-]{20,}")),
)


def _tracked_files() -> list[str]:
    try:
        result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return [path for path in files if not path.startswith("var/") and path != ".env"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fall back to filesystem walk in minimal container images without git.
        files: list[str] = []
        for path in Path(".").rglob("*"):
            if not path.is_file():
                continue
            rel = str(path)
            if rel.startswith(".git/") or rel.startswith("var/") or rel.startswith(".venv/"):
                continue
            if rel == ".env":
                continue
            files.append(rel)
        return files


def main() -> int:
    findings: list[str] = []
    for rel_path in _tracked_files():
        path = Path(rel_path)
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(content.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(f"{rel_path}:{line_no}: {label}")
    if findings:
        print("Potential secrets detected:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("No secret patterns detected in tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
