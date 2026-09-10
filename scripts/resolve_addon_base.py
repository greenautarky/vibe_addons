#!/usr/bin/env python3
"""Resolve the BUILD_FROM base image for one add-on and one architecture.

WHY THIS EXISTS
---------------
`addon-publish.yml` used to construct the base image itself:

    BUILD_FROM=ghcr.io/home-assistant/${ha_arch}-base:${base_tag}

which means it never read the add-on's own `build.yaml`. Every Home Assistant
add-on declares its bases there, and every other add-on in this fleet is built
from that file — so for the two add-ons that go through this shared workflow,
editing `build_from` changed nothing about the image that reached a device. A
migration could be reviewed, merged and shown green while being inert.

That matters right now because the fleet's armv7 bases are frozen: upstream's
last armv7 build of `hassio-addons/base` is 18.2.1 (2025-10-16) and
`home-assistant/armv7-base` ended at 3.22. Add-ons are being moved onto
GreenAutarky-owned bases built FROM a live distro, and this workflow would have
silently pinned them back to the dead one.

THE RULES THIS ENCODES
----------------------
1. `build.yaml` wins. If it exists and names the architecture, that is the base.
2. If `build.yaml` exists but does NOT name the architecture, that is an ERROR,
   not a reason to fall back. A file that lists aarch64 and amd64 but not armv7
   is a statement that armv7 is unsupported, and quietly substituting a default
   would build an image nobody declared.
3. If there is no `build.yaml` at all, the legacy construction is used — and it
   is ANNOUNCED at warning level, not info. A silent fallback turns a config
   mistake into an outage nobody sees; this fleet has already paid for that
   once, with a service that read a config file which was not mounted, fell
   back to a hardcoded address a month out of date, and said so in one INFO
   line.
4. Anything unreadable, unparseable, or empty fails. "Could not determine the
   base" must never render as "used the default".

Usage:
    resolve_addon_base.py --addon-dir <dir> --arch <aarch64|amd64|armv7|armhf|i386> \\
                          --legacy-tag <tag> [--github-output <file>]

Prints the resolved image to stdout, and writes `build_from=<image>` plus
`source=build.yaml|legacy` to $GITHUB_OUTPUT when asked.
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - environment problem, not logic
    print("::error::PyYAML is not installed; cannot read build.yaml. "
          "Refusing to guess a base image.", file=sys.stderr)
    raise SystemExit(2)

LEGACY_TEMPLATE = "ghcr.io/home-assistant/{arch}-base:{tag}"


def fail(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"::error::{msg}", file=sys.stderr)
    raise SystemExit(1)


def resolve(addon_dir: str, arch: str, legacy_tag: str) -> tuple[str, str]:
    """Return (image, source) where source is 'build.yaml' or 'legacy'."""
    path = os.path.join(addon_dir, "build.yaml")

    if not os.path.exists(path):
        image = LEGACY_TEMPLATE.format(arch=arch, tag=legacy_tag)
        # Warning, not info — see rule 3 in the module docstring.
        print(
            f"::warning::{addon_dir} has no build.yaml; falling back to the "
            f"legacy base {image}. This add-on cannot be migrated off a frozen "
            f"base until it declares build_from.",
            file=sys.stderr,
        )
        return image, "legacy"

    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001 - any parse error is fatal here
        fail(f"{path} exists but could not be parsed ({exc}). Refusing to fall "
             f"back to a default: an unreadable base declaration is a build "
             f"error, not a reason to build something else.")

    if not isinstance(doc, dict):
        fail(f"{path} did not parse to a mapping (got {type(doc).__name__}). "
             f"Refusing to guess.")

    build_from = doc.get("build_from")
    if not isinstance(build_from, dict) or not build_from:
        fail(f"{path} has no usable `build_from:` mapping. Refusing to guess.")

    image = build_from.get(arch)
    if not image or not str(image).strip():
        declared = ", ".join(sorted(build_from)) or "(none)"
        fail(f"{path} declares build_from for [{declared}] but not for "
             f"'{arch}'. An architecture a build.yaml does not list is "
             f"unsupported, not a candidate for the default base.")

    return str(image).strip(), "build.yaml"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addon-dir", required=True)
    ap.add_argument("--arch", required=True)
    ap.add_argument("--legacy-tag", required=True)
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = ap.parse_args()

    image, source = resolve(args.addon_dir, args.arch, args.legacy_tag)

    print(f"{args.arch}: BUILD_FROM={image}  (source: {source})", file=sys.stderr)
    print(image)

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write(f"build_from={image}\n")
            fh.write(f"source={source}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
