# MK Service Bot (public mirror)

Sanitized public mirror of a private operational platform for a vending service
network: Telegram field bot, HTTP webhooks, admin UI, event sourcing, and
integrations.

## What this mirror contains

- Application source under `src/`
- Automated tests (excluding live credential suites)
- Docker / Compose scaffolding and process entrypoints
- Public-mirror build policy under `scripts/public_mirror/`

## What is intentionally omitted

Internal documentation, company operating model, discovery notes, deployment
runbooks, task tracker files, agent-process corpus, business catalog dumps, and
secrets / live account files are **not** published here.

Documentation is for internal use and is not part of this public mirror.

## Local development (high level)

This mirror is meant for reading and limited local experimentation. It is not a
complete ops package.

```bash
cp .env.example .env.dev
uv sync
uv run python run.py
```

Fill only placeholder values in `.env.dev`. Never commit real tokens or
credential JSON files.

## Rebuild policy

If you are working from the private repository:

```bash
uv run python scripts/build_public_mirror.py --out ../mk_service_bot-public --force
```
