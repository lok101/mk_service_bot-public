# План: Compact happy

**Формат:** compact-v1

## Outcome 1: Lint detects compact marker

**Acceptance:** closes compact-v1 marker + required outcome fields
**Files:** `scripts/lint_plans_lib/compact.py`
**Tests:** happy, edge, error
**Risk:** low
**Verification:**
- `uv run pytest tests/scripts/lint_plans_tests/test_compact_v1.py -q`

- [ ] Outcome delivered
