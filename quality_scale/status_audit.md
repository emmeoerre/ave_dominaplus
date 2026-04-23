# AVE Dominaplus Quality Scale Audit

Date: 2026-04-14
Source rules reviewed: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules

Legend:
- Covered: already implemented in code/docs
- Missing: not implemented yet
- N/A: not applicable to this integration in the current design

## Bronze

1. action-setup
Status: N/A
Evidence: no custom integration service actions are registered today.
Action: checklist can be treated as satisfied-by-scope; if service actions are introduced later, register them in async_setup and validate entry availability in the service handler.

2. appropriate-polling
Status: Covered
Evidence: integration is push/event-driven; AveHubStatusBinarySensor no longer polls and now reflects live websocket connection state.
Action: if a polling entity is introduced in the future, define and document an explicit scan interval.

3. brands
Status: Covered
Evidence: branding assets exist in home-assistant/brands under custom_integrations/ave_dominaplus with icon.png and logo.png.
Action: optional improvement only: add dark and @2x variants if you want sharper theme-specific visuals.

4. common-modules
Status: Covered
Evidence: reusable logic extracted in uid_v2.py, ave_map.py, ave_thermostat.py, web_server.py, const.py.
Action: keep consolidating duplicated parsing/name helpers during refactors.

5. config-flow-test-coverage
Status: Covered
Evidence: tests/test_config_flow.py now covers user flow, zeroconf flow, duplicate prevention, legacy adoption paths, reconfigure flow, and error/recovery branches with 100% coverage for custom_components/ave_dominaplus/config_flow.py.
Action: keep tests updated whenever new config/reconfigure flow branches are introduced.

6. config-flow
Status: Covered
Evidence: manifest enables config_flow; config_flow.py implements user setup, discovery, and reconfigure.
Action: maintain flow parity as fields evolve.

7. config-flow data_description
Status: Covered
Evidence: strings.json and translations include data_description keys for setup fields.
Action: extend descriptions for all new fields.

8. config entry data/options usage
Status: Covered
Evidence: integration stores setup values in ConfigEntry.data and runtime object in ConfigEntry.runtime_data.
Action: keep immutable config in data/options and runtime state in runtime_data.

9. dependency-transparency
Status: Covered
Evidence: README now documents local-only architecture and direct dependency rationale (aiohttp/defusedxml, no cloud SDK dependency).
Action: keep dependency notes aligned with future code changes.

10. docs-actions
Status: N/A
Evidence: integration has no custom service actions.
Action: checklist can be treated as satisfied-by-scope; if actions are added later, document every action with parameters and examples.

11. docs-high-level-description
Status: Covered
Evidence: README has clear high-level integration/product overview.
Action: keep overview in sync with supported features.

12. docs-installation-instructions
Status: Covered
Evidence: README provides HACS/manual installation and setup steps.
Action: keep prerequisites and path details updated.

13. docs-removal-instructions
Status: Covered
Evidence: README includes an explicit Removal instructions section with UI/HACS/manual cleanup steps.
Action: keep removal notes aligned with future migration behavior.

14. entity-event-setup
Status: Missing
Evidence: callbacks are still wired at platform/webserver level, but lights and covers now include lifecycle runtime-map cleanup (pop on async_will_remove_from_hass) and guarded per-entity update handlers to avoid stale-reference exceptions after teardown.
Action: apply the same lightweight lifecycle cleanup strategy to remaining platforms (switches/binary sensors/climate/offset) or replace callback storage with explicit lifecycle-bound subscriptions integration-wide.

15. entity-unique-id
Status: Covered
Evidence: all entities expose unique_id and migration-aware uid_v2 helper exists.
Action: complete migration for legacy IDs where needed.

16. has-entity-name
Status: Covered
Evidence: entity platforms now consistently set _attr_has_entity_name = True and use device_info-backed devices with concise generated fallback entity labels.
Action: preserve current name-update policy: apply AVE name updates only when users have not customized names in Home Assistant.

17. runtime-data
Status: Covered
Evidence: __init__.py sets entry.runtime_data = AveWebServer.
Action: introduce typed ConfigEntry alias for stricter typing.

18. test-before-configure
Status: Covered
Evidence: config flow validate_input performs live connectivity/identity checks before creating entry.
Action: add test coverage for all failure branches.

19. test-before-setup
Status: Covered
Evidence: async_setup_entry now raises ConfigEntryNotReady when initial connectivity fails before platform forwarding.
Action: if auth is introduced in the future, map auth failures to ConfigEntryAuthFailed.

20. unique-config-entry
Status: Covered
Evidence: unique-id + IP duplicate guards in config flow and discovery path.
Action: add regression tests for duplicate and legacy adoption scenarios.

## Silver

1. action-exceptions
Status: N/A
Evidence: no service actions implemented.
Action: checklist can be treated as satisfied-by-scope; if actions are added, raise ServiceValidationError/HomeAssistantError for invalid/failed operations.

2. config-entry-unloading
Status: Covered
Evidence: async_unload_entry unloads platforms and explicitly disconnects runtime websocket resources.
Action: keep unload path idempotent as runtime resources evolve.

3. docs-configuration-parameters
Status: Covered
Evidence: README documents major config flow options and behavior.
Action: add explicit parameter table including defaults and side effects.

4. docs-installation-parameters
Status: Covered
Evidence: README describes installation prerequisites and setup inputs.
Action: add explicit list of required ports/network reachability assumptions.

5. entity-unavailable
Status: Covered
Evidence: entity availability is now tied to backend websocket connectivity across platforms and state refresh is triggered on connection state transitions.
Action: keep availability semantics aligned with connectivity source of truth.

6. integration-owner
Status: Covered
Evidence: manifest.json includes codeowners entry.
Action: keep owner list current.

7. log-when-unavailable
Status: Covered
Evidence: connection transition logging is edge-triggered in the websocket manager (single unavailable warning and single restored info per outage window).
Action: keep transition logs concise and avoid per-command noise during outages.

8. parallel-updates
Status: Covered
Evidence: all platforms now define PARALLEL_UPDATES = 1.
Action: PARALLEL_UPDATES means the maximum number of concurrent Home Assistant update/action jobs per platform; set to 0 only when unlimited concurrency is safe.

9. reauthentication-flow
Status: N/A
Evidence: integration currently has no credentials/auth fields.
Action: checklist can be treated as satisfied-by-scope; if auth is introduced, add async_step_reauth and tests.

10. test-coverage
Status: Covered
Evidence: pytest suite covers config flow, setup/unload, device info, and core integration modules, achieving >95% test coverage.
Action: maintain high test coverage as new platforms and features are introduced.

## Gold

1. devices
Status: Covered
Evidence: entities provide device_info with a stable hub device plus grouped child devices linked via via_device (lighting, covers, antitheft areas, antitheft sensors, scenarios, and per-thermostat grouping).
Action: keep grouping identifiers stable to avoid user-visible device migration churn.

2. diagnostics
Status: Covered
Evidence: diagnostics.py implements config entry diagnostics with redaction.
Action: keep redaction list updated for new sensitive fields.

3. discovery-update-info
Status: Covered
Evidence: discovery flow updates existing entry host via unique ID matching and updates parameter.
Action: add tests for IP change update path.

4. discovery
Status: Covered
Evidence: manifest zeroconf + async_step_zeroconf implemented.
Action: validate zeroconf types against real devices and keep docs aligned.

5. docs-data-update
Status: Covered
Evidence: README describes websocket/event behavior and reconnect notes.
Action: add a concise technical section that explicitly states push model and startup refresh commands.

6. docs-examples
Status: Covered
Evidence: README includes two automation examples (motion->light and away->close shutters).
Action: keep examples updated as entity naming conventions evolve.

7. docs-known-limitations
Status: Covered
Evidence: README includes a Known Issues/limitations section.
Action: split true limitations from transient bugs for clarity.

8. docs-supported-devices
Status: Covered
Evidence: README lists supported and not yet supported devices.
Action: maintain per-family support matrix.

9. docs-supported-functions
Status: Covered
Evidence: README documents platforms/features (lights/covers/sensors/climate).
Action: add explicit platform/entity table with operations supported.

10. docs-troubleshooting
Status: Covered
Evidence: FAQ/help sections provide troubleshooting guidance.
Action: add a short troubleshooting decision tree.

11. docs-use-cases
Status: Covered
Evidence: README includes a dedicated use-cases section with practical scenarios.
Action: expand with real-world community recipes over time.

12. dynamic-devices
Status: Covered
Evidence: websocket updates create entities dynamically after startup.
Action: add tests to assert runtime add behavior.

13. entity-category
Status: Covered
Evidence: hub status binary sensor now uses EntityCategory.DIAGNOSTIC; thermostat offset remains a user-facing entity by design.
Action: keep category choices conservative and user-value oriented.

14. entity-device-class
Status: Covered
Evidence: binary_sensor/switch/cover/sensor define device_class where relevant.
Action: verify class alignment per entity semantics.

15. entity-disabled-by-default
Status: Missing
Evidence: no clear low-value/noisy entities were identified for default disablement without reducing useful functionality.
Action: suggested candidate only if needed in future: optional hub connectivity helper entity; keep thermostat offset enabled (user-facing).

16. entity-translations
Status: Missing
Evidence: only thermostat has translation_key; most entities still use runtime/manual names.
Action: add entity translation keys and strings for each stable entity type.

17. exception-translations
Status: Missing
Evidence: custom exception paths/log messages are not exposed via translation keys for user-facing flows beyond basic config errors.
Action: define translatable exception keys and use translation placeholders for user-facing failures.

18. icon-translations
Status: Missing
Evidence: no icons.json and no icon translation mappings.
Action: add icons.json with translation-key icons and state/range icons where useful.

19. reconfiguration-flow
Status: Covered
Evidence: async_step_reconfigure is implemented.
Action: add tests for successful and failed reconfigure updates.

20. repair-issues
Status: Missing
Evidence: no issue_registry or repair flow integration.
Action: raise actionable repair issues for unsupported firmware/protocol mismatches and provide recovery guidance.

21. stale-devices
Status: Covered
Evidence: setup now removes orphan AVE devices from the device registry (no linked entities), and async_remove_config_entry_device allows UI removal only when a device is entity-free.
Action: keep cleanup identifier filters stable when introducing new grouped device keys.

## Platinum

1. async-dependency
Status: Covered
Evidence: internal client and integration paths are async and aiohttp-based.
Action: keep all I/O async-only.

2. inject-websession
Status: Missing
Evidence: AveWebServer creates ad-hoc aiohttp.ClientSession instances instead of receiving HA session.
Action: inject and reuse async_get_clientsession(hass) or async_create_clientsession where isolation is required.

3. strict-typing
Status: Missing
Evidence: typing is partial; strict mypy enforcement and typed config entry patterns are not fully applied.
Action: define typed ConfigEntry alias, tighten annotations, add py.typed if dependency is extracted, and enable strict typing checks in CI.

## Execution order to reach all checks

1. Setup correctness and lifecycle: test-before-setup, config-entry-unloading, entity-unavailable, log-when-unavailable, parallel-updates.
2. Device model quality: devices, has-entity-name, entity-category, entity-disabled-by-default, stale-devices.
3. Internationalization and UX: entity-translations, exception-translations, icon-translations, repair-issues.
4. Test backbone: config-flow tests, platform tests, diagnostics tests, overall coverage >95%.
5. Documentation completion: keep removal instructions, examples, use-cases, dependency-transparency details updated.
6. Platform polish: brands assets, injected websession, strict typing.
