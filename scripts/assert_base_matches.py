#!/usr/bin/env python3
"""Assert that a BUILT add-on image really derives from what `build.yaml` declares.

WHY THIS EXISTS
---------------
On 2026-08-20 the same coupling was found three times in three repos in one day:
a CI workflow that CONSTRUCTS the base image name instead of READING the
add-on's declaration.

  * `ga-ops/.github/workflows/addon-publish.yml`
        BUILD_FROM=ghcr.io/home-assistant/${ha_arch}-base:${base_tag}
  * `greenautarky/MQTT` `publish.yaml`
        build args enumerated by name with `sed`; a newly added arg arrived EMPTY
  * `greenautarky/influxDBv1` `publish.yaml`
        the base hardcoded in a `case` statement

All three looked green and shipped nothing. `scripts/resolve_addon_base.py` is
the fix for the *construction* half: every pipeline now READS `build.yaml`.

This script is the fix for the half that resolver cannot cover — proving the
image that came out is the image that was declared. The influxDBv1 instance is
why it exists. `build.yaml` declared:

    ghcr.io/greenautarky/ga-addon-debian-base-armv7:trixie      (Debian 13.6)

the workflow built on:

    ghcr.io/hassio-addons/debian-base/armv7:8.1.4               (older Debian)

and the CVE gate then printed the OS it had detected — a different Debian point
release from the declared one — next to its finding count, and stopped the push.

That is the lesson worth keeping: the gate held the DECLARED base and the
OBSERVED OS in the same run and never compared them. It reported a number where
it could have reported a contradiction. A base migration that had been proven on
real hardware and merged was inert, and the evidence was sitting unasserted in
the log. (The measurements themselves live in the private docs repo, not here.)

WHAT IS COMPARED, AND WHY THAT
------------------------------
Not the image NAME. A tag is mutable and a name proves only what someone typed;
the MQTT instance shows a build arg can be present and empty while every name in
the workflow still reads correctly.

The decisive comparison is the **distro identity the two images report about
themselves**: `/etc/os-release`, plus `/etc/debian_version` or
`/etc/alpine-release`. The declared base is pulled and asked; the built image is
asked; the two answers must agree. This is exactly the signal the CVE gate
already had in hand.

Three levels, in order of how loudly they mean "wrong base":

  1. distro id      debian vs alpine        -> always fatal
  2. major version  13 vs 12                -> always fatal
  3. full version   13.6 vs 13.1            -> fatal by default;
                                               `--allow-point-drift` downgrades
                                               it to a warning

Level 3 is what catches the real 2026-08-20 case if the two Debians happen to
share a major. It is strict by default deliberately: the declared base is pulled
at assertion time and the built image was built minutes earlier from that same
tag, so the only way they disagree on a point release is that the build did not
use it.

Optionally (`--check-lineage`) the built image's `RootFS.Layers` must start with
the declared base's layers — an exact derivation proof rather than a distro-level
one. It is off by default because it misfires on squashed or multi-stage builds,
and a gate that flags correct builds gets overridden by reflex, which is a slower
way of having no gate at all.

THE TRAP THIS SCRIPT IS ABOUT
-----------------------------
The expectation comes from `build.yaml`, resolved through the LIVE
`scripts/resolve_addon_base.py`. It is never read from, or influenced by, the
image under test. An audit that derives its expected value from the artifact it
audits is green by construction.

AND: a comparison that cannot be made FAILS (exit 2). If either side yields no
identity — image missing, file absent, docker unavailable — that is "could not
check", and "could not check" must never render as "checked and fine".

NOTE ON EXECUTION: the images are never RUN. `docker create` + `docker cp` reads
the files out of a container that is never started, so a foreign-architecture
image (armv7 on an amd64 runner) needs no qemu/binfmt.

Usage:
    assert_base_matches.py --addon-dir <dir> --arch armv7 \\
                           --image ghcr.io/greenautarky/mqtt-armv7:1.2.3 \\
                           [--legacy-tag 3.21] [--allow-point-drift] \\
                           [--check-lineage] [--no-pull]

Exit codes:  0 = declared and built agree
             1 = they disagree (the defect this exists to catch)
             2 = could not check (missing image, unreadable identity, no docker)
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
from typing import NamedTuple

HERE = pathlib.Path(__file__).resolve().parent
LIVE_RESOLVER = HERE / "resolve_addon_base.py"

# arch name in build.yaml -> OCI platform string
PLATFORMS = {
    "amd64": "linux/amd64",
    "aarch64": "linux/arm64",
    "armv7": "linux/arm/v7",
    "armhf": "linux/arm/v6",
    "i386": "linux/386",
}

IDENTITY_FILES = ("/etc/os-release", "/etc/debian_version", "/etc/alpine-release")

_NUMERIC = re.compile(r"^\d+(\.\d+)*$")


def err(msg: str) -> None:
    print(f"::error::{msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"::warning::{msg}", file=sys.stderr)


# ── the expectation side ────────────────────────────────────────────────────
def load_resolver():
    """Import the LIVE resolver by path. Never a copy, never a re-declaration.

    If it is gone, that is a failure and not a reason to construct the base name
    here — reconstructing it is the exact defect this script exists to catch.
    """
    if not LIVE_RESOLVER.is_file():
        err(f"cannot find the live base resolver at {LIVE_RESOLVER}. Refusing "
            f"to reconstruct the base image name: constructing instead of "
            f"reading is the defect this assertion exists to catch.")
        raise SystemExit(2)
    spec = importlib.util.spec_from_file_location("resolve_addon_base", LIVE_RESOLVER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── identity: the pure half (fixtures test this without docker) ─────────────
class Identity(NamedTuple):
    distro: str          # "debian", "alpine", "ubuntu", ...
    version: str         # full version as reported, e.g. "13.6", "3.24.1"
    major: str           # "13", "3.24" for alpine (id + feature release)
    evidence: str        # which file(s) the answer came from


def _parse_os_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def parse_identity(files: dict[str, str | None]) -> Identity | None:
    """Derive a distro identity from raw file contents.

    `files` maps the paths in IDENTITY_FILES to their contents, or None when the
    file is absent. Returns None when no identity can be established — the
    caller must treat that as "could not check", never as a pass.
    """
    osr = _parse_os_release(files.get("/etc/os-release") or "")
    distro = (osr.get("ID") or "").strip().lower()

    deb = (files.get("/etc/debian_version") or "").strip()
    alp = (files.get("/etc/alpine-release") or "").strip()

    if not distro:
        if alp:
            distro = "alpine"
        elif deb:
            distro = "debian"
        else:
            return None

    version = ""
    evidence = []

    if distro == "alpine":
        # /etc/alpine-release carries the full patch version; os-release's
        # VERSION_ID is usually the same but the file is the primary source.
        if alp and _NUMERIC.match(alp):
            version, evidence = alp, ["/etc/alpine-release"]
        elif osr.get("VERSION_ID"):
            version, evidence = osr["VERSION_ID"], ["/etc/os-release"]
    elif distro in ("debian", "raspbian"):
        # os-release on Debian only carries the MAJOR ("13"); /etc/debian_version
        # carries the point release ("13.6") — which is the whole reason the
        # 2026-08-20 case is visible at all. Prefer it when it is numeric;
        # on testing/unstable it reads "trixie/sid" instead.
        if deb and _NUMERIC.match(deb):
            version, evidence = deb, ["/etc/debian_version"]
        elif osr.get("VERSION_ID"):
            version, evidence = osr["VERSION_ID"], ["/etc/os-release"]
        elif deb:
            version, evidence = deb, ["/etc/debian_version"]
    else:
        if osr.get("VERSION_ID"):
            version, evidence = osr["VERSION_ID"], ["/etc/os-release"]

    if not version:
        return None

    if distro == "alpine":
        parts = version.split(".")
        major = ".".join(parts[:2]) if len(parts) >= 2 else version
    else:
        major = version.split(".")[0]

    return Identity(distro=distro, version=version, major=major,
                    evidence="+".join(evidence))


class Verdict(NamedTuple):
    ok: bool
    code: str        # match | distro | major | point | undetermined
    message: str


def compare_identity(declared: Identity | None, built: Identity | None,
                     allow_point_drift: bool = False) -> Verdict:
    """Compare the declared base's identity with the built image's.

    A side that could not be determined is a FAILURE, never a pass.
    """
    if declared is None and built is None:
        return Verdict(False, "undetermined",
                       "neither the declared base nor the built image reported a "
                       "distro identity — could not check, which is not a pass")
    if declared is None:
        return Verdict(False, "undetermined",
                       "the DECLARED base reported no distro identity — could "
                       "not check, which is not a pass")
    if built is None:
        return Verdict(False, "undetermined",
                       "the BUILT image reported no distro identity — could not "
                       "check, which is not a pass")

    if declared.distro != built.distro:
        return Verdict(False, "distro",
                       f"distro mismatch: build.yaml declares a "
                       f"{declared.distro} base, the built image is "
                       f"{built.distro}")

    if declared.major != built.major:
        return Verdict(False, "major",
                       f"{declared.distro} release mismatch: declared "
                       f"{declared.distro} {declared.major} "
                       f"({declared.version}), built image is "
                       f"{built.distro} {built.major} ({built.version})")

    if declared.version != built.version:
        msg = (f"{declared.distro} point-release mismatch: declared "
               f"{declared.version}, built image is {built.version}. The "
               f"declared base was pulled just now and the image was built from "
               f"that same tag, so a disagreement here means the build did not "
               f"use it.")
        if allow_point_drift:
            return Verdict(True, "point-drift-allowed",
                           msg + " (downgraded by --allow-point-drift)")
        return Verdict(False, "point", msg)

    return Verdict(True, "match",
                   f"declared and built agree: {built.distro} {built.version} "
                   f"(declared via {declared.evidence}, built via "
                   f"{built.evidence})")


def compare_lineage(base_layers: list[str] | None,
                    built_layers: list[str] | None) -> Verdict:
    """The built image's rootfs layers must START WITH the base's layers.

    An image built `FROM base` keeps the base's diff_ids as a prefix. This is an
    exact derivation proof rather than a distro-level one — and it misfires on
    squashed or multi-stage builds, which is why it is opt-in.
    """
    if not base_layers or not built_layers:
        return Verdict(False, "undetermined",
                       "lineage could not be read from one or both images — "
                       "could not check, which is not a pass")
    if len(built_layers) < len(base_layers):
        return Verdict(False, "lineage",
                       f"the built image has fewer layers ({len(built_layers)}) "
                       f"than the declared base ({len(base_layers)}); it cannot "
                       f"derive from it")
    prefix = built_layers[:len(base_layers)]
    if prefix != base_layers:
        first = next((i for i, (a, b) in enumerate(zip(base_layers, prefix))
                      if a != b), 0)
        return Verdict(False, "lineage",
                       f"the built image's layers diverge from the declared "
                       f"base at layer {first}: base has {base_layers[first]}, "
                       f"image has {prefix[first]}")
    return Verdict(True, "match",
                   f"lineage ok: the built image's first {len(base_layers)} "
                   f"layers are exactly the declared base's")


# ── identity: the docker half ───────────────────────────────────────────────
def _docker(*args: str, capture: bool = True) -> tuple[int, bytes, str]:
    proc = subprocess.run(
        ["docker", *args],
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout or b"", (proc.stderr or b"").decode(
        "utf-8", "replace")


def require_docker() -> None:
    if shutil.which("docker") is None:
        err("docker is not available; the assertion cannot be made. That is "
            "'could not check', not 'checked and fine'.")
        raise SystemExit(2)


def pull(image: str, platform: str) -> None:
    rc, _, stderr = _docker("pull", "--platform", platform, image)
    if rc != 0:
        err(f"could not pull {image} for {platform}: {stderr.strip()}")
        raise SystemExit(2)


def read_image_files(image: str, platform: str,
                     paths=IDENTITY_FILES) -> dict[str, str | None]:
    """Read files out of an image WITHOUT running it.

    `docker create` materialises a container's filesystem without executing
    anything, so this works for a foreign architecture with no qemu/binfmt.
    """
    rc, out, stderr = _docker("create", "--platform", platform, image)
    if rc != 0:
        err(f"could not create a container from {image} ({platform}): "
            f"{stderr.strip()}")
        raise SystemExit(2)
    cid = out.decode().strip()
    result: dict[str, str | None] = {}
    try:
        for path in paths:
            # -L follows symlinks. On Debian /etc/os-release is a symlink to
            # /usr/lib/os-release; without -L `docker cp` hands back the LINK,
            # the tar member is not a regular file, and the read silently
            # returns nothing. Measured on 2026-08-20: every one of the five
            # real base images reported os-release as absent until -L was added.
            rc, blob, _ = _docker("cp", "-L", f"{cid}:{path}", "-")
            if rc != 0 or not blob:
                result[path] = None
                continue
            try:
                with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                    member = next((m for m in tf.getmembers() if m.isfile()), None)
                    fh = tf.extractfile(member) if member else None
                    result[path] = fh.read().decode("utf-8", "replace") if fh else None
            except Exception:  # noqa: BLE001
                result[path] = None
    finally:
        _docker("rm", "-f", cid)
    return result


def image_layers(image: str) -> list[str] | None:
    rc, out, _ = _docker("image", "inspect", "--format", "{{json .RootFS.Layers}}",
                         image)
    if rc != 0:
        return None
    try:
        layers = json.loads(out.decode().strip())
    except Exception:  # noqa: BLE001
        return None
    return layers if isinstance(layers, list) else None


def identity_of(image: str, platform: str, do_pull: bool) -> Identity | None:
    if do_pull:
        pull(image, platform)
    files = read_image_files(image, platform)
    return parse_identity(files)


# ── entry point ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Assert a built add-on image derives from the base its "
                    "build.yaml declares.")
    ap.add_argument("--addon-dir", required=True,
                    help="directory containing the add-on's build.yaml")
    ap.add_argument("--arch", required=True, choices=sorted(PLATFORMS))
    ap.add_argument("--image", required=True,
                    help="the BUILT image to check (local tag or registry ref)")
    ap.add_argument("--legacy-tag", default="",
                    help="passed to the resolver for the no-build.yaml case")
    ap.add_argument("--allow-point-drift", action="store_true",
                    help="downgrade a point-release disagreement to a warning")
    ap.add_argument("--check-lineage", action="store_true",
                    help="also require the built image's rootfs layers to start "
                         "with the declared base's (exact derivation proof; "
                         "misfires on squashed/multi-stage builds)")
    ap.add_argument("--no-pull", action="store_true",
                    help="do not refresh the DECLARED base from its registry; "
                         "use whatever copy is already local")
    args = ap.parse_args()

    platform = PLATFORMS[args.arch]
    require_docker()

    # EXPECTATION — from build.yaml, through the live resolver. Never from the
    # image under test.
    resolver = load_resolver()
    declared_image, source = resolver.resolve(args.addon_dir, args.arch,
                                              args.legacy_tag)
    print(f"declared base : {declared_image}  (from {source})")
    print(f"built image   : {args.image}")
    print(f"platform      : {platform}")

    if source == "legacy":
        warn(f"{args.addon_dir} has no build.yaml; the 'declaration' being "
             f"asserted against is the legacy constructed name, which proves "
             f"much less. Give this add-on a build.yaml.")

    # The declared base is pulled so the expectation is the CURRENT content of
    # the tag, not a stale local copy. The built image is never pulled: in a
    # publish pipeline it was created locally seconds ago, and `docker create`
    # fetches it anyway if it is a registry reference that is not present.
    declared_id = identity_of(declared_image, platform, do_pull=not args.no_pull)
    built_id = identity_of(args.image, platform, do_pull=False)

    print(f"declared base reports : {declared_id}")
    print(f"built image reports   : {built_id}")

    verdict = compare_identity(declared_id, built_id, args.allow_point_drift)
    if not verdict.ok:
        err(f"BASE MISMATCH [{verdict.code}] for {args.addon_dir} ({args.arch}): "
            f"{verdict.message}")
        err("build.yaml declares one base and the image was built on another. "
            "This is the 2026-08-20 defect class: a workflow that constructs "
            "the base instead of reading the declaration.")
        return 2 if verdict.code == "undetermined" else 1
    print(f"OK: {verdict.message}")
    if verdict.code == "point-drift-allowed":
        warn(verdict.message)

    if args.check_lineage:
        lin = compare_lineage(image_layers(declared_image),
                              image_layers(args.image))
        if not lin.ok:
            err(f"LINEAGE MISMATCH [{lin.code}]: {lin.message}")
            return 2 if lin.code == "undetermined" else 1
        print(f"OK: {lin.message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
