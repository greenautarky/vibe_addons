# Changelog

This is the addon-store sync file for `ga_manager`. Each entry mirrors a
release from the [source repo](https://github.com/greenautarky/ga_manager)
— see that repo's [CHANGELOG](https://github.com/greenautarky/ga_manager/blob/main/CHANGELOG.md)
for full rationale, test details, and the "why".

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
