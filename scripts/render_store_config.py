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


class RenderError(RuntimeError):
    """The source cannot be rendered into a valid store entry."""


def _insert_after(lines: list[str], predicate, payload: str) -> bool:
    for i, line in enumerate(lines):
        if predicate(line):
            lines.insert(i + 1, payload)
            return True
    return False


def render(source_text: str, image: str, name: str = "GA", repo: str = "greenautarky") -> str:
    """Source config -> store entry. Raises RenderError rather than emitting a
    store entry that would be broken."""
    lines = source_text.splitlines(keepends=True)
    if not lines:
        raise RenderError("source config is empty")

    has_header = HEADER_MARK in source_text
    has_image = any(line.startswith("image:") for line in lines)

    if not has_image:
        # Anchor order matters. ga_manager's source carries `codenotary:`;
        # ga_default_addon's and ga_hmvapp_addon's do not — anchoring only on
        # codenotary produced a store entry with NO `image:` key at all, which
        # would stop the add-on being install-by-pull: the Supervisor could
        # neither install nor update it. Fall back to `slug:`, and refuse to
        # render if neither anchor exists.
        payload = f"image: {image}\n"
        placed = (
            _insert_after(lines, lambda l: l.startswith("codenotary:"), payload)
            or _insert_after(lines, lambda l: l.startswith("slug:"), payload)
        )
        if not placed:
            raise RenderError(
                "cannot place `image:` — the source has neither a `codenotary:` "
                "nor a `slug:` line to anchor it to"
            )

    if not has_header:
        header = HEADER.format(mark=HEADER_MARK, name=name, repo=repo)
        # After a leading `---` when there is one, otherwise at the very top.
        if lines[0].strip() == "---":
            lines.insert(1, header)
        else:
            lines.insert(0, header)

    out = "".join(lines)
    if not any(l.startswith("image:") for l in out.splitlines()):
        raise RenderError("rendered store entry has no `image:` key — refusing to emit it")
    return out


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
    try:
        sys.stdout.write(render(text, args.image, args.name, args.source_repo))
    except RenderError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
