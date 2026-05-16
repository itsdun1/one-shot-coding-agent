# {Project Name} - Agent Reference

## Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| Runtime | {e.g., Node.js 22.x} | {e.g., PM2 cluster mode} |
| Language | {e.g., JavaScript (ES6+), TypeScript} | {notes on language split} |
| Framework | {e.g., Express.js 4.x} | {role in the project} |
| Primary DB | {e.g., PostgreSQL} | {ORM: e.g., Sequelize 6.x, migration tool: e.g., Knex.js} |
| Cache | {e.g., Redis 4.x} | {usage: sessions, rate limiting, etc.} |
| Message Queue | {e.g., RabbitMQ} | {client library} |
| Object Storage | {e.g., AWS S3} | {CDN if applicable} |
| Error Tracking | {e.g., Sentry v10} | {instrumentation details} |
| Logging | {e.g., Winston 3.x} | {output format, transports} |
| APM | {e.g., Elastic APM, Datadog} | {agent library} |
| Auth | {e.g., JWT + cookie sessions} | {RBAC details if applicable} |

### Key Libraries
{List important non-obvious dependencies and what they are used for.}

---

## Architecture

### Entry Points

{List all application entry points (servers, workers, etc.) and their purpose.}

| File | Purpose |
|------|---------|
| `{filename}` | {description} |

### Directory Structure

```
{project}/
  {dir}/    # {description}
  ...
```

{For each significant directory, describe:}
- What it contains
- The pattern/convention used (MVC, service-only, etc.)
- How many files/modules (if large)
- How it relates to other directories

### Feature Modules

{If the project has modular feature directories, list each module:}

| Module | Route/Mount | Description |
|--------|------------|-------------|
| `{module}/` | `{route}` | {description} |

### Consumer/Worker Pattern

{Describe how background job consumers work, including base class and how to extend.}

### Models and Migrations

{Describe:}
- Where models live and how they are loaded
- Migration file format and naming convention
- How to create new migrations

---

## Commands

{List all commands from package.json/Makefile/etc.}

| Command | Description |
|---------|-------------|
| `{command}` | {description} |

### Pre-commit Hooks

{Describe any git hooks (husky, lint-staged, etc.)}

---

## Conventions

### Code Style

- **Linter**: {tool and config file}
- **Formatter**: {tool and config file}
- Key rules: {list important non-default rules}
- Ignore patterns: {what is excluded from linting/formatting}

### Logging

{Describe the logging convention: what logger to use, correct/incorrect usage patterns.}

### Database Queries

{Describe: ORM usage, parameterized query requirements, read replica handling.}

### Module/File Patterns

{Describe standard patterns for new modules: file naming, return formats, etc.}

### Error Tracking

{Describe: how errors are reported, initialization requirements.}

### Auth & Authorization

{Describe: middleware, guard functions, how to protect new routes.}

### Constants & Configuration

{Describe: where constants live, config file format, environment handling.}

---

## Testing

### Framework

- **Runner**: {e.g., Mocha, Jest}
- **Assertions**: {e.g., Chai}
- **HTTP testing**: {e.g., Supertest, chai-http}
- **Mocking**: {e.g., Sinon}
- **Coverage**: {e.g., NYC/Istanbul}

### Test Directory Structure

```
test/
  {structure}
```

### Test Setup

{Describe what bootstrap/setup files do: DB initialization, service mocking, etc.}

### Running Tests

```bash
# {List all test commands with descriptions}
{command}    # {description}
```

### Test Environment Requirements

| Service | Host | Port | Database |
|---------|------|------|----------|
| {service} | {host} | {port} | {db name} |

### Test Mapping

{Describe the relationship between source files and test files.}

| Source Path | Test Path |
|-------------|-----------|
| `{source}` | `{test}` |

{Note any gaps in test coverage.}

---

## Agent Rules

### 1. Read Before You Write
- Search for existing implementations before writing new code
- When replacing function calls (e.g. console.log → logger): read the target function's SOURCE CODE first — never assume its API from training data
- When using internal utilities: read their source to understand actual signatures and behavior
- When touching database queries: read the model/schema definitions first

### 2. Implement Carefully
- Make minimal, focused changes — do not modify unrelated code
- Do not duplicate existing utilities — reuse what exists
- Do not hardcode credentials, API keys, or env-specific values
- Do not add placeholder/mock data that could reach production
- For bulk refactoring: change incrementally and verify after each batch

### 3. Validate Before PR (MANDATORY)
Every PR must pass these checks before submission:

| Check | Command | When |
|-------|---------|------|
| **Syntax** | `node -c <file>` or `python -m py_compile <file>` | Always |
| **Import** | `node -e "require('./<file>')"` | Always |
| **Existing tests** | Run tests related to changed files | If tests exist |
| **New tests** | Write minimal test for core behavior | If no tests exist |
| **Business logic** | Verify with concrete example | If logic/rules changed |

A PR with syntax errors, broken imports, or failing tests is unacceptable.

### 4. Common Mistakes to Avoid
- Assuming function signatures from training data instead of reading source
- Silently dropping function parameters (e.g. converting `f(a, b, c)` to `g(a)` without checking if `g` supports the extra args)
- Reimplementing existing utilities instead of importing them
- Changing error handling in a way that hides errors from users
- Adding dependencies without checking if equivalent functionality already exists in the codebase
