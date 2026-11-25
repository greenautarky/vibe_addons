#!/usr/bin/env python3
"""Fixtures for scripts/assert_base_matches.py — both directions, every run.

A gate ships with its fixtures and CI runs them. A red proof pasted into a
review is evidence once, about one version, and nothing re-checks it when the
assertion is edited a month later.

  MUST-FAIL  pairs the assertion has to reject. The headline one is the real
             2026-08-20 influxDBv1 case, byte-for-byte: `build.yaml` declared
             `ga-addon-debian-base-armv7:trixie` (Debian 13.6) and the workflow
             built on `hassio-addons/debian-base/armv7:8.1.4` (Debian 13.1).
             Also here: every "could not determine one side" shape, because
             "could not check" must never render as "checked and fine".

  MUST-PASS  pairs it must NOT reject. Not padding: an assertion that flags
             correct builds is overridden by reflex, which is a slower way of
             having no assertion at all. Every false positive we ever fix lands
             here so it cannot come back.

WHY THE FILE CONTENTS BELOW ARE REAL
------------------------------------
They were read out of the actual images on 2026-08-20 with
`read_image_files(...)` from the live script, not invented. That matters for one
specific reason, and it is the whole design argument:

    ghcr.io/greenautarky/ga-addon-debian-base-armv7:trixie   ->  VERSION_ID="13", trixie
    ghcr.io/hassio-addons/debian-base/armv7:8.1.4            ->  VERSION_ID="13", trixie

The two bases in the real incident agree on `/etc/os-release` — same major, same
codename. An assertion built on `os-release` alone would have been GREEN on the
day it was needed. Only `/etc/debian_version` (13.6 vs 13.1) tells them apart,
which is why the script prefers that file for Debian and why the point-release
comparison is fatal by default.

This suite imports the LIVE script by path — never a copy, never a
re-declaration of its logic — and FAILS rather than skips if it cannot find it.
It needs no docker: the docker half reads bytes, the pure half decides, and it
is the deciding that has to be right.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIVE = ROOT / "scripts" / "assert_base_matches.py"

if not LIVE.is_file():
    print(f"::error::cannot find the live assertion at {LIVE} — refusing to "
          f"report a result. 'Could not check' must never read as 'checked'.")
    raise SystemExit(2)

spec = importlib.util.spec_from_file_location("assert_base_matches", LIVE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# ── real image contents, read on 2026-08-20 ─────────────────────────────────
DEB_13_6 = {  # ghcr.io/greenautarky/ga-addon-debian-base-armv7:trixie  (DECLARED)
    "/etc/os-release": (
        'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n'
        'NAME="Debian GNU/Linux"\nVERSION_ID="13"\nVERSION="13 (trixie)"\n'
        "VERSION_CODENAME=trixie\nDEBIAN_VERSION_FULL=13.6\nID=debian\n"
    ),
    "/etc/debian_version": "13.6\n",
    "/etc/alpine-release": None,
}
DEB_13_1 = {  # ghcr.io/hassio-addons/debian-base/armv7:8.1.4          (BUILT ON)
    "/etc/os-release": (
        'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n'
        'NAME="Debian GNU/Linux"\nVERSION_ID="13"\nVERSION="13 (trixie)"\n'
        "VERSION_CODENAME=trixie\nDEBIAN_VERSION_FULL=13.1\nID=debian\n"
    ),
    "/etc/debian_version": "13.1\n",
    "/etc/alpine-release": None,
}
DEB_12_10 = {  # ghcr.io/hassio-addons/debian-base/armv7:7.8.1
    "/etc/os-release": (
        'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
        'NAME="Debian GNU/Linux"\nVERSION_ID="12"\nVERSION="12 (bookworm)"\n'
        "VERSION_CODENAME=bookworm\nID=debian\n"
    ),
    "/etc/debian_version": "12.10\n",
    "/etc/alpine-release": None,
}
ALP_3_24_1 = {  # ghcr.io/greenautarky/ga-addon-base-armv7:3.24
    "/etc/os-release": ('NAME="Alpine Linux"\nID=alpine\nVERSION_ID=3.24.1\n'
                        'PRETTY_NAME="Alpine Linux v3.24"\n'),
    "/etc/debian_version": None,
    "/etc/alpine-release": "3.24.1\n",
}
ALP_3_22_2 = {  # ghcr.io/hassio-addons/base:18.2.1
    "/etc/os-release": ('NAME="Alpine Linux"\nID=alpine\nVERSION_ID=3.22.2\n'
                        'PRETTY_NAME="Alpine Linux v3.22"\n'),
    "/etc/debian_version": None,
    "/etc/alpine-release": "3.22.2\n",
}
# synthetic, but legitimate shapes the script must survive
DEB_SID = {"/etc/os-release": 'ID=debian\nVERSION_ID="13"\n',
           "/etc/debian_version": "trixie/sid\n", "/etc/alpine-release": None}
UBUNTU_24 = {"/etc/os-release": 'ID=ubuntu\nVERSION_ID="24.04"\n',
             "/etc/debian_version": None, "/etc/alpine-release": None}
NOTHING = {"/etc/os-release": None, "/etc/debian_version": None,
           "/etc/alpine-release": None}
GARBAGE = {"/etc/os-release": "\n\n# nothing useful here\n",
           "/etc/debian_version": None, "/etc/alpine-release": None}

checks = 0
failures = 0


def _ok(label: str) -> None:
    print(f"  ✓ {label}")


def _bad(label: str, detail: str) -> None:
    global failures
    failures += 1
    print(f"  ✗ {label}: {detail}")


def must_pass(label: str, declared: dict, built: dict,
              allow_point_drift: bool = False) -> None:
    global checks
    checks += 1
    v = mod.compare_identity(mod.parse_identity(declared),
                             mod.parse_identity(built), allow_point_drift)
    if v.ok:
        _ok(f"MUST-PASS {label}")
    else:
        _bad(f"MUST-PASS {label}", f"rejected [{v.code}] {v.message}")


def must_fail(label: str, declared: dict, built: dict, expect_code: str,
              allow_point_drift: bool = False) -> None:
    """Reject, AND reject for the stated reason.

    N30: if a different check catches the mutation, the check under test is
    still unproven. Same logic applies to a fixture — 'it went red' is not the
    assertion, 'it went red for THIS reason' is.
    """
    global checks
    checks += 1
    v = mod.compare_identity(mod.parse_identity(declared),
                             mod.parse_identity(built), allow_point_drift)
    if v.ok:
        _bad(f"MUST-FAIL {label}",
             f"ACCEPTED ({v.code}) — this is the 2026-08-20 defect class "
             f"passing through the assertion built to stop it")
    elif v.code != expect_code:
        _bad(f"MUST-FAIL {label}",
             f"rejected for the wrong reason: got [{v.code}], expected "
             f"[{expect_code}]")
    else:
        _ok(f"MUST-FAIL {label} [{v.code}]")


def expect_identity(label: str, files: dict, distro: str, version: str) -> None:
    global checks
    checks += 1
    ident = mod.parse_identity(files)
    if ident is None:
        _bad(f"IDENTITY {label}", "no identity derived at all")
    elif ident.distro != distro or ident.version != version:
        _bad(f"IDENTITY {label}",
             f"got {ident.distro} {ident.version}, expected {distro} {version}")
    else:
        _ok(f"IDENTITY {label} -> {ident.distro} {ident.version} "
            f"(via {ident.evidence})")


def lineage_pass(label: str, base, built) -> None:
    global checks
    checks += 1
    v = mod.compare_lineage(base, built)
    _ok(f"MUST-PASS lineage {label}") if v.ok else _bad(
        f"MUST-PASS lineage {label}", f"[{v.code}] {v.message}")


def lineage_fail(label: str, base, built, expect_code: str) -> None:
    global checks
    checks += 1
    v = mod.compare_lineage(base, built)
    if v.ok:
        _bad(f"MUST-FAIL lineage {label}", "accepted")
    elif v.code != expect_code:
        _bad(f"MUST-FAIL lineage {label}",
             f"wrong reason: [{v.code}] != [{expect_code}]")
    else:
        _ok(f"MUST-FAIL lineage {label} [{v.code}]")


print(f"live assertion: {LIVE}")
print()

# ── the discriminator ───────────────────────────────────────────────────────
# If this block regresses, the headline MUST-FAIL below silently becomes
# unfindable: both images say VERSION_ID="13" and codename trixie.
print("discriminator — Debian point release must come from /etc/debian_version")
expect_identity("declared base (ga-addon-debian-base-armv7:trixie)",
                DEB_13_6, "debian", "13.6")
expect_identity("built-on base (hassio-addons/debian-base/armv7:8.1.4)",
                DEB_13_1, "debian", "13.1")
expect_identity("alpine reads /etc/alpine-release", ALP_3_24_1, "alpine", "3.24.1")
expect_identity("debian testing falls back to os-release", DEB_SID, "debian", "13")
expect_identity("os-release-only distro still resolves", UBUNTU_24, "ubuntu", "24.04")

# ── MUST-FAIL ───────────────────────────────────────────────────────────────
print()
print("must-fail")
must_fail(
    "THE 2026-08-20 CASE: declared Debian 13.6 (trixie base), built on 13.1 "
    "— same major, same codename, same VERSION_ID",
    DEB_13_6, DEB_13_1, "point",
)
must_fail("declared trixie 13.6, built on bookworm 12.10",
          DEB_13_6, DEB_12_10, "major")
must_fail("declared Alpine 3.24.1, built on Alpine 3.22.2",
          ALP_3_24_1, ALP_3_22_2, "major")
must_fail("declared Debian, built on Alpine", DEB_13_6, ALP_3_24_1, "distro")
must_fail("declared Alpine, built on Debian", ALP_3_24_1, DEB_13_6, "distro")
must_fail("the BUILT image reports no identity", DEB_13_6, NOTHING, "undetermined")
must_fail("the DECLARED base reports no identity", NOTHING, DEB_13_6, "undetermined")
must_fail("neither side reports an identity", NOTHING, NOTHING, "undetermined")
must_fail("an os-release with no usable keys is not an identity",
          DEB_13_6, GARBAGE, "undetermined")
must_fail("--allow-point-drift does NOT excuse a major mismatch",
          DEB_13_6, DEB_12_10, "major", allow_point_drift=True)
must_fail("--allow-point-drift does NOT excuse an undetermined side",
          DEB_13_6, NOTHING, "undetermined", allow_point_drift=True)

# ── MUST-PASS ───────────────────────────────────────────────────────────────
print()
print("must-pass")
must_pass("an image built from the declared trixie base", DEB_13_6, dict(DEB_13_6))
must_pass("an image built from the declared Alpine 3.24 base",
          ALP_3_24_1, dict(ALP_3_24_1))
must_pass("the 12.10 base matches itself (older base, correctly declared)",
          DEB_12_10, dict(DEB_12_10))
must_pass("point drift, explicitly and deliberately allowed",
          DEB_13_6, DEB_13_1, allow_point_drift=True)
must_pass("a debian testing base matches a 13 image via os-release",
          DEB_SID, {"/etc/os-release": 'ID=debian\nVERSION_ID="13"\n',
                    "/etc/debian_version": "trixie/sid\n",
                    "/etc/alpine-release": None})
must_pass("os-release-only distro matches itself", UBUNTU_24, dict(UBUNTU_24))

# ── lineage (opt-in check) ──────────────────────────────────────────────────
print()
print("lineage")
B = ["sha256:aaa", "sha256:bbb"]
lineage_pass("built = base + the add-on's own layers", B, B + ["sha256:ccc"])
lineage_pass("built = base exactly (no extra layer)", B, list(B))
lineage_fail("built diverges from the base at layer 1", B,
             ["sha256:aaa", "sha256:zzz", "sha256:ccc"], "lineage")
lineage_fail("built has fewer layers than the base", B, ["sha256:aaa"], "lineage")
# Added after a mutation counter-check on 2026-08-20: rewriting the prefix test
# as a SET comparison passed every other fixture here. Derivation is ordered —
# an image that merely CONTAINS the base's layers somewhere is not built on it.
lineage_fail("built contains the base's layers but not as a prefix", B,
             ["sha256:bbb", "sha256:aaa", "sha256:ccc"], "lineage")
lineage_fail("base layers unreadable", None, B, "undetermined")
lineage_fail("built layers unreadable", B, None, "undetermined")

# ── the expectation must come from build.yaml, and nowhere else ─────────────
print()
print("expectation source")
checks += 1
_saved = mod.LIVE_RESOLVER
try:
    mod.LIVE_RESOLVER = pathlib.Path("/nonexistent/resolve_addon_base.py")
    try:
        mod.load_resolver()
        _bad("no live resolver -> must refuse",
             "load_resolver() returned instead of exiting; the script would "
             "have to construct the base name itself, which IS the defect")
    except SystemExit as e:
        if e.code == 2:
            _ok("no live resolver -> refuses with exit 2 (could not check)")
        else:
            _bad("no live resolver -> must refuse", f"exited {e.code}, wanted 2")
finally:
    mod.LIVE_RESOLVER = _saved

checks += 1
if mod.LIVE_RESOLVER.is_file() and mod.LIVE_RESOLVER.name == "resolve_addon_base.py":
    _ok("the expectation is resolved through the live scripts/resolve_addon_base.py")
else:
    _bad("expectation source", f"unexpected resolver path {mod.LIVE_RESOLVER}")

print()
# A suite that ran zero checks is a failure, not a pass.
if checks < 29:
    print(f"::error::only {checks} checks ran — the suite did not execute as "
          f"written; a run over nothing is a failure, not a pass")
    raise SystemExit(2)
print(f"{checks} checks, {failures} failed")
raise SystemExit(1 if failures else 0)
