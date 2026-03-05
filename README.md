# Personal Assistant v2

Personal Assistant v2 is a Python productivity and spiritual workflow assistant with:
- prayer reminders and tracking,
- Pomodoro and health reminders,
- Google Calendar integration,
- Quran progress gate and goals,
- Telegram remote control,
- live web dashboard,
- cross-platform runtime behavior (Linux + Windows adapters).

This repository is designed for local-first usage with strong runtime observability, feature flags, and secure secret handling.

## Table of Contents
- Project Goals
- Core Features
- Architecture
- Repository Structure
- Requirements
- Quick Start
- Configuration
- Security Model
- Runtime Modes and Feature Flags
- CLI Reference
- Telegram Bot Commands
- Dashboard API Reference
- Autostart Installation
- Testing and CI
- Packaging
- Troubleshooting
- Roadmap and Status
- Contributing

## Project Goals
- Keep the assistant local-first and reliable.
- Support daily workflow automation and spiritual habits in one runtime.
- Keep command/control available from desktop, dashboard, and Telegram.
- Maintain Linux baseline behavior while supporting Windows parity.
- Keep the system debuggable through logs, runtime status, and doctor diagnostics.

## Core Features

### Productivity
- Pomodoro loop with focus minutes tracking.
- Workday limit alerts.
- Meeting reminders and prep notes from Google Calendar.
- Auto-focus around meetings (feature-flagged).

### Wellbeing
- Water and stretch reminders.
- Eye-strain (20-20-20) reminders.

### Prayer and Quran
- Daily prayer timings and reminders.
- Prayer status tracking (`prayed` / `missed`) and streak metrics.
- Prayer recovery flow for missed prayers.
- Quran gate UI with notes/bookmarks and persisted progress.
- Quran daily goal and progress tracking.

### Control Surfaces
- Telegram bot commands and inline control panel.
- Dashboard with live status, thread health, controls, toggles, and metrics.
- Optional tray controls.

### Ops and Security
- Linux/Windows platform adapter layer.
- Capability reporting (`--print-capabilities`, `/api/capabilities`).
- `.env` support and secret redaction.
- Doctor diagnostics (`--run-doctor`).
- Autostart installers for Linux and Windows.

## Architecture

### Entrypoint
- `personal_assistant.py` is a compatibility launcher that calls `assistant_app.main.main()`.

### Main Runtime
- `assistant_app/main.py` contains the orchestration loop, thread runtime, Telegram and dashboard integrations, and backward-compatible flow.

### Platform Adapter
- `assistant_app/platform/base.py` defines the runtime contract.
- `assistant_app/platform/linux.py` implements Linux behavior.
- `assistant_app/platform/windows.py` implements Windows behavior.
- `assistant_app/platform/__init__.py` selects adapter by OS.

### Service Layer
- `assistant_app/services/*` hosts modular service utilities (scoring and helper abstractions).

### Persistence and Migrations
- `assistant_app/main.py` includes `AssistantDB`.
- `assistant_app/migrations.py` adds v2 tables:
  - `schema_migrations`
  - `app_settings`
  - `weekly_report_log`

### Install Helpers
- `assistant_app/install/linux_autostart.py`
- `assistant_app/install/windows_autostart.py`

## Repository Structure

```text
assistant_app/
  main.py
  config.py
  runtime_state.py
  migrations.py
  platform/
  services/
  integrations/
  install/
personal_assistant.py
requirements.txt
tests/
docs/
.github/workflows/ci.yml
scripts/
```

## Requirements
- Python 3.11+
- Linux or Windows desktop session
- Optional integrations:
  - Google Calendar OAuth credentials
  - Telegram bot token and allowed chat IDs

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Quick Start

1. Create `.env` from template:

```bash
cp .env.example .env
```

2. Fill required secrets in `.env`:
- `TELEGRAM_BOT_TOKEN`
- `QURAN_CLIENT_ID`
- `QURAN_CLIENT_SECRET`

3. Validate config:

```bash
python3 personal_assistant.py --validate-config
```

4. Run:

```bash
python3 personal_assistant.py
```

## Configuration
Primary configuration is `config.json`.

Important top-level sections:
- `security`
- `features`
- `personal_modes`
- `prayers`
- `pomodoro`
- `health`
- `eye_strain`
- `google_calendar`
- `focus_mode`
- `quran_khatma`
- `telegram_bot`
- `dashboard`

Environment variables override sensitive/runtime values.

## Security Model
- Secret material should be provided through environment variables or `.env`.
- When `security.require_env_secrets=true`, startup validation fails if required secret env vars are missing.
- Logs and runtime error messages redact configured secret values when `security.redact_secrets_in_logs=true`.
- `.env` is ignored by git.
- Do not commit real secrets to `config.json`, helper scripts, or docs.

## Runtime Modes and Feature Flags
Feature flags live under `features` and are reflected in dashboard/telemetry. Examples:
- `telegram_inline_panel`
- `telegram_sensitive_confirm`
- `calendar_auto_focus`
- `daily_score`
- `quran_goals`
- `prayer_recovery_flow`
- `weekly_report_push`
- `personal_modes`

Personal modes:
- `workday`
- `light`
- `ramadan`

Mode can be set from Telegram (`/mode`) or dashboard (`/action/mode`).

## CLI Reference

```bash
python3 personal_assistant.py --status
python3 personal_assistant.py --validate-config
python3 personal_assistant.py --print-capabilities
python3 personal_assistant.py --run-doctor
python3 personal_assistant.py --install-autostart
python3 personal_assistant.py --uninstall-autostart
```

## Telegram Bot Commands
Existing commands are preserved and v2 adds:
- `/panel`
- `/mode <workday|light|ramadan>`
- `/goal [units]`
- `/weekly`

Sensitive power actions can require callback confirmation when `telegram_sensitive_confirm` is enabled.

## Dashboard API Reference
Core endpoints:
- `GET /api/status`
- `GET /api/events`
- `GET /api/errors`

v2 endpoints:
- `GET /api/capabilities`
- `GET /api/score`
- `POST /action/mode`
- `POST /action/quran_goal`
- `POST /action/mark_prayer`

## Autostart Installation
Use cross-platform installer commands:

```bash
python3 personal_assistant.py --install-autostart
python3 personal_assistant.py --uninstall-autostart
```

Behavior:
- Linux: writes/removes XDG autostart desktop entry.
- Windows: creates/removes Task Scheduler ONLOGON task.

## Testing and CI
Run locally:

```bash
python3 -m pytest -q
```

CI matrix (`.github/workflows/ci.yml`) runs on:
- `ubuntu-latest`
- `windows-latest`

## Packaging
Build scripts:
- Linux: `scripts/build_dist.sh`
- Windows: `scripts/build_dist.ps1`

Both use PyInstaller one-file mode.

## Troubleshooting

### Validation fails with missing env vars
If `security.require_env_secrets=true`, set required env vars in `.env`.

### Telegram bot not responding
Check:
- `telegram_bot.enabled`
- `TELEGRAM_BOT_TOKEN`
- `allowed_chat_ids`

### Screenshot commands fail
Run diagnostics:

```bash
python3 personal_assistant.py --run-doctor
```

Verify screenshot capability in output.

### Dashboard does not open automatically
Check dashboard config:
- `dashboard.enabled`
- `dashboard.host`
- `dashboard.port`
- `dashboard.auto_open_on_start`

## Roadmap and Status
Implementation checklist and rollout notes:
- `docs/IMPLEMENTATION_TODO.md`
- `docs/ROLLOUT_AND_ROLLBACK.md`

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md).
