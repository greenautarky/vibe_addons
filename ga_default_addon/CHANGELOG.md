# Changelog

This is the addon-store sync file for `ga_default_addon`. Each entry
mirrors a release from the (private) source repo
[greenautarky/ga_default_addon](https://github.com/greenautarky/ga_default_addon).

## 1.4.0 — Cloud push becomes an explicit, per-device opt-in (2026-08-24)

- New add-on option `legacy_cloud_push` (bool, **default `false`**), plus the
  matching `schema` key. This is the reason for the store bump: an option only
  reaches a device through this entry.
- The add-on pushes aggregated data to the central cloud database **only** when
  `legacy_cloud_push` is `true` **and** all four credential options
  (`DB_HOST`, `DB_NAME`, `DB_USERNAME`, `DB_PASSWORD`) are set. Since 1.3.2 the
  credentials were delivered as options rather than baked into the image, which
  made "does this device push?" depend on configuration nobody had decided;
  1.4.0 makes it a decision.
- The path is **transitional** — it serves devices that have not yet migrated
  off the old UI — and is scheduled for removal. Current systems need no action:
  the default is off.
- The add-on now logs exactly one line per run stating which of three states it
  is in (disabled by policy / enabled on the legacy path / turned on but
  misconfigured), so a silent non-push is no longer possible.

Nothing else in this entry changes: no option value, port, map, arch or image
reference is touched.

## 1.1.21 — Initial publish to vibe_addons (2026-06-01)

- First public store entry for the GA Default Addon (VOS functions).
- Image is pulled from `ghcr.io/greenautarky/ga_default_addon-{arch}`
  (private GHCR package — requires the shared `read:packages` credential
  in Supervisor's `/docker/registries`, delivered by ga-fleet-manager).
- Three architectures published: aarch64, amd64, armv7.
- Replaces the old private-repo + PAT-in-URL store registration that was
  shipped via ga-flasher-py `install-addons.sh`. The legacy slug was
  `48a36628_ga_default_addon` (or `95cc8708_*`); the new slug is
  `99f1cad4_ga_default_addon` (constant hash of the public vibe_addons
  store URL). Existing devices are migrated to the new slug by
  `ga_manager` 0.25.0's `_step_migrate_legacy_addons`.
