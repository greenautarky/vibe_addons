#!/usr/bin/env python3
"""Fixtures for scripts/resolve_addon_base.py — both directions, every run.

A gate ships with its fixtures and CI runs them. A red proof pasted into a
review is evidence once, about one version, and nothing re-checks it when the
resolver is edited a month later.

Both sets are mandatory:

  MUST-FAIL  inputs the resolver has to reject. The important ones are the
             near-misses: a build.yaml that lists other architectures but not
             this one, and a build.yaml that cannot be parsed. Both are exactly
             the shapes where "fall back to the default" feels helpful and is
             wrong — a silent substitution turns a config mistake into an image
             nobody declared.

  MUST-PASS  inputs it must NOT reject, including the legacy no-build.yaml case.
             This half is not padding: a resolver that refuses everything gets
             worked around, which is a slower way of having no resolver. Every
             false positive we ever fix lands here so it cannot come back.

This suite imports the LIVE script by path — never a copy, never a
re-declaration of its logic — and FAILS rather than skips if it cannot find it.
A self-test that carries its own copy of the thing under test stays green while
the real one rots, which is the very failure it exists to catch.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIVE = ROOT / "scripts" / "resolve_addon_base.py"

if not LIVE.is_file():
    print(f"::error::cannot find the live resolver at {LIVE} — refusing to "
          f"report a result. 'Could not check' must never read as 'checked'.")
    raise SystemExit(2)

spec = importlib.util.spec_from_file_location("resolve_addon_base", LIVE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

OURS = "ghcr.io/greenautarky/ga-addon-base-armv7:3.24"
LEGACY_TAG = "3.21"

checks = 0
failures = 0


def _write(body: str | None) -> str:
    d = tempfile.mkdtemp()
    if body is not None:
        (pathlib.Path(d) / "build.yaml").write_text(body, encoding="utf-8")
    return d


def must_pass(label: str, body: str | None, arch: str, expect_image: str,
              expect_source: str) -> None:
    global checks, failures
    checks += 1
    try:
        image, source = mod.resolve(_write(body), arch, LEGACY_TAG)
    except SystemExit as e:
        failures += 1
        print(f"  ✗ MUST-PASS {label}: rejected (exit {e.code})")
        return
    if image != expect_image or source != expect_source:
        failures += 1
        print(f"  ✗ MUST-PASS {label}: got ({image}, {source}), "
              f"expected ({expect_image}, {expect_source})")
    else:
        print(f"  ✓ MUST-PASS {label}")


def must_fail(label: str, body: str | None, arch: str) -> None:
    global checks, failures
    checks += 1
    try:
        image, source = mod.resolve(_write(body), arch, LEGACY_TAG)
    except SystemExit:
        print(f"  ✓ MUST-FAIL {label}")
        return
    failures += 1
    print(f"  ✗ MUST-FAIL {label}: accepted and returned ({image}, {source}) — "
          f"this is the silent-substitution defect the resolver exists to stop")


print(f"live resolver: {LIVE}")
print()

# ── MUST-PASS ───────────────────────────────────────────────────────────────
must_pass(
    "build.yaml wins over the legacy construction",
    f"build_from:\n  aarch64: ghcr.io/hassio-addons/base:21.0.2\n"
    f"  amd64: ghcr.io/hassio-addons/base:21.0.2\n  armv7: {OURS}\n",
    "armv7", OURS, "build.yaml",
)
must_pass(
    "a non-migrated arch still resolves from build.yaml",
    f"build_from:\n  aarch64: ghcr.io/hassio-addons/base:21.0.2\n  armv7: {OURS}\n",
    "aarch64", "ghcr.io/hassio-addons/base:21.0.2", "build.yaml",
)
must_pass(
    "no build.yaml falls back to legacy (and warns)",
    None, "armv7", f"ghcr.io/home-assistant/armv7-base:{LEGACY_TAG}", "legacy",
)
must_pass(
    "extra keys alongside build_from are tolerated",
    f"build_from:\n  armv7: {OURS}\nargs:\n  FOO: bar\ncodenotary:\n"
    f"  signer: notary@greenautarky.com\n",
    "armv7", OURS, "build.yaml",
)

# ── MUST-FAIL ───────────────────────────────────────────────────────────────
print()
must_fail(
    "build.yaml exists but omits this arch",
    "build_from:\n  aarch64: ghcr.io/hassio-addons/base:21.0.2\n"
    "  amd64: ghcr.io/hassio-addons/base:21.0.2\n",
    "armv7",
)
must_fail(
    "build.yaml is not parseable YAML",
    "build_from:\n  armv7: [unclosed\n", "armv7",
)
must_fail(
    "build.yaml has no build_from mapping at all",
    "args:\n  FOO: bar\n", "armv7",
)
must_fail(
    "build_from is present but empty",
    "build_from:\n", "armv7",
)
must_fail(
    "the arch key exists but its value is blank",
    "build_from:\n  armv7: \"\"\n", "armv7",
)
must_fail(
    "build.yaml parses to a list, not a mapping",
    "- build_from\n- armv7\n", "armv7",
)

print()
# A suite that ran zero checks is a failure, not a pass.
if checks < 10:
    print(f"::error::only {checks} checks ran — the suite did not execute as written")
    raise SystemExit(2)
print(f"{checks} checks, {failures} failed")
raise SystemExit(1 if failures else 0)
