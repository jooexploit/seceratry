# Personal Assistant v2 TODO Tracking

## Foundation
- [x] T01 Remove hardcoded secrets from local config/helper scripts
- [x] T02 Add `.env` support and env precedence
- [x] T03 Add secret redaction path in logger/error store
- [x] T04 Build `PlatformAdapter` contract + selector
- [x] T05 Move Linux-specific platform behaviors into Linux adapter
- [x] T06 Add Windows adapter for notifications/screenshot/power/lock/window listing
- [x] T07 Add capability reporting
- [x] T08 Keep compatibility entrypoint while moving runtime to `assistant_app.main`
- [x] T09 Wire feature flags for new features

## Feature Additions
- [x] T10 Telegram inline control panel (`/panel`) and callback actions
- [x] T11 Sensitive power confirmation flow in Telegram
- [x] T12 Auto-focus around calendar meetings
- [x] T13 Daily score engine in runtime + snapshot text
- [x] T14 Quran daily goal persistence/progress tracking
- [x] T15 Prayer recovery reminder flow for missed prayers
- [x] T16 Weekly report push with dedupe log table
- [x] T17 Personal modes (`workday`, `light`, `ramadan`)
- [x] T18 Dashboard API/UI extensions (score/capabilities/mode/goal actions)

## Cross-Platform Ops
- [x] T19 Linux autostart installer/uninstaller CLI
- [x] T20 Windows Task Scheduler installer/uninstaller CLI
- [x] T21 Doctor command with capability + env diagnostics
- [x] T22 Fix stale helper scripts

## Quality & Delivery
- [x] T23 Unit tests for scoring/migrations/runtime token store
- [x] T24 Integration-smoke tests for snapshot formatting
- [x] T25 Migration coverage (idempotent test)
- [x] T26 CI matrix (Linux + Windows)
- [x] T27 Packaging scripts (PyInstaller linux/windows)
- [x] T28 Rollout + rollback notes
- [ ] T29 Full end-to-end acceptance run on native Linux and native Windows sessions

## Notes
- T29 remains manual and environment-dependent (native desktop/session validation required).
