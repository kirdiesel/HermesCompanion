# Nightly Git checkpoint

This command is deterministic and does not use an LLM.

## Dry run

```powershell
python scripts/nightly_git_checkpoint.py --repo C:\AIProjects\Bots\tg-companion-bot
```

It checks repository state, scans candidate Git files for common secret patterns, compiles Python files, and runs the full pytest suite. It does not stage, commit, or push.

## Execute gate

Commit and push require both controls:

```powershell
$env:NIGHTLY_GIT_ALLOW_WRITE='1'
python scripts/nightly_git_checkpoint.py --repo C:\AIProjects\Bots\tg-companion-bot --execute
```

Do not register an external scheduler until the dry run is green and the user explicitly approves scheduler mutation and the first push.

The approved Windows scheduler entrypoint is:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\AIProjects\Bots\tg-companion-bot\scripts\run_nightly_git_checkpoint.ps1
```

Failure is closed: secret scan, compilation, tests, detached HEAD, missing `origin`, commit failure, or push failure returns non-zero and stops the remaining steps.

The script also compares local `HEAD` with `origin/<branch>`. A previously committed but unpushed checkpoint is retried even when the working tree is clean.
