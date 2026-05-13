# One-Shot Coding Agent

An autonomous coding agent that takes a single instruction and produces a tested, CI-passing PR — with zero human interaction in between. Built on top of [Open SWE](https://github.com/langchain-ai/open-swe) by LangChain.

Inspired by [Stripe's Minions architecture](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents).

## Architecture

```
Trigger (Slack / Jira webhook)
       |
       v
Open SWE Fork (LangGraph + FastAPI)
       |
  PHASE 1: DETERMINISTIC (0 tokens)
    - Clone repo in sandbox
    - Extract keywords from task
    - ripgrep search -> rank files -> top 20-30
    - Extract function signatures
    - Inject as "starting context" to LLM (ADDITIVE, not restrictive)
       |
  PHASE 2: AGENTIC (LLM)
    - Agent reads AGENTS.md (repo conventions)
    - Reads targeted files, implements fix
    - Writes tests for its changes
       |
  PHASE 3: DETERMINISTIC (0 tokens)
    - ESLint autofix + check (changed files only)
    - Run migrations (seed DB)
    - Run tests (existing + agent-written)
    - 1 retry per stage if failures
       |
  PHASE 4: OUTPUT
    - git commit + push
    - gh pr create --draft
    - Notify Slack/Jira
       |
       v
Output: Draft PR for human review
```

## Custom Components (on top of Open SWE)

### Pre-Filter Middleware (`agent/middleware/prefilter_context.py`)

`@before_model` hook that runs on the first LLM turn only. Saves 2-3 turns of blind searching.

- Extracts keywords from task description (no LLM, pure text processing)
- Runs ripgrep in sandbox to find matching files
- Ranks files by relevance (filename match, path match, entry-point patterns)
- Injects top 20-30 files + function signatures + git history as starting context

**Additive, not restrictive** — agent retains full grep/glob/read access for anything the pre-filter missed.

| Match quality | What happens |
|--------------|-------------|
| 3+ files match | Full context: files + signatures + git log |
| 1-2 files match | Partial context + "search more broadly" note |
| No matches | Directory skeleton for orientation |
| No keywords | Does nothing — agent explores on its own |

### Deterministic Checks Middleware (`agent/middleware/deterministic_checks.py`)

`@after_agent` hook that runs lint and tests deterministically after the agent finishes writing code.

- Parses `context.yaml` for repo-specific commands
- Supports `scope: changed_files_only` — lint only files the agent touched
- Seeds database if configured (migrations)
- Discovers related test files via `test_mapping` rules + agent-written `.test.` files
- Max 1 retry per stage, then creates PR with status labels

### Per-Repo Config (2 files)

**`AGENTS.md`** — Everything the LLM needs (architecture, conventions, commands). Single source of truth.

**`context.yaml`** — Only what deterministic code parses (lint command, test command, test file mapping, sandbox services).

See `repo-configs/TEMPLATE-AGENTS.md` and `repo-configs/TEMPLATE-context.yaml` for templates.

## Sandbox

The sandbox Docker image includes services tests depend on:

- Node.js 22
- PostgreSQL 15 (pre-initialized with test user/db)
- Redis 7
- RabbitMQ 3.12
- GitHub CLI

Services start in <5 seconds via `sandbox-entrypoint.sh`.

## Setup

### 1. Install dependencies

```bash
make install   # uv pip install -e .
```

### 2. Configure environment

```bash
# Model
export LLM_MODEL_ID="anthropic:claude-sonnet-4-6"
export LLM_FALLBACK_MODEL_ID="anthropic:claude-haiku-4-5"

# Sandbox provider (modal, daytona, langsmith, local)
export SANDBOX_TYPE="modal"

# GitHub App
export GITHUB_APP_ID="..."
export GITHUB_APP_PRIVATE_KEY="..."
export GITHUB_APP_INSTALLATION_ID="..."

# Slack
export SLACK_SIGNING_SECRET="..."
export SLACK_BOT_TOKEN="..."

# LangGraph state DB
export LANGGRAPH_STORAGE_URI="postgresql://user:pass@host:5432/agent_db"
```

### 3. Add config to your repo

Drop `AGENTS.md` and `context.yaml` at the root of any repo you want the agent to work on. Use the templates in `repo-configs/`.

### 4. Run

```bash
make dev    # LangGraph dev server + webhook server
```

### 5. Trigger

Tag `@your-agent` in Slack with a task description and `repo:owner/name`.

## Onboarding a New Repo

1. Copy `repo-configs/TEMPLATE-AGENTS.md` to your repo root as `AGENTS.md`
2. Copy `repo-configs/TEMPLATE-context.yaml` to your repo root as `context.yaml`
3. Fill in the blanks (stack, architecture, commands, test mapping)
4. No agent code changes needed — works for any stack (Node, Python, Go, Ruby, etc.)

## Key Design Decisions

- **Pre-filter is additive, not restrictive** — performance optimization, not a gate
- **No zone definitions** — AGENTS.md describes architecture, LLM figures out zones
- **Changed-files-only linting** — new code must be clean, legacy code untouched
- **Agent writes tests** — since most repos lack coverage, agent writes focused tests for its changes
- **Max 1 retry per stage** — diminishing returns beyond that, hand to human
- **Seed DB in sandbox** — tests run against real services, not mocks

## References

- [Stripe Minions Part 1](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents)
- [Stripe Minions Part 2](https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2)
- [Open SWE](https://github.com/langchain-ai/open-swe)
- [Anthropic Harness Engineering](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
