# Rollout and Rollback

## Rollout Order
1. Deploy foundation only with all new feature flags in `features.*` set to `false`.
2. Enable `daily_score` and `telegram_inline_panel`.
3. Enable `calendar_auto_focus` and `personal_modes`.
4. Enable `quran_goals`, `prayer_recovery_flow`, and `weekly_report_push`.
5. Monitor logs for `calendar`, `telegram`, `focus_mode`, and `screenshot` error sources.

## Immediate Rollback
1. Disable high-risk features via config flags:
   - `features.calendar_auto_focus = false`
   - `features.telegram_sensitive_confirm = false`
   - `features.weekly_report_push = false`
2. Keep adapter layer active; it is backward compatible.
3. If startup issues occur, run with:
   - `python personal_assistant.py --run-doctor`
   - `python personal_assistant.py --validate-config`

## Security Rollback Consideration
- Do not roll back hardcoded secrets.
- If needed, set `security.require_env_secrets = false` temporarily while fixing env setup.

## Verification Commands
- `python personal_assistant.py --print-capabilities`
- `python personal_assistant.py --run-doctor`
- `pytest -q`
