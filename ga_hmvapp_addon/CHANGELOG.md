# Changelog

This is the addon-store sync file for `ga_hmvapp_addon`. Each entry
mirrors a release from the (private) source repo
[greenautarky/ga_hmvapp_addon](https://github.com/greenautarky/ga_hmvapp_addon).

## 1.1.713 — Initial publish to vibe_addons (2026-06-01)

- First public store entry for the GA HMVapp Addon (heating-management
  model).
- Image is pulled from `ghcr.io/greenautarky/ga_hmvapp_addon-{arch}`
  (private GHCR package — requires the shared `read:packages` credential
  in Supervisor's `/docker/registries`, delivered by ga-fleet-manager).
- Three architectures published: aarch64, amd64, armv7.
- Replaces the old private-repo + PAT-in-URL store registration that was
  shipped via ga-flasher-py `install-addons.sh`. The legacy slug was
  `48a36628_ga_hmvapp_addon` (or `95cc8708_*`); the new slug is
  `99f1cad4_ga_hmvapp_addon` (constant hash of the public vibe_addons
  store URL). Existing devices are migrated to the new slug by
  `ga_manager` 0.25.0's `_step_migrate_legacy_addons`.
- Previously took 30–45 min to install on armv7 because the source
  Dockerfile did `pip install xgboost` from source. The pre-built image
  installs in seconds.
