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
