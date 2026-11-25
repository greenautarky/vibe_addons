#!/usr/bin/env python3
"""Store image gate: every add-on in this store installs an image from OUR registry.

This repository is public and it is a code path onto every device: a fresh
gateway installs its management add-on from here at first boot, before fleet
management is involved. Whoever can change an `image:` line here chooses what a
new device runs. Merging into main is automated (the lockstep jobs open and merge
their own PRs), so the protection cannot be a reviewer — it is this check, run
on every pull request and required by the main-branch ruleset.

Rules, fail-closed:
  * every add-on directory (a directory holding config.yaml / config.yml /
    config.json) declares `image:`;
  * the image is ghcr.io/greenautarky/<name>, optionally with `-{arch}`, a tag or
    a digest — nothing else, no other owner, no look-alike owner, no path tricks;
  * no add-on directory ships a Dockerfile or build.yaml/json: the Supervisor
    would build it on the device from this public tree instead of pulling a
    scanned image;
  * finding zero add-ons is a failure, not a pass.

usage: check_store_images.py [ROOT]      (default: repository root)
"""
import json, os, re, sys

import yaml

IMAGE_RX = re.compile(r"^ghcr\.io/greenautarky/[a-z0-9][a-z0-9_.-]*(-\{arch\})?(:[A-Za-z0-9_.-]+|@sha256:[0-9a-f]{64})?$")
CONFIG_NAMES = ("config.yaml", "config.yml", "config.json")
BUILD_NAMES = ("Dockerfile", "build.yaml", "build.yml", "build.json")
SKIP_DIRS = {".git", ".github", "tests", "scripts", "tools", "node_modules"}


def addon_dirs(root):
    for cur, dirs, files in os.walk(root):
        rel = os.path.relpath(cur, root)
        top = rel.split(os.sep)[0]
        if top in SKIP_DIRS:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        cfg = [f for f in files if f in CONFIG_NAMES]
        if cfg and rel != ".":
            yield cur, cfg, files


def load(path):
    with open(path, encoding="utf8") as fh:
        return (json.load(fh) if path.endswith(".json") else yaml.safe_load(fh)) or {}


def check(root):
    errors, seen = [], 0
    for d, cfgs, files in addon_dirs(root):
        seen += 1
        rel = os.path.relpath(d, root)
        if len(cfgs) > 1:
            errors.append(f"{rel}: more than one config file ({', '.join(cfgs)}) — ambiguous")
        try:
            data = load(os.path.join(d, cfgs[0]))
        except Exception as exc:  # unreadable config is a failure, not a skip
            errors.append(f"{rel}: cannot parse {cfgs[0]}: {exc}")
            continue
        image = data.get("image") if isinstance(data, dict) else None
        if not image:
            errors.append(f"{rel}: no `image:` — the Supervisor would build this add-on on the device")
        elif not isinstance(image, str) or not IMAGE_RX.match(image):
            errors.append(f"{rel}: image {image!r} is not ghcr.io/greenautarky/<name>")
        for b in BUILD_NAMES:
            if b in files:
                errors.append(f"{rel}: ships {b} — store entries must pull a published image, never build")
    if seen == 0:
        errors.append("no add-on directories found — refusing to report a clean scan of nothing")
    return seen, errors


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..")
    seen, errors = check(os.path.abspath(root))
    for e in errors:
        print(f"::error::{e}")
    print(f"store image gate: {seen} add-ons inspected, {len(errors)} violations")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
