# Changelog  

## 1.3.6 — rebuilt operating-system layer (2026-09-30)
### Changed (GreenAutarky)
- **The image is now rebuilt instead of copied.** Up to 1.3.5, CI copied the vendor
  `-{arch}:1.3.4` image byte-for-byte. From 1.3.6, CI (`mirror-flasher-image.yaml`)
  builds `ga_dongle_flasher-{arch}` on top of that vendor image and refreshes only the
  operating-system layer (`.github/flasher-image/Dockerfile`):
  - all Alpine 3.21 packages upgraded to the current 3.21 releases;
  - `nodejs` / `npm` moved from the vendor's exact pin to the current Alpine 3.21
    patch release (Node 22.22.2 → 22.23.x, same major and ABI);
  - `tempio` replaced by upstream release 2026.07.0 (sha256-verified).
  The vendor application in `/workspace` is unchanged, as are the add-on options,
  mappings and privileges.
- CI now builds and checks the image on every pull request and pushes only from
  `main`; it refuses to overwrite a version tag that already exists.

## 1.3.5 — GA security config (2026-08-19)
### Changed (GreenAutarky)
- **Image moved to `ghcr.io/greenautarky/ga_dongle_flasher-{arch}`, version bumped
  1.3.4 → 1.3.5.** The version bump is the delivery vehicle: the Supervisor uses
  the addon version as the image tag, so a config change (below) only reaches
  installed addons via a version bump — and that needs an image at the new tag.
  The vendor tags stop at 1.3.4, so CI (`mirror-flasher-image.yaml`) copies the
  vendor `-{arch}:1.3.4` image **byte-for-byte** to the GA registry as
  `ga_dongle_flasher-{arch}:1.3.5` (registry-to-registry, no rebuild — identical
  layers). Lockstep bump in `ha-operating-system/addon-images.json`.
- **Removed `host_network: true`.** The addon ran a persistent HTTP + WebSocket
  server (`ingress_port` 8324) that, under `host_network`, bound to `0.0.0.0` on
  every host interface — reachable on the LAN and the mesh, guarded only by an
  HMAC secret baked into the public image (its WebSocket accepted unauthenticated
  connections). That is the CVE-2026-34205 pattern. Without `host_network` the
  server binds inside the addon's bridge network namespace and is reachable
  **only** through HA-authenticated `ingress` — the direct LAN/mesh path is gone.
  Flashing is unaffected: hardware access is via `uart`/`udev`/`gpio` (not the
  network), and GA's `zigbee_coordinator` drives the flasher over `docker exec`,
  never the HTTP API. This mirrors the official HA `silabs_flasher` addon, which
  runs no host-network server at all. See ga-ihost-docs ADR-0016 / Odoo #700.
  Least-privilege (dropping `full_access` / unneeded caps) is a separate,
  device-flash-tested step: the GPIO bootloader does `mount -o remount,rw /sys`,
  which needs `SYS_ADMIN`, so the caps cannot be stripped blindly.

## 1.3.4
### Added
- Added support for **SONOFF Dongle-MZG23**.

## 1.3.3
### Fixed
- Force Dongle-E and Dongle-LMG21 flashed with Router firmware into pairing mode when it is powered on.
- Fixed an issue where certain dongles identified as running unknown firmware could not have a firmware selected for flashing.

## 1.3.2
### Fixed
- Fixed an issue where certain dongles could not be properly recognized during scanning.

## 1.3.1
### Added
- Force Dongle-PMG24 flashed with Router firmware into pairing mode when it is powered on.

## 1.3.0
### Added
- Added support for **SONOFF Dongle-PZG23**.

## 1.2.3
### Fixed
- Fixed the issue where firmware information for certain dongles could not be properly recognized.

## 1.2.2
### Fixed
- Fixed the issue where firmware version could not be sorted correctly.

## 1.2.1
### Added
- Add support for **SONOFF Dongle-LMG21**.

## 1.2.0
### Added
- Added support for **SONOFF Dongle-M** and **Dongle-PMG24**.

### Changed
- Added a progress bar display during the **Step 1: Connect** process.

## 1.1.1
### Fixed
- Fixed add-on malfunction caused by accessing Home Assistant through the HTTPS protocol.

## 1.1.0
### Added
- Supports more architectures (armv7, aarch64, amd64).
- Supports flashing SONOFF ZBDongle series (ZBDongle-E, ZBDongle-P). *Note：The ZBDongle-E for the CH9102 chip is currently not supported.
- Supports flashing OpenThread, MultiPAN, and custom uploaded firmware.