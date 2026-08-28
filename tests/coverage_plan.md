# AVE Dominaplus Test Coverage Plan (Completed)

Created: 2026-04-14
Last verified: 2026-07-20

Status: completed. The plan below is retained as a historical record of the coverage effort.

## Goal

Build tests in two phases:

1. Phase 1: cover critical, functional, user-impacting behavior.
2. Phase 2: expand to 95%+ total coverage for integration modules.

Current result (from `pytest --cov=custom_components/ave_dominaplus --cov-report=term-missing`):

- Tests: 351 passed
- Total coverage: 99%
- Config flow coverage: 100%
- Lowest individual module: `uid_v2.py` at 93%

## Working Rules For This Effort

- Prioritize behavior that can break real automations and state consistency.
- Prefer deterministic unit tests over fragile integration-heavy tests.
- When a test failure is ambiguous (test may be wrong, code may be right, or vice versa), do not force a fix immediately.
- Record ambiguity in `tests/oddities.md` first, then decide with maintainer input.
- Use temporary `xfail` only when linked to a specific oddity entry.

## Phase 1: Critical Functional Coverage

### Priority A: WebSocket Update Routing (core runtime behavior)

Files:

- `custom_components/ave_dominaplus/web_server.py`

Tests to add first:

- `manage_upd` routes updates to the correct callback by family and settings.
- On/off lights are routed to switch or light based on `on_off_lights_as_switch`.
- Cover updates route only for supported cover families.
- Thermostat update commands route correctly (`WT`, `TM`, `TW`, `TP`, `TT`, `TR`, `TL`, `TLO`, `TO`, `TS`).
- Unknown or unsupported updates do not raise exceptions.
- Behavior remains safe when map/command metadata is not ready.

Why this is critical:

- This is the main event pipeline. If routing is wrong, entities go stale or automations act on wrong state.

### Priority B: Dynamic Entity Create/Update Semantics

Files:

- `custom_components/ave_dominaplus/light.py`
- `custom_components/ave_dominaplus/cover.py`
- `custom_components/ave_dominaplus/switch.py`
- `custom_components/ave_dominaplus/binary_sensor.py`
- `custom_components/ave_dominaplus/sensor.py`

Tests to add first:

- `update_*` functions create entities on first valid update.
- Existing entities are updated (not recreated) on subsequent updates.
- Guarded creation paths behave correctly when identity data is missing (for modules that require `address_dec`).
- Name update policy is respected:
  - AVE name updates apply when enabled.
  - HA user-renamed entities are not overwritten.
- Feature flags (`fetch_lights`, `fetch_covers`, `fetch_sensors`, etc.) correctly suppress creation/update.
- Availability lifecycle paths (`async_added_to_hass`, `async_will_remove_from_hass`) register/unregister cleanly.

Why this is critical:

- Prevents duplicate entities, name regressions, and runtime exceptions in day-to-day usage.

### Priority C: Thermostat Behavior Mapping

Files:

- `custom_components/ave_dominaplus/climate.py`
- `custom_components/ave_dominaplus/ave_thermostat.py`

Tests to add first:

- `update_thermostat` command-to-property mapping for all handled commands.
- Numeric conversions (tenths, offsets, set points) are correct.
- HVAC mode/action and fan level state derivation are correct for representative combinations.
- Command methods call expected webserver APIs.

Why this is critical:

- Thermostat behavior is complex and most likely to produce subtle wrong-state bugs.

### Priority D: Safety/Observability Helpers

Files:

- `custom_components/ave_dominaplus/diagnostics.py`
- `custom_components/ave_dominaplus/uid_v2.py`

Tests to add first:

- Diagnostics redacts host/IP/MAC and masks device names as intended.
- UID build/parse/find helpers handle valid, invalid, and fallback forms.

Why this is critical:

- Protects privacy and ID stability, both important for supportability.

### Phase 1 Exit Criteria

- New tests cover all Priority A and Priority B scenarios.
- Critical thermostat mappings in Priority C have representative coverage.
- `tests/oddities.md` is updated for unresolved ambiguities.
- Coverage target for end of Phase 1: practical step-up (expected ~50-70%), not forced 95%.

## Phase 2: Reach 95%+ Coverage

### Expand Branch Coverage Systematically

- Fill remaining branches in all platform modules.
- Cover reconnect/error paths in `web_server.py` (`authenticate`, `send_ws_command`, disconnect/start loop guards).
- Add adoption/migration edge-case tests for entity/device registry paths.
- Add negative-path diagnostics and helper tests.

### Add Coverage Gate And Tracking

- Add strict CI coverage command for local/CI use:
  - `pytest --cov=custom_components/ave_dominaplus --cov-report=term-missing --cov-fail-under=95`
- Optionally add module-specific minima for high-risk modules after they stabilize.

### Phase 2 Exit Criteria

- Total integration module coverage >= 95%.
- No unresolved high-severity oddities remain open.
- Remaining exclusions are documented and justified.

## Recommended Implementation Order

1. New `tests/test_web_server_routing.py`
2. New `tests/test_light_update_flow.py`
3. New `tests/test_cover_update_flow.py`
4. New `tests/test_switch_update_flow.py`
5. New `tests/test_binary_sensor_update_flow.py`
6. New `tests/test_climate_update_mapping.py`
7. New `tests/test_diagnostics.py`
8. New `tests/test_uid_v2.py`

## Oddity Handling Workflow

- Every questionable failure goes to `tests/oddities.md` before forcing code/test changes.
- Each oddity gets:
  - affected test,
  - expected behavior,
  - observed behavior,
  - hypothesis,
  - proposed next action,
  - status (`open`, `resolved`, `won't-fix`).

This keeps the suite honest while we grow coverage.
