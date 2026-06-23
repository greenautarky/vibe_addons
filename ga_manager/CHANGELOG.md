# Changelog

This is the addon-store sync file for `ga_manager`. Each entry mirrors a
release from the [source repo](https://github.com/greenautarky/ga_manager)
— see that repo's [CHANGELOG](https://github.com/greenautarky/ga_manager/blob/main/CHANGELOG.md)
for full rationale, test details, and the "why".

## 0.49.4

- **On-device addon self-healing** — health-engine restarts stopped
  load-bearing addons every tick, with per-slug TTL suppression locks
  (Zigbee FW update keeps z2m down) + crash-loop backoff. Local-first.

## 0.49.3

- **Revert non-functional `ga.core_auto_update_disabled`** (added 0.49.2) —
  /core/info has no auto_update field; the check returned `unknown`
  everywhere. Core is not auto-pulled by Supervisor.
- **Fix `ga.image_origin`** to accept v1.2-clean upstream Core
  (`ghcr.io/home-assistant/tinker-homeassistant`) — was flagging every
  v1.2-clean device as crit.

## 0.49.2

- **New health check `ga.core_auto_update_disabled`** — closes a
  2026-06-23 audit gap. The existing `ga.auto_update_disabled` only
  checked Supervisor; Core has an independent auto_update knob.

## 0.26.4

- **Step 1 per-addon try/except** — one addon's install failure no
  longer aborts the rest of the loop AND the rest of converge. Found
  on the bench reflash 2026-06-01 when ga_default_addon's install
  threw 400 (no cred yet) and killed steps 2-11 entirely. See source
  CHANGELOG for detail.

## 0.26.3

- **MANAGED_ADDON_SLUGS missing 4 addons** — fresh-flash converge only
  iterated `ga_mosquitto`, `ga_zigbee2mqtt`, `ga_ihosthardwarecontrol`,
  `sonoff_dongle_flasher_for_ihost`. **Added:** `ga_tailscale`,
  `ga_influxdbv1`, `ga_default_addon`, `ga_hmvapp_addon` — so the
  private addons get installed automatically on a fresh device. See
  source CHANGELOG.

## 0.26.2

- **Rotation-blind bug fix** — `docker-registry-ensure` now detects PAT
  rotation via a persistent sha-marker (`/share/ga/.ghcr-creds.applied-sha`),
  not by username-comparison. Before this, rotating the GHCR token
  silently left Supervisor on the old (often revoked) token. See source
  CHANGELOG for detail.

## 0.26.1

- **HTTP routes for `ghcr-creds-write` + `docker-registry-ensure`** —
  0.26.0 / 0.25.0 shipped the workers but no `POST /jobs/<action>`
  endpoint to invoke them. Found during the first canary push to
  KIB-SON-0 (`fleet-manager` got 405). 0.26.1 wires them up.
- **Security:** sanitized 422 validation errors so a malformed
  `ghcr-creds-write` payload can't echo the password back to the
  caller. See source CHANGELOG for detail.

## 0.26.0

- **`ghcr-creds-write`** worker — writes `/share/ga/ghcr-creds.json` (mode 0600,
  atomic, idempotent) so ga-fleet-manager can deliver / rotate the shared
  `read:packages` token for private GHCR addon images. Companion to the
  `docker-registry-ensure` worker shipped in 0.25.0. Token never logged.
  See source CHANGELOG for detail.

## 0.25.0

- **Fresh-flash provisioning gaps** found on the A3 bench: z2m `onboarding:false`
  (Zigbee forms), wizard trigger `version:2` (matches component `STORAGE_VERSION`),
  placement-gated integration enable-list (writes `<domain>:` to
  configuration.yaml so config_flow custom_components actually load).
- **Generalized for ga_frontend_bundle**: `_step_place_component` loops all
  staged components; `provision_verify` gains live checks (`z2m_formed`,
  `integrations_loaded`); Core-restart `verify-on-raise` (tolerates the
  cosmetic mid-restart conn drop).
- **D / D2**: `docker-registry-ensure` worker + converge step 0.5 (push GHCR
  creds into Supervisor's `/docker/registries`); `_step_migrate_legacy_addons`
  (one-time migration from `48a36628_*`/`95cc8708_*` slugs to vibe_addons
  prefixed slugs, drops the PAT-in-URL repo). See source CHANGELOG for detail.

## 0.24.0

- On-device **provisioning self-check** (converge step 11): the device verifies
  its own provisioning state after converge (the equivalent of ga-flasher-py
  stage 81) instead of the flasher SSHing in to assert it. Checks each converge
  step's persisted effect — addons, addon flags, z2m serial+channel, DNS, MQTT
  entry, custom_component, Core un-forked, wizard armed. Best-effort: a FAIL is
  logged + recorded but does not undo convergence. +16 tests. See source
  CHANGELOG for detail.

## 0.23.2

- Converge sets **Zigbee2MQTT channel 15** (`advanced.channel`) at fresh
  network formation — completes stage 64. Gated to first provisioning only
  (serial config newly written ⇒ no network yet), so the channel applies at
  formation with zero migration. Verified on a canary that the ember adapter
  *does* migrate a formed network in-place on a channel change and SONOFF
  devices follow (15→20→25→15, 4/4 online) — but we deliberately do **not**
  rely on that for provisioned customer devices. +2 tests. See the source
  CHANGELOG for detail.

## 0.23.1

- Fresh-boot fixes for the 0.23.0 converge work (found by flashing a truly
  fresh device): write to **`/homeassistant`** (Core's config dir) not
  `/config` — fixes the custom_component, wizard trigger AND MQTT entry
  placement; **readiness gating** (wait for addons started + Mosquitto's mqtt
  service) so step 8 doesn't no-op on first boot; **one gated Core restart**
  so the `.storage` writes actually load; `device_type` falls back to `ihost`.
  +7 tests, full suite 325/325. See the source CHANGELOG for detail.

## 0.23.0

- Converge closes fresh-flash provisioning gaps (= ga-flasher-py stages
  64/65/69): enforces load-bearing **addon flags** (watchdog/auto_update/
  boot), sets **Zigbee2MQTT serial** config (hardware-keyed on device_type),
  writes the **HA-Core MQTT integration entry**. New single-source
  `addon_expectations` (converge applies / healthcheck verifies) + safe
  `addon_merge_options` helper. Full suite 318/318 PASS. See the source
  CHANGELOG for rationale + known fresh-boot readiness/timing follow-ups.

## 0.22.3

- Zigbee converge step 5 is now tiered (Tier 0 reads firmware from z2m's
  MQTT `bridge/info` → **zero Zigbee outage** when chip already at target;
  Tier 1 falls back to addon-probe with ~30 s outage; Tier 2 actual flash
  only when needed). Was: unconditional ~3 min Zigbee outage per converge.
- 9 new tests + 3 updated. Full suite 318/318 PASS.

## 0.22.2

- New `ga.image_origin` health check — WARN if `homeassistant` container
  is pulling from upstream `ghcr.io/home-assistant/...` instead of the
  GA `ghcr.io/greenautarky/...` registry.

## 0.22.1

- `SupervisorAPI` per-call timeout — long ops (addon update with build,
  core update with image pull, backup) opt out of the global 30 s
  budget. Fixes false-failed audits during legitimate long ops.
- 18 new tests.

## 0.22.0

- Bake ga_manager + vibe_addons registration into the OS image
  (first-boot offline). T4 reconciliation.
