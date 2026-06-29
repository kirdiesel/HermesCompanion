from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


SECRET_PATTERNS = {
    "telegram_token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
FORBIDDEN_NAMES = {".env", "credentials.json", "id_rsa", "id_ed25519"}
MAX_SCAN_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_command(args: Sequence[str], *, cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def git_paths(repo: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode(errors="replace").strip() or "git ls-files failed")
    return [item.decode("utf-8", errors="surrogateescape") for item in completed.stdout.split(b"\0") if item]


def scan_secret_issues(repo: Path, relative_paths: Iterable[str]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for relative_path in relative_paths:
        path = repo / relative_path
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            issues.append({"path": relative_path, "reason": "forbidden_secret_filename"})
            continue
        if not path.is_file() or path.stat().st_size > MAX_SCAN_BYTES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                issues.append({"path": relative_path, "reason": name})
    return issues


def writes_allowed(*, execute: bool, environment: dict[str, str] | None = None) -> bool:
    env = environment if environment is not None else os.environ
    return execute and env.get("NIGHTLY_GIT_ALLOW_WRITE") == "1"


def remote_push_required(local_head: str, remote_result: CommandResult) -> bool:
    if remote_result.returncode == 2:
        return True
    _require_success(remote_result, "git ls-remote")
    remote_line = remote_result.stdout.strip().splitlines()
    remote_head = remote_line[0].split()[0] if remote_line else ""
    return remote_head != local_head


def _require_success(result: CommandResult, label: str) -> None:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{label} failed: {detail}")


def run_checkpoint(repo: Path, *, execute: bool, message: str | None = None) -> dict[str, object]:
    repo = repo.resolve()
    if not (repo / ".git").exists():
        raise RuntimeError(f"not a git repository: {repo}")

    status = run_command(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo)
    _require_success(status, "git status")
    changed_paths = [line[3:] for line in status.stdout.splitlines() if len(line) >= 4]

    candidate_paths = git_paths(repo)
    secret_issues = scan_secret_issues(repo, candidate_paths)
    if secret_issues:
        return {
            "ok": False,
            "mode": "execute" if execute else "dry_run",
            "error": "secret_scan_failed",
            "secret_issues": secret_issues,
            "changed_paths": changed_paths,
        }

    compile_result = run_command(
        [sys.executable, "-m", "compileall", "-q", "src/tg_companion_bot", "scripts"],
        cwd=repo,
    )
    _require_success(compile_result, "py_compile")
    test_result = run_command([sys.executable, "-m", "pytest", "-q"], cwd=repo)
    _require_success(test_result, "pytest")

    branch_result = run_command(["git", "branch", "--show-current"], cwd=repo)
    _require_success(branch_result, "git branch")
    branch = branch_result.stdout.strip()
    if not branch:
        raise RuntimeError("detached HEAD is not allowed")

    remote_result = run_command(["git", "remote", "get-url", "origin"], cwd=repo)
    _require_success(remote_result, "git remote origin")
    head_result = run_command(["git", "rev-parse", "HEAD"], cwd=repo)
    _require_success(head_result, "git rev-parse HEAD")
    remote_head_result = run_command(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
        cwd=repo,
    )
    needs_push = remote_push_required(head_result.stdout.strip(), remote_head_result)

    result: dict[str, object] = {
        "ok": True,
        "mode": "execute" if execute else "dry_run",
        "branch": branch,
        "origin_configured": True,
        "changed_paths": changed_paths,
        "checks": {"secret_scan": "passed", "py_compile": "passed", "pytest": "passed"},
        "would_commit": bool(changed_paths),
        "would_push": bool(changed_paths) or needs_push,
        "unpushed_head": needs_push,
    }

    if not execute:
        return result
    if not writes_allowed(execute=True):
        result.update(
            {
                "ok": False,
                "error": "write_gate_closed",
                "detail": "Set NIGHTLY_GIT_ALLOW_WRITE=1 together with --execute.",
            }
        )
        return result

    committed = False
    commit_message = None
    if changed_paths:
        add_result = run_command(["git", "add", "--all"], cwd=repo)
        _require_success(add_result, "git add")
        staged_result = run_command(["git", "diff", "--cached", "--quiet"], cwd=repo)
        if staged_result.returncode == 1:
            commit_message = message or f"chore: nightly checkpoint {datetime.now().date().isoformat()}"
            commit_result = run_command(["git", "commit", "-m", commit_message], cwd=repo)
            _require_success(commit_result, "git commit")
            committed = True
        elif staged_result.returncode != 0:
            _require_success(staged_result, "git diff --cached")

    should_push = committed or needs_push
    if should_push:
        push_result = run_command(["git", "push", "--set-upstream", "origin", branch], cwd=repo)
        _require_success(push_result, "git push")
    result.update({"committed": committed, "pushed": should_push})
    if commit_message is not None:
        result["commit_message"] = commit_message
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed nightly Git checkpoint for tg-companion-bot.")
    parser.add_argument("--repo", default=".", help="Repository path. Defaults to current directory.")
    parser.add_argument("--execute", action="store_true", help="Enable commit/push when the environment gate is open.")
    parser.add_argument("--message", help="Optional commit message for execute mode.")
    args = parser.parse_args(argv)

    try:
        result = run_checkpoint(Path(args.repo), execute=args.execute, message=args.message)
    except Exception as exc:  # pragma: no cover - command-level guard
        result = {"ok": False, "mode": "execute" if args.execute else "dry_run", "error": "checkpoint_failed", "detail": str(exc)}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
