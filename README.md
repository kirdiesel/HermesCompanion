# Hermes Companion

Reusable Telegram human-in-the-loop core for AI agents: render a result, request a decision, persist it safely, and continue the workflow without coupling the domain logic to a Telegram framework.

The project is designed for self-hosted assistants, internal automation, and agent platforms that need an explicit review step before a result is accepted or written to a knowledge base.

## What it solves

AI workflows often produce useful results but leave approval, revision, and follow-up actions scattered across chats and tools. Hermes Companion provides one deterministic interaction loop:

```text
incoming request
    → agent result
    → Telegram review card
    → accept / revise / next
    → durable decision
    → optional knowledge-base write
```

## Core capabilities

- Framework-neutral rendering of progress, review, and final-result messages.
- Typed callbacks for `accept`, `revise`, and `next` actions.
- Sequential attention items with inline decisions and stale-callback protection.
- Transactional SQLite state for restart recovery and concurrent callbacks.
- Idempotent, atomic Obsidian persistence in a dedicated namespace.
- Telegram-like dry-run CLI that requires no token, polling, or network access.
- Adapter boundary for an existing agent gateway, avoiding a second polling consumer.
- Fail-closed checkpoint script with secret scanning and test gates.

## Safety model

The default workflow is offline and dry-run:

- no BotFather token is required;
- no Telegram updates are consumed;
- no messages are sent;
- no real knowledge-base path is required;
- `.env`, SQLite state, logs, and local orchestration files are ignored by Git.

Live polling, webhook mode, real Telegram delivery, and production knowledge-base writes are separate deployment decisions. See [SECURITY.md](SECURITY.md) and [the aiogram runbook](docs/live_run_aiogram3.md).

## Maturity

Current stage: tested dry-run MVP.

- 93 offline tests pass on Python 3.11.
- Rendering, callbacks, attention dispatch, persistence, restart recovery, and gateway action planning are covered.
- The reusable core is implemented; production deployment still requires an environment-specific gateway adapter and an explicit credential/configuration review.

## Quick start

Requirements: Python 3.11+ and Git.

```powershell
git clone https://github.com/kirdiesel/HermesCompanion.git
Set-Location HermesCompanion

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest
python -m pytest -q
```

Run the no-network smoke example:

```powershell
$env:PYTHONPATH = (Resolve-Path "src")
python -m tg_companion_bot.smoke_cli --input examples\telegram_message_update.json
```

The JSON response should report:

- `ok: true`;
- `mode: dry_run`;
- `requires_token: false`;
- `consumes_updates: false`;
- `sends_messages: false`;
- a Telegram-ready payload with review buttons.

## Architecture

The package separates domain behavior from delivery and storage:

- `rendering.py` — statuses, result text, and decision keyboards;
- `callbacks.py` — review actions and callback semantics;
- `attention_items.py` / `attention_dispatcher.py` — sequential decisions;
- `live_runtime.py` — message and callback orchestration;
- `telegram_framework_adapter.py` — Telegram-like update mapping;
- `runtime_state_store.py` — transactional SQLite state;
- `obsidian.py` — idempotent knowledge-base persistence;
- `hermes_gateway_adapter.py` — action plans for an external agent gateway;
- `smoke_cli.py` — offline executable demonstration.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component boundaries and extension points.

## Optional live adapter dependencies

The reusable core has no mandatory runtime dependencies. For an `aiogram 3` integration:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Keep `DRY_RUN=true` until token ownership, allowed chat IDs, polling conflicts, and storage paths have been reviewed.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [aiogram 3 dry-run and live gates](docs/live_run_aiogram3.md)
- [Gateway integration boundary](docs/hermes_gateway_integration.md)
- [Runtime state store](docs/runtime_state_store.md)
- [Multi-writer knowledge-base contract](docs/vault_multi_writer_contract.md)
- [Nightly checkpoint safety gates](docs/nightly_git_checkpoint.md)

The root-level `PROJECT_CONTEXT.md`, `HERMES_BRIEF.md`, `AGENT_MANIFEST.md`, `BACKLOG.md`, and `PROJECT_STATUS_SUMMARY.md` retain implementation history. They are not required to embed the reusable core.

## Commercial use

Suitable delivery models include a reusable core plus paid deployment, gateway integration, organization-specific policies, monitoring, and support. Production use should add environment-specific authentication, authorization, audit retention, privacy rules, and operational ownership.

## License

Licensed under Apache-2.0. See `LICENSE`.

## Security reports

Do not publish tokens, chat IDs, private conversation content, or production paths in an issue. Follow [SECURITY.md](SECURITY.md) for private reporting guidance.
