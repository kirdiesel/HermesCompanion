# Security policy

## Supported state

Hermes Companion is currently a dry-run MVP. The framework-neutral core and offline smoke CLI are supported for evaluation. A production Telegram deployment is environment-specific and must pass the gates documented in `docs/live_run_aiogram3.md`.

## Reporting a vulnerability

Use GitHub's private security-advisory workflow for the repository. Do not open a public issue containing a token, chat ID, conversation content, database, local path, or other sensitive evidence.

Include only the minimum reproduction details needed to confirm the issue. Replace real credentials and personal data with synthetic values.

## Credential rules

- Keep live values only in the local `.env` or an external secret manager.
- Never commit `.env`, databases, logs, state files, private keys, or exported conversations.
- Use a dedicated bot token and an explicit allowed-chat list for a live deployment.
- Rotate a credential immediately if it appears in Git history, logs, screenshots, or issue content.

## Deployment boundary

The core does not provide a complete production security perimeter. Deployers remain responsible for authentication, authorization, network exposure, backups, retention, monitoring, incident response, and applicable privacy requirements.
