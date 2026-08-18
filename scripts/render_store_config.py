#!/usr/bin/env python3
"""Render an add-on's published store config.yaml from its source config.yaml.

Every add-on exists twice: the private source repo builds the IMAGE, and this
public store repo carries the ``config.yaml`` **the Supervisor actually reads**
— ports, options, schema, maps, privileges. The source copy is inert at
runtime, so a change made only there ships an image and changes nothing on any
device, silently. That is how bluetooth (#556) and the watchdog/livez
containment (#555) became undeployable fleet-wide (retro 2026-07-22, #566).

``ga_manager`` already solved this: its CI renders the store entry from its
source and pushes it (``scripts/render_vibe_config.py``, full-body sync). This
is the same idea generalised so the shared add-on publish pipeline can do it
for every add-on, and it lives HERE because this repo is public — the private
ga-ops workflow can read it without handing a cross-repo token to every caller.

The store entry is the source config plus exactly two additions, each applied
only when missing, so rendering is idempotent:

  1. a header comment after the leading ``---``
  2. an ``image:`` install-by-pull key after ``codenotary:``

Everything else must be identical. ``ga_default_addon``'s source has no
``image:`` (it gets one here); ``influxdb``'s source already carries it (then
this is a pure copy). Both shapes are covered by the fixtures.

    python3 scripts/render_store_config.py <source-config.yaml> \\
        --image ghcr.io/greenautarky/ga_influxdbv1-{arch} [--source-repo NAME]
"""

from __future__ import annotations

import argparse
import sys

HEADER_MARK = "# Published store entry"

HEADER = """{mark} for the {name} add-on.
# Synced from the source repo greenautarky/{repo} by CI — DO NOT EDIT BY HAND.
# The only delta vs. the source config is the `image:` key: this entry is
# install-by-pull (the multi-arch image is built by the source repo's CI and
# published to GHCR), so the source repo can stay private.
# `version` stays in lock-step with the GHCR image tag and with the OS bake list
# (ha-operating-system buildroot-external/package/hassio/addon-images.json).
"""


def render(source_text: str, image: str, name: str = "GA", repo: str = "greenautarky") -> str:
    has_header = HEADER_MARK in source_text
    has_image = any(line.startswith("image:") for line in source_text.splitlines())

    out: list[str] = []
    for i, line in enumerate(source_text.splitlines(keepends=True), start=1):
        out.append(line)
        if i == 1 and not has_header:
            out.append(HEADER.format(mark=HEADER_MARK, name=name, repo=repo))
        if line.startswith("codenotary:") and not has_image:
            out.append(f"image: {image}\n")
    return "".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--image", required=True, help="install-by-pull image ref, {arch} templated")
    ap.add_argument("--name", default="GA", help="human name used in the header comment")
    ap.add_argument("--source-repo", default="greenautarky", help="source repo name for the header")
    args = ap.parse_args(argv)

    with open(args.source, encoding="utf-8") as fh:
        text = fh.read()
    if not text.strip():
        print("::error::source config is empty — refusing to render", file=sys.stderr)
        return 1
    sys.stdout.write(render(text, args.image, args.name, args.source_repo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
