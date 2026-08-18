#!/usr/bin/env python3
"""Fixtures for the store-sync gate — both sets are mandatory.

* ``must_fail/`` — source/store pairs the gate MUST reject
* ``must_pass/`` — pairs it must NOT reject. This set is not padding: a gate
  that flags legitimate states gets overridden by reflex, which is a slower
  way of having no gate. Every false positive we ever fix belongs in here so
  it cannot come back.

The gate is imported from its LIVE path. A fixture suite that restates the
comparison rules tests a copy, stays green while the real gate rots, and is
the exact failure this gate exists to prevent. If the gate cannot be found,
this FAILS — it never skips.

    python3 tests/store_sync_gate/run_fixtures.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
CASES = pathlib.Path(__file__).resolve().parent
IMAGE = "ghcr.io/greenautarky/ga_influxdbv1-{arch}"


def _load(name: str):
    path = SCRIPTS / f"{name}.py"
    if not path.is_file():
        raise SystemExit(f"FATAL: {path} not found — refusing to skip a gate self-test")
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cases(kind: str):
    root = CASES / kind
    if not root.is_dir():
        raise SystemExit(f"FATAL: fixture set {kind} missing")
    for case in sorted(root.iterdir()):
        if case.is_dir():
            yield (case.name,
                   (case / "source.yaml").read_text(),
                   (case / "store.yaml").read_text())


def main() -> int:
    renderer = _load("render_store_config")
    gate = _load("verify_store_sync")
    failures: list[str] = []
    checked = 0

    for kind in ("must_fail", "must_pass"):
        for name, source_text, store_text in _cases(kind):
            checked += 1
            rendered = yaml.safe_load(renderer.render(source_text, IMAGE)) or {}
            store = yaml.safe_load(store_text) or {}
            problems, _warnings = gate.compare(rendered, store)
            if kind == "must_fail" and not problems:
                failures.append(f"must_fail/{name}: gate did NOT flag it")
            elif kind == "must_fail":
                print(f"  must_fail/{name}: flagged — {problems[0]}")
            elif problems:
                failures.append(f"must_pass/{name}: false positive — {problems}")
            else:
                print(f"  must_pass/{name}: clean")

    # The renderer must be idempotent, or the sync would churn a commit on
    # every run and the verifier would flag its own output.
    checked += 1
    sample = (CASES / "must_pass" / "source_without_image" / "source.yaml").read_text()
    once = renderer.render(sample, IMAGE)
    twice = renderer.render(once, IMAGE)
    if once != twice:
        failures.append("renderer is NOT idempotent — render(render(x)) != render(x)")
    else:
        print("  idempotence: render(render(x)) == render(x)")

    if checked == 0:
        print("FATAL: zero fixtures inspected — a gate that ran over nothing proves nothing")
        return 1
    if failures:
        print(f"\nFAILED ({len(failures)} of {checked}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"\nOK — {checked} checks, gate red on every must_fail and green on every must_pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
