# Default Prompt — Organization Conventions

## Default Organization

When no repository is specified, assume the organization is `my-org`.

## Repository Routing

Common repos and their shorthand:
- `backend` → `my-org/backend`
- `frontend` → `my-org/frontend`

## Organization Conventions

- Use conventional commits: `fix:`, `feat:`, `chore:`, `refactor:`
- Always reference the ticket in commit messages when provided
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
- If an existing pattern is vulnerable, do not follow it — apply best practice instead
- Do not commit files that contain secrets (.env, credentials.json, etc.)
