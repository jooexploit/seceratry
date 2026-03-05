# Contributing Guide

Thank you for contributing to Personal Assistant v2.

This project is feature-rich and runtime-sensitive (timers, reminders, OS adapters, Telegram, dashboard), so we use a strict contribution workflow for stability and security.

## Table of Contents
- Before You Start
- Development Setup
- Branch and Commit Workflow
- Coding Standards
- Testing Requirements
- Security Requirements
- Documentation Requirements
- Pull Request Checklist
- Review and Merge Policy
- Release Notes Contributions

## Before You Start
- Read `README.md` fully.
- Read `docs/IMPLEMENTATION_TODO.md` to understand active roadmap items.
- Open an issue for significant changes before coding.

## Development Setup

1. Clone and install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Configure local secrets:

```bash
cp .env.example .env
```

3. Validate runtime configuration:

```bash
python3 personal_assistant.py --validate-config
```

4. Run tests:

```bash
python3 -m pytest -q
```

## Branch and Commit Workflow
- Create topic branches from `main`.
- Suggested branch names:
  - `feat/<short-feature-name>`
  - `fix/<short-bug-name>`
  - `docs/<short-doc-name>`
  - `chore/<short-task-name>`
- Commit style recommendation (Conventional Commits):
  - `feat: add telegram weekly summary command`
  - `fix: prevent duplicate weekly report sends`
  - `docs: improve setup section in README`

## Coding Standards
- Python code should stay explicit and readable.
- Preserve backward compatibility for existing commands/endpoints unless intentionally versioned.
- Do not hardcode secrets.
- Avoid OS-specific logic in shared code paths when adapter methods exist.
- Keep feature additions behind config/feature flags where appropriate.

## Testing Requirements
Every change should include or update tests when applicable.

Minimum expectations:
- Unit tests for new logic in `assistant_app/services`, migrations, or runtime helpers.
- Regression coverage for fixed bugs.
- Ensure `python3 -m pytest -q` passes locally.

For platform behavior:
- If Linux-only behavior is changed, validate Linux path manually.
- If Windows adapter is changed, include best-effort local verification notes in PR description.

## Security Requirements
- Never commit production tokens, OAuth secrets, or credential files.
- Keep `.env` local only.
- If adding logs, ensure sensitive values are not leaked.
- If security-related code changes are introduced, explain threat/risk in PR description.

## Documentation Requirements
Update docs whenever behavior changes:
- `README.md` for user-facing setup/usage changes.
- `docs/IMPLEMENTATION_TODO.md` for roadmap checklist progress.
- `docs/ROLLOUT_AND_ROLLBACK.md` when rollout strategy changes.
- API changes should be reflected in README endpoint sections.

## Pull Request Checklist
Before opening PR, confirm all items:

- [ ] Code builds and tests pass (`python3 -m pytest -q`)
- [ ] No secrets introduced
- [ ] Backward compatibility checked for existing commands/endpoints
- [ ] New behavior documented in README/docs
- [ ] Migration impact reviewed (if DB schema touched)
- [ ] Feature flags/defaults reviewed
- [ ] Rollback path considered for risky changes

## Review and Merge Policy
- At least one maintainer review required.
- High-risk areas (security, migrations, startup flow, power commands, platform adapters) require explicit reviewer sign-off.
- Squash merge is preferred for clean history unless maintainers request otherwise.

## Release Notes Contributions
For user-visible changes, include in PR description:
- What changed
- Why it changed
- How to enable/disable it
- Any migration or config action required
- Any platform limitations (Linux/Windows)
