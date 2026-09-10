#!/usr/bin/env python3
"""Fail if a published store config is not what the source renders to.

The sync is automated (see ``render_store_config.py`` and the shared
ga-ops ``addon-publish.yml``). This is the proof that it landed: it re-renders
the source and compares, key by key, against what the store actually serves.

It replaces the per-add-on ``verify_vibe_schema.py``, which compared only the
*key names* of ``schema`` and ``options``, in one direction. That check could
not see any of these, all of which change what the Supervisor does:

* ``ports: {8086/tcp: 8086}`` vs ``{8086/tcp: null}`` — ``ports`` was never
  inspected, so closing a port in the source alone passed as "in sync";
* ``per_user_secrets: false`` vs ``true`` — values were never compared, only
  the presence of the key;
* a key removed from the source but still live in the store.

Exit 0 = store matches the render. Exit 1 = drift, or the store copy could not
be read — this fails CLOSED: an unreadable store is not evidence of agreement.

    python3 scripts/verify_store_sync.py <source-config.yaml> <store-config.yaml> \\
        --image ghcr.io/greenautarky/ga_influxdbv1-{arch}
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

import yaml

# Import the LIVE renderer next to this file — never a copy. A verifier that
# re-implements the render rules verifies its own copy and stays green while
# the real renderer drifts.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from render_store_config import RenderError, render  # noqa: E402


def _fmt(value: Any) -> str:
    text = yaml.safe_dump(value, default_flow_style=True, sort_keys=True).strip()
    return text if len(text) <= 140 else text[:137] + "..."


# `version` is compared but never blocks. A canary is published from a feature
# branch with a pre-release tag and the store is pointed at it by hand, so the
# store legitimately runs ahead of the default branch for a while; the same
# happens for the moments between a bump and the lock-step sync. The previous
# per-add-on checker had this carve-out and said so; it was lost in the move to
# render-based comparison and immediately blocked two publishes of an add-on
# whose canary was doing exactly that. Everything the gate exists for — ports,
# options, schema, image, map, arch — stays hard.
ADVISORY_KEYS = frozenset({"version"})


def compare(rendered: dict[str, Any], store: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Key-by-key diff of two parsed configs. Returns (problems, warnings).
    Pure — the fixtures exercise this exact function, not a re-implementation."""
    problems: list[str] = []
    warnings: list[str] = []
    rk, sk = set(rendered), set(store)
    for key in sorted(rk - sk):
        problems.append(f"key `{key}` is in the source but MISSING from the store")
    for key in sorted(sk - rk):
        problems.append(f"key `{key}` is in the store but GONE from the source")
    for key in sorted(rk & sk):
        if rendered[key] == store[key]:
            continue
        message = f"key `{key}` DIFFERS — source={_fmt(rendered[key])} store={_fmt(store[key])}"
        if key in ADVISORY_KEYS:
            warnings.append(message + " (advisory: a canary or a pending sync)")
        else:
            problems.append(message)
    return problems, warnings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("store")
    ap.add_argument("--image", required=True)
    ap.add_argument("--name", default="GA")
    ap.add_argument("--source-repo", default="greenautarky")
    args = ap.parse_args(argv)

    with open(args.source, encoding="utf-8") as fh:
        source_text = fh.read()
    try:
        with open(args.store, encoding="utf-8") as fh:
            store_cfg = yaml.safe_load(fh.read()) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"::error::could not read the store config {args.store}: {e}")
        print("::error::failing closed — an unreadable store config is not proof of sync")
        return 1

    try:
        rendered_cfg = yaml.safe_load(
            render(source_text, args.image, args.name, args.source_repo)
        ) or {}
    except RenderError as e:
        print(f"::error::the source cannot be rendered into a store entry: {e}")
        print("::error::failing closed — an unrenderable source is not proof of sync")
        return 1

    if not rendered_cfg:
        print("::error::rendered source is empty — refusing to report success")
        return 1

    problems, warnings = compare(rendered_cfg, store_cfg)
    for w in warnings:
        print(f"::warning::{w}")
    if problems:
        print("::error::store config does NOT match the source. The Supervisor reads the "
              "STORE copy, so this change reaches no device:")
        for p in problems:
            print(f"::error::  {p}")
        return 1

    print(f"OK — store matches the rendered source on {len(rendered_cfg)} keys: "
          f"{', '.join(sorted(rendered_cfg))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
