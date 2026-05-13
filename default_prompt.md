# Default Prompt — Vahan Engineering

## Default Organization

When no repository is specified, assume the organization is `VahanInc`.

## Repository Routing

Common repos and their shorthand:
- `jobfinder` or `jf` → `VahanInc/JobFinder`
- `mitra-leader` or `pwa` → `VahanInc/mitra-leader-pwa`

## Organization Conventions

- Use conventional commits: `fix:`, `feat:`, `chore:`, `refactor:`
- Always reference the Jira ticket in commit messages when provided (e.g., `fix: resolve OTP timeout [VAN-1234]`)
- Tag the requesting user when work is complete
- Never hardcode secrets, credentials, or environment-specific URLs
- Production database changes require a migration file — no direct schema edits

## Code Quality

- All code must pass the repo's configured linter before submission
- Write focused tests for your changes — cover the happy path and the specific bug/feature
- Do not write exhaustive test suites — keep tests minimal and targeted
- Do not refactor or "improve" surrounding code unless explicitly asked

## Security

- Never write raw SQL queries without parameterization
- If an existing pattern is vulnerable (SQL injection, eval, hardcoded secrets), do not follow it — apply best practice instead
- Do not commit files that contain secrets (.env, credentials.json, etc.)
